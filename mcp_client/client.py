"""MCP client bridge for the AIBA ``mcp_call`` tool (Phase 7).

Security posture
----------------
This module is the *only* place AIBA talks to an MCP server and it is strict:

* The real ``mcp`` SDK (Pip extra ``[mcp]``) is imported lazily inside the
  async call path only, so a base AIBA install that lacks the optional extra
  imports this file fine and just reports an actionable "install the [mcp]
  extra" diagnostic when ``mcp_call`` is driven.
* A single, static, manifest-backed AIBA tool named ``mcp_call`` is the only
  MCP entry point. It never creates dynamic per-server tool names, so every
  AIBA-wide policy gate (permissions.json ``mcp_call`` row + the
  ``AIBA_MCP_ENABLED`` feature flag, orchestrated by the ToolRegistry) applies
  automatically — never a tool name the capability manifest/validator could not
  statically see.
* ``mcp_call`` takes ``{server_id, tool, arguments}`` and resolves them in this
  strict, fail-closed order:
  1. The whole-tool AIBA gates have already run in the registry
     (``check_tool('mcp_call')`` + feature flag + approval). We fail closed
     again here in case the method is driven directly: subsystem disabled, or
     config absent/malformed with no enabled server => a clear denial and no
     process/network touch.
  2. The named server must exist and be ``enabled``; a remote ``http`` server
     additionally requires the ``AIBA_MCP_REMOTE`` flag (off by default).
  3. The named *remote* tool must be explicitly allowlisted **and enabled** in
     that server's per-tool policy; nothing is auto-approved.
  4. A server's per-tool ``requires_approval`` is observed through the wired-in
     approver (the ToolRegistry drives approval for all of ``mcp_call`` too); a
     denial aborts before any process/network touch.
  5. Stdio servers launch with an explicit argv (no shell), a minimal
     environment containing only allowlisted var NAMES resolved from the OS at
     launch, a confined cwd, inside the SDK's own process group (terminated on
     teardown). Remote URLs are https-only and pass
     ``security.urlguard.forbidden_open_target``; HTTP redirect-following is
     disabled so an https URL can never silently hop to an internal target.
* Every argv element / name is validated at config load; this module re-validates
  the dynamic request fields too.
* Output is bounded to the configured byte cap. Anything this module audits or
  returns is run through ``scrub_secrets`` first so credential-like values never
  leak into AIBA's AuditLog (which does not redact) or the model stream.

Because the MCP SDK is async while a Tool handler is synchronous, the awaited
coroutine is executed to completion on a dedicated per-call background event
loop, bounded by start/call timeouts.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from _thread import get_ident as _thread_ident

from mcp_client import config as _cfg
from mcp_client import policy as _policy
from mcp_client.availability import EXTRA_LABEL, scrub_secrets, sdk_available

log = logging.getLogger("aiba.mcp")

#: Ceiling on how many simultaneous MCP remote operations AIBA may run. Bounds
#: subprocess/thread churn; calls beyond this block until a slot frees.
MAX_CONCURRENT_CALLS = 4


class MCPRemoteDisabled(Exception):
    """Remote http server requested while AIBA_MCP_REMOTE is off."""


class MCPStartTimeout(Exception):
    """Server did not initialise within its configured startup window."""


class MCPCallTimeout(Exception):
    """A remote call exceeded its configured call window."""


def _mk_result(ok: bool, output: Any = None, error: Optional[str] = None) -> Any:
    from tools.base import ToolResult

    return ToolResult(ok, output=output, error=error)


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[output truncated by AIBA MCP output policy]"


def _content_to_text(result: Any, byte_limit: int) -> str:
    """Render an MCP ``CallToolResult`` to plain bounded text.

    Concatenates ``TextContent`` blocks and, if present, JSON-serialises
    ``structured_content``. Non-text payloads (image/resource/audio) are named
    but never replayed, so we stay bounded and safe against exotic content.
    """
    parts: list[str] = []
    content = getattr(result, "content", None) or []
    if isinstance(content, list):
        for block in content:
            kind = getattr(block, "type", None)
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(str(text))
            elif kind in ("image", "resource", "audio"):
                parts.append(f"[MCP {kind} content omitted by AIBA output policy]")
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        try:
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            parts.append(repr(structured))
    text = "\n".join(p for p in parts if p)
    return _truncate_text(text, int(byte_limit))


def _build_stdio_env(srv: _cfg.McpServerConfig) -> dict[str, str] | None:
    """Assemble the extra env for a stdio child from allowlisted var NAMES.

    Only operator-listed names are read from the OS env at launch; the values
    are forwarded to the child and stored nowhere by AIBA. Secret-looking env
    names were already rejected at config load.
    """
    if not srv.env_names:
        return None
    env: dict[str, str] = {}
    for name in srv.env_names:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
        else:
            log.warning(
                "MCP stdio server %r env var %r is not set in the process "
                "environment and was skipped.",
                srv.server_id,
                name,
            )
    return env or None


class MCPClientController:
    """Gate + synchronous bridge to configured MCP servers.

    Constructed once per AgentLoop. It is cheap and inert when disabled: config
    is read lazily on first call, so an unconfigured install adds no startup
    cost and no network/process activity until an operator enables
    ``AIBA_MCP_ENABLED``, lists ``mcp_call`` in permissions.json, and configures
    at least one enabled server in ``config/mcp_servers.json``.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        root_dir: str | Path | None = None,
        audit: Any | None = None,
        approver: Callable[[str, str], bool] | None = None,
        remote_enabled: bool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._root_dir = str(root_dir) if root_dir is not None else str(Path.cwd())
        self._audit_log = audit
        self._approver = approver
        if remote_enabled is not None:
            self._remote_enabled = bool(remote_enabled)
        else:
            self._remote_enabled = bool(
                os.getenv(_policy.FEATURE_FLAG_REMOTE, "").strip().lower()
                in {"1", "true", "yes", "on", "y"}
            )
        self._load_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._config_path: str | None = None
        self._loaded: Optional[_cfg.MCPConfig] = None
        self._load_error: str | None = None
        # A map thread-ident -> its dedicated running event loop, so the sync
        # bridge can detect (and avoid nesting in) an existing loop.
        self._owns_loop_thread: int | None = None

    # -- public facade ------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def remote_enabled(self) -> bool:
        return self._remote_enabled

    def clear_config_cache(self) -> None:  # tests / reload
        self._loaded = None
        self._config_path = None
        self._load_error = None

    def load_config(self) -> _cfg.MCPConfig:
        """Load + cache the parsed MCP config (fail-closed, file-read only).

        A malformed config raises :class:`MCPConfigError`; a missing/empty config
        returns an empty (disabled) config.
        """
        if self._loaded is not None:
            if self._load_error:
                raise _cfg.MCPConfigError(self._load_error)
            return self._loaded
        path = Path(self._root_dir) / "config" / _cfg.DEFAULT_CONFIG_NAME
        try:
            loaded = _cfg.load_config(path)
        except _cfg.MCPConfigError as exc:
            self._load_error = str(exc)
            raise
        self._config_path = loaded.source_path
        self._loaded = loaded
        return loaded

    def _write_audit(self, event: str, **data: Any) -> None:
        audit = self._audit_log
        if audit is None:
            return
        try:
            scrubbed: dict[str, Any] = scrub_secrets(dict(data))  # type: ignore[assignment]
            audit.record(event, **scrubbed)
        except Exception:  # pragma: no cover - auditing must never break a call
            log.exception("MCP controller could not write audit record %s", event)

    # -- diagnostics ---------------------------------------------------------
    def server_ids(self) -> list[str]:
        """Configured server ids (diagnostics). Never triggers a connect."""
        try:
            cfg = self.load_config()
        except _cfg.MCPConfigError:
            return []
        return sorted(cfg.servers.keys())

    def status(self) -> dict[str, Any]:
        """Truthful, safe status for diagnostics/CLIs (no secrets, no network)."""
        sdk_ok = sdk_available()
        error: str | None = None
        servers: list[dict[str, Any]] = []
        enabled_count = 0
        if self._enabled:
            try:
                cfg = self.load_config()
                for sid, srv in sorted(cfg.servers.items()):
                    dev_enabled = bool(srv.enabled)
                    servers.append(
                        {
                            "server_id": sid,
                            "name": srv.name,
                            "transport": srv.transport,
                            "enabled": dev_enabled,
                            "remote": not srv.is_stdio,
                            "stdio_command": srv.command if srv.is_stdio else None,
                            "allowlisted_tools": sorted(
                                t for t, p in srv.tools.items() if p.enabled
                            ),
                        }
                    )
                    if dev_enabled:
                        enabled_count += 1
            except _cfg.MCPConfigError as exc:
                error = str(exc)
                servers = []
                enabled_count = 0
        available = (
            bool(self._enabled) and error is None and enabled_count > 0 and sdk_ok
        )
        return {
            "available": available,
            "feature_flag_on": self._enabled,
            "sdk_available": sdk_ok,
            "sdk_label": EXTRA_LABEL,
            "enabled_server_count": enabled_count,
            "servers": servers,
            "remote_enabled": self._remote_enabled,
            "config_error": error,
            "config_path": self._config_path,
        }

    # -- mcp_call handler -----------------------------------------------------
    def execute(
        self,
        server_id: str,
        tool: str,
        arguments: Optional[dict[str, Any]],
    ) -> Any:
        """Synchronous handler for the ``mcp_call`` AIBA tool.

        Resolves + validates the request, then bridges to async on a dedicated
        per-call event loop. Returns a ``tools.base.ToolResult``.
        """
        if not isinstance(server_id, str):
            return _mk_result(False, error="mcp_call 'server_id' must be a string")
        if not isinstance(tool, str):
            return _mk_result(False, error="mcp_call 'tool' must be a string")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _mk_result(False, error="mcp_call 'arguments' must be a JSON object")

        scrubbed_for_audit = scrub_secrets(arguments)

        # Fail-closed master switch (belt & suspenders alongside the registry
        # feature-flag/permission gates).
        if not self._enabled:
            self._write_audit(
                "mcp_call_denied",
                server_id=server_id,
                tool=tool,
                reason="MCP disabled",
            )
            return _mk_result(
                False,
                error=(
                    "MCP is not enabled. Set AIBA_MCP_ENABLED=true, list "
                    "'mcp_call' (enabled) in config/permissions.json, and "
                    "configure a server in config/mcp_servers.json."
                ),
            )
        if not sdk_available():
            self._write_audit(
                "mcp_call_denied",
                server_id=server_id,
                tool=tool,
                reason="MCP SDK missing",
            )
            return _mk_result(
                False,
                error=(
                    "mcp_call requires the optional MCP SDK. Install the "
                    f"[mcp] extra ({EXTRA_LABEL.split(':')[-1]}) and restart, "
                    "or hide this tool via AIBA_MCP_ENABLED=false."
                ),
            )

        # Safe token validation before touching config.
        try:
            _policy.assert_safe_server_id(server_id)
        except ValueError as exc:
            return _mk_result(False, error=f"{exc}")
        if not _policy.validate_component(tool):
            return _mk_result(
                False,
                error=(
                    "Invalid remote tool name; must be a non-empty "
                    "[A-Za-z0-9_-] token."
                ),
            )

        try:
            cfg = self.load_config()
        except _cfg.MCPConfigError as exc:
            return _mk_result(
                False,
                error=f"MCP config is invalid and MCP is not usable: {exc}",
            )
        srv = cfg.get(server_id)
        if srv is None:
            return _mk_result(
                False,
                error=f"Unknown MCP server {server_id!r}. No such server is configured.",
            )
        if not srv.enabled:
            return _mk_result(
                False,
                error=f"MCP server {server_id!r} is configured but disabled.",
            )

        # Fail-closed per-server-tool allowlist.
        tool_row = srv.tool_policy(tool)
        if tool_row is None:
            return _mk_result(
                False,
                error=f"Invalid MCP tool name for server {server_id!r}.",
            )
        if not tool_row.enabled:
            self._write_audit(
                "mcp_call_denied",
                server_id=server_id,
                tool=tool,
                reason="not allowlisted",
            )
            return _mk_result(
                False,
                error=(
                    f"Remote tool {tool!r} on server {server_id!r} is not in the "
                    "operator allowlist (disabled). Allowlist it under "
                    f"'servers.{server_id}.tools.{tool}.enabled'."
                ),
            )

        # Operator-set, fine-grained approval for this particular remote tool.
        if tool_row.requires_approval and self._approver is not None:
            prompt = json.dumps(scrubbed_for_audit, ensure_ascii=False)[:500]
            if not self._approver(f"mcp_call({server_id}:{tool})", prompt):
                return _mk_result(False, error="User approval denied")

        # Remote (http) transport requires the AIBA_MCP_REMOTE flag.
        if not srv.is_stdio and not self._remote_enabled:
            return _mk_result(
                False,
                error=(
                    f"Server {server_id!r} uses a remote http transport, which "
                    "is disabled. Set AIBA_MCP_REMOTE=true to allow it."
                ),
            )

        self._write_audit(
            "mcp_call_start",
            server_id=server_id,
            tool=tool,
            arguments=scrubbed_for_audit,
        )
        try:
            result = self._run_on_loop(srv, tool, arguments)
        except Exception as exc:  # noqa: BLE001 - bridge never crashes the caller
            self._write_audit(
                "mcp_call_error",
                server_id=server_id,
                tool=tool,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            return _mk_result(False, error=f"{type(exc).__name__}: {exc}")

        ok, output, error = result
        self._write_audit(
            "mcp_call_end",
            server_id=server_id,
            tool=tool,
            ok=ok,
            error=(error or None),
        )
        if not ok:
            return _mk_result(False, error=(error or "MCP call failed"))
        return _mk_result(True, output)

    # -- sync -> async bridge ------------------------------------------------
    def _call_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        if self._load_executor is None:
            self._load_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=MAX_CONCURRENT_CALLS,
                thread_name_prefix="aiba-mcp",
            )
        return self._load_executor

    def _run_on_loop(
        self,
        srv: _cfg.McpServerConfig,
        tool: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, Any, Optional[str]]:
        """Run the async MCP operation, awaiting it to completion.

        Executed on a background thread that owns a fresh event loop so we never
        nest inside an already-running loop (AIBA may be driven from an async
        connector). Timing is bounded by the configured call timeout plus a
        small backstop; the SDK teardown terminates the child's process group
        on cancellation, so a stuck server cannot leak a process.
        """
        executor = self._call_executor()

        async def _target() -> tuple[bool, Any, Optional[str]]:
            try:
                if srv.is_stdio:
                    out, is_error = await self._async_stdlib_call(srv, tool, arguments)
                else:
                    out, is_error = await self._async_http_call(srv, tool, arguments)
            except MCPRemoteDisabled as exc:
                return False, None, str(exc)
            except (MCPStartTimeout, MCPCallTimeout, TimeoutError, asyncio.TimeoutError) as exc:
                return False, None, f"MCP call timed out: {exc}"
            except Exception as exc:  # noqa: BLE001 - surface as tool error
                return False, None, f"{type(exc).__name__}: {exc}"
            if is_error:
                return False, None, _truncate_text(out, srv.max_output_bytes)
            return True, scrub_secrets(out), None

        future = executor.submit(_run_coro_on_fresh_loop, _target())
        # Backstop wall-clock bound slightly larger than the SDK call timeout so
        # a wedged SDK can still be surfaced rather than hanging forever.
        backstop = float(max(srv.startup_timeout_s, srv.call_timeout_s, 1.0) + 10.0)
        try:
            return future.result(timeout=backstop)
        except concurrent.futures.TimeoutError:
            return False, None, (
                "MCP call exceeded the overall time budget and was cancelled."
            )

    # -- async transports -----------------------------------------------------
    async def _async_stdlib_call(
        self,
        srv: _cfg.McpServerConfig,
        tool: str,
        arguments: dict[str, Any],
    ) -> tuple[str, bool]:
        """Call *tool* on a stdio server, spawning its subprocess argv-only."""
        # Lazy import: only here do we require the optional MCP SDK.
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=srv.command,
            args=list(srv.args),
            env=_build_stdio_env(srv),
            cwd=srv.working_dir,
        )

        async def _open_and_call() -> tuple[str, bool]:
            async with stdio_client(params) as _streams:
                r_stream, w_stream = _streams
                async with ClientSession(r_stream, w_stream) as session:
                    await asyncio.wait_for(session.initialize(), timeout=srv.startup_timeout_s)
                    tool_result = await asyncio.wait_for(
                        session.call_tool(tool, dict(arguments)),
                        timeout=srv.call_timeout_s,
                    )
                    text = _content_to_text(tool_result, srv.max_output_bytes)
                    return text, bool(getattr(tool_result, "is_error", False))

        # stdio_client itself performs the spawn; bound it too so a wedged launcher
        # cannot hang us. The context manager teardown kills the process group.
        out, is_error = await asyncio.wait_for(
            _open_and_call(), timeout=float(srv.startup_timeout_s + srv.call_timeout_s + 5.0)
        )
        return out, is_error

    async def _async_http_call(
        self,
        srv: _cfg.McpServerConfig,
        tool: str,
        arguments: dict[str, Any],
    ) -> tuple[str, bool]:
        """Call *tool* on a remote http (Streamable HTTP) server over https."""
        # Remote http transport additionally requires the AIBA_MCP_REMOTE flag.
        if not self._remote_enabled:
            raise MCPRemoteDisabled(
                f"Server {srv.server_id!r} uses a remote http transport, which "
                "is disabled. Set AIBA_MCP_REMOTE=true to allow it."
            )
        # Lazy imports: only here do we require the optional MCP SDK and httpx.
        import httpx2

        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        # SSRF hardening: never follow redirects (the SDK default follows them).
        # An https URL we vetted must not silently hop to a private/internal
        # host after connect.
        async with httpx2.AsyncClient(
            follow_redirects=False,
            timeout=httpx2.Timeout(
                connect=srv.startup_timeout_s,
                read=max(srv.call_timeout_s, 30.0),
                write=srv.call_timeout_s,
                pool=srv.startup_timeout_s,
            ),
        ) as http_client:
            async with streamable_http_client(
                srv.url,
                http_client=http_client,
                terminate_on_close=False,
            ) as _streams:
                r_stream, w_stream = _streams
                async with ClientSession(r_stream, w_stream) as session:
                    await asyncio.wait_for(session.initialize(), timeout=srv.startup_timeout_s)
                    tool_result = await asyncio.wait_for(
                        session.call_tool(tool, dict(arguments)),
                        timeout=srv.call_timeout_s,
                    )
                    text = _content_to_text(tool_result, srv.max_output_bytes)
                    return text, bool(getattr(tool_result, "is_error", False))


def _run_coro_on_fresh_loop(coro: Any) -> Any:
    """Run *coro* to completion on a fresh event loop on this worker thread."""
    return asyncio.run(coro)

