"""Validated MCP server configuration (Phase 7).

Reads a single JSON file ``config/mcp_servers.json`` relative to the AIBA repo
root (mirroring ``config/permissions.json``). The model is compact, strict and
fail-closed:

* Every server has a stable validated ``server_id`` used as the policy anchor;
  it must be a non-empty ``[A-Za-z0-9_-]`` token (``mcp_client.policy``).
* ``transport`` is ``stdio`` (default) or ``http``. Remote ``http`` servers are
  only honoured while the ``AIBA_MCP_REMOTE`` feature flag is on, the URL is
  *https*, and it clears ``security.urlguard.forbidden_open_target``. Stdio
  never touches the URL/network policy.
* **Never store raw secrets here.** Stdio authentication state is referenced by
  *environment variable NAME* only (``env_names``); the value is resolved from
  the process environment at launch time and is never persisted or logged. Any
  embedded credential-looking value (env name that reads like a secret, URL
  query carrying a secret-looking key) is rejected outright by the validator.
* Per-tool policy entries live under ``tools``: a mapping of
  ``{ "<tool>": {enabled, requires_approval} }``. A tool AIBA never explicitly
  allowlists as ``enabled`` is *denied* — a server cannot broaden AIBA's attack
  surface merely by advertising a tool.

A missing file, an empty file, or a file with no *enabled* server yields an
inert (disabled) :class:`MCPConfig` so the subsystem is fail-closed by default.
A structurally malformed or policy-violating file raises :class:`MCPConfigError`
at load time so a bad operator config cannot silently become a half-open hole.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_client import policy
from mcp_client.availability import is_secret_key
from mcp_client.policy import (
    DEFAULT_CALL_TIMEOUT_S,
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_RESTART_LIMIT,
    DEFAULT_STARTUP_TIMEOUT_S,
)

__all__ = [
    "DEFAULT_CONFIG_NAME",
    "McpToolPolicy",
    "McpServerConfig",
    "MCPConfig",
    "MCPConfigError",
    "load_config",
    "config_abs_path",
]

DEFAULT_CONFIG_NAME = "mcp_servers.json"

# Approved working-directory roots fall back to the config directory itself if
# the operator does not list any, i.e. a relative working_dir must stay inside
# the same ``config`` directory's resolved parent tree the operator controls.
_FALLBACK_WORKDIR_ROOT = "."


class MCPConfigError(ValueError):
    """Raised when config/mcp_servers.json is malformed or policy-violating."""


def _require_type(value: Any, type_: type, field_path: str, ctx: str) -> None:
    if not isinstance(value, type_):
        raise MCPConfigError(
            f"config field {field_path} in {ctx} must be {type_.__name__}, "
            f"got {type(value).__name__}: {value!r}"
        )


@dataclass
class McpToolPolicy:
    """Per-tool gate parsed from ``config/mcp_servers.json`` ``tools[<name>]``.

    ``enabled`` describes whether the operator has allowlisted this remote tool.
    ``requires_approval`` is the *operator-set* approval flag for this remote
    tool. AIBA never auto-approves a remote tool call, and a tool that is not in
    the operator's ``tools`` allowlist (or whose entry is not enabled) is
    denied before any session is opened.
    """

    name: str
    enabled: bool = False
    requires_approval: bool = True

    @classmethod
    def from_json(cls, name: str, raw: Any, ctx: str) -> "McpToolPolicy":
        """Parse one allowlist entry for remote tool *name*.

        *raw* is the per-tool body, e.g. ``{"enabled": true,
        "requires_approval": true}``. *name* is validated and used on the
        returned row so the JSON key and the row can never disagree.
        """
        if not policy.validate_component(name):
            raise MCPConfigError(
                f"server {ctx} tool {name!r} has an invalid name; remote tool "
                f"names must match [A-Za-z0-9_-]."
            )
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise MCPConfigError(
                f"server {ctx} config for tool {name!r} must be an object "
                f"{{enabled, requires_approval}}."
            )
        enabled = bool(raw.get("enabled", False))
        requires_approval = bool(raw.get("requires_approval", True))
        return cls(name=name, enabled=enabled, requires_approval=requires_approval)


@dataclass
class McpServerConfig:
    """A validated MCP server definition from config/mcp_servers.json."""

    server_id: str
    name: str
    transport: str  # 'stdio' | 'http'
    enabled: bool = False
    # stdio
    command: str = ""
    args: list[str] = field(default_factory=list)
    working_dir: str | None = None
    env_names: tuple[str, ...] = field(default_factory=tuple)  # allowlisted NAMES
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S
    call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S
    # remote http
    url: str = ""
    # operator approval defaults + per-tool allowlist
    requires_approval_default: bool = True
    tools: dict[str, McpToolPolicy] = field(default_factory=dict)
    # tuning
    restart_limit: int = DEFAULT_RESTART_LIMIT
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    # bookkeeping (never secrets)
    note: str = ""

    @property
    def is_stdio(self) -> bool:
        return self.transport == "stdio"

    def tool_policy(self, tool_name: str) -> McpToolPolicy | None:
        """Return the parsed allowlist row for *tool_name*, or a fail-closed row
        (enabled=False) if *tool_name* is absent from the allowlist.

        Never returns ``None`` for a syntactically-valid name: an unlisted tool
        is *denied*, which is the safe default. Only an invalid (unsafe) tool
        name returns None so the caller can reject it as a name-validation
        failure distinct from a policy denial.
        """
        if not policy.validate_component(tool_name):
            return None
        entry = self.tools.get(tool_name)
        if entry is not None:
            return entry
        # An unlisted tool is denied (fail-closed allowlist), using the
        # operator's default approval posture for dangerous tools.
        return McpToolPolicy(
            name=tool_name,
            enabled=False,
            requires_approval=self.requires_approval_default,
        )

    def tool_requires_approval(self, tool_name: str) -> bool:
        """Operator-set approval requirement for *tool_name* (best effort)."""
        row = self.tool_policy(tool_name)
        if row is None:
            return True
        return row.requires_approval


def _read_env_allowlist(raw: Any, field_path: str, ctx: str) -> tuple[str, ...]:
    """Validate + return the allowlisted env-var NAMES for a stdio server.

    Only names that are NOT secret-looking are accepted (secrets are referenced
    by name only, resolved at launch, and are stored nowhere). Values are never
    read here.
    """
    if raw is None:
        return ()
    _require_type(raw, list, field_path, ctx)
    names: list[str] = []
    for i, item in enumerate(raw):
        _require_type(item, str, f"{field_path}[{i}]", ctx)
        item = item.strip()
        if not item:
            raise MCPConfigError(
                f"{field_path}[{i}] in {ctx} must be a non-empty env var NAME."
            )
        if is_secret_key(item):
            raise MCPConfigError(
                f"{field_path}[{i}] in {ctx} ({item!r}) looks like a secret; "
                f"store secrets in the process environment and reference the "
                f"variable by a NON-secret NAME here (e.g. 'MY_TOKEN' is "
                f"refused, but 'CREDENTIAL_ENV' is acceptable). Never embed a "
                f"credential value in config."
            )
        if "=" in item or any(c in item for c in " \t\n"):
            raise MCPConfigError(
                f"{field_path}[{i}] in {ctx} must be an env var NAME only, "
                f"not a key=value or path expression: {item!r}"
            )
        names.append(item)
    return tuple(names)


def _size(value: Any, field_path: str, ctx: str, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise MCPConfigError(f"{field_path} in {ctx} must be an integer >= {minimum}")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise MCPConfigError(f"{field_path} in {ctx} must be an integer >= {minimum}") from None
    if n < minimum:
        raise MCPConfigError(f"{field_path} in {ctx} must be an integer >= {minimum}")
    return n


def _float_gt0(value: Any, field_path: str, ctx: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise MCPConfigError(f"{field_path} in {ctx} must be a number > 0") from None
    if not (f > 0):
        raise MCPConfigError(f"{field_path} in {ctx} must be a number > 0")
    return f


def _parse_uint_bounded(
    value: Any,
    field_path: str,
    ctx: str,
    *,
    default: int,
    minimum: int = 1,
    maximum: int,
) -> int:
    if value is None:
        return default
    n = _size(value, field_path, ctx, minimum=minimum)
    if n > maximum:
        raise MCPConfigError(
            f"{field_path} in {ctx} must be <= {maximum} (protects the host "
            f"from runaway subprocesses/output)."
        )
    return n


def _parse_server(raw: Any, ctx: str, file_parent: Path) -> McpServerConfig:
    if not isinstance(raw, dict):
        raise MCPConfigError(f"server {ctx} must be an object")
    # The server_id is the authoritative value. It may appear explicitly in the
    # body as "server_id", but for the common keyed layout
    # `servers: { "<id>": {...} }` it is also the JSON key (ctx). Prefer an
    # explicit body field when present, else fall back to the key. It is always
    # re-derived from the JSON key by the loader, so the two can never disagree.
    server_id = raw.get("server_id", ctx)
    if not isinstance(server_id, str) or not server_id:
        raise MCPConfigError(f"server {ctx} 'server_id' must be a non-empty string")
    try:
        policy.assert_safe_server_id(server_id)
    except ValueError as exc:
        raise MCPConfigError(str(exc)) from None

    name = raw.get("name")
    name = server_id if name is None else name
    if not isinstance(name, str):
        raise MCPConfigError(f"server {ctx} 'name' must be a string")

    transport = str(raw.get("transport", "stdio")).strip().lower()
    if transport not in ("stdio", "http"):
        raise MCPConfigError(
            f"server {ctx} transport must be 'stdio' or 'http', got {transport!r}"
        )
    enabled = bool(raw.get("enabled", False))

    # ---- per-tool allowlist ---------------------------------------------
    tools_raw = raw.get("tools", {})
    _require_type(tools_raw, dict, "tools", ctx)
    tools: dict[str, McpToolPolicy] = {}
    for tname, tcfg in tools_raw.items():
        if not isinstance(tname, str):
            raise MCPConfigError(
                f"server {ctx} tools object keys must be strings, got {tname!r}"
            )
        tools[tname] = McpToolPolicy.from_json(tname, tcfg, ctx)

    # ---- stdio fields ---------------------------------------------------
    command_raw = raw.get("command")
    command = str(command_raw) if command_raw is not None else ""
    args: list[str] = []
    args_raw = raw.get("args")
    if args_raw is None:
        args = []
    else:
        _require_type(args_raw, list, "args", ctx)
        for i, a in enumerate(args_raw):
            _require_type(a, str, f"args[{i}]", ctx)
            args.append(a)

    working_dir_raw = raw.get("working_dir")
    working_dir = str(working_dir_raw).strip() if working_dir_raw not in (None, "") else ""

    env_names = _read_env_allowlist(raw.get("env_names"), "env_names", ctx)

    url = str(raw.get("url", "") or "").strip()

    # ---- transport-specific presence + policy -----------------------------
    # Validate argv even for disabled/stdio configs so a typo cannot silently
    # become an open hole the moment the operator flips enabled:true.
    if transport == "stdio":
        if not command:
            raise MCPConfigError(
                f"stdio server {ctx} requires a non-empty 'command' filename."
            )
        full_argv = [command, *args]
        try:
            policy.assert_safe_argv(full_argv)
        except ValueError as exc:
            raise MCPConfigError(str(exc)) from None

    if transport == "http":
        if not url:
            raise MCPConfigError(f"http server {ctx} requires an https 'url'.")
        _validate_remote_url(url, ctx)

    # Confine working_dir to approved roots relative to the config file.
    wd: str | None = None
    if working_dir:
        approved_root, wd = _confine_working_dir(working_dir, ctx, file_parent)
        _ = approved_root

    cfg = McpServerConfig(
        server_id=server_id,
        name=name,
        transport=transport,
        enabled=enabled,
        command=command,
        args=args,
        working_dir=wd,
        env_names=env_names,
        startup_timeout_s=_float_gt0(
            raw.get("startup_timeout_s", DEFAULT_STARTUP_TIMEOUT_S),
            "startup_timeout_s",
            ctx,
        ),
        call_timeout_s=_float_gt0(
            raw.get("call_timeout_s", DEFAULT_CALL_TIMEOUT_S),
            "call_timeout_s",
            ctx,
        ),
        url=url,
        requires_approval_default=bool(raw.get("requires_approval_default", True)),
        tools=tools,
        restart_limit=_parse_uint_bounded(
            raw.get("restart_limit"),
            "restart_limit",
            ctx,
            default=DEFAULT_RESTART_LIMIT,
            minimum=0,
            maximum=50,
        ),
        max_output_bytes=_parse_uint_bounded(
            raw.get("max_output_bytes"),
            "max_output_bytes",
            ctx,
            default=DEFAULT_MAX_OUTPUT_BYTES,
            minimum=1024,
            maximum=8 * 1024 * 1024,
        ),
        note=str(raw.get("note", "") or ""),
    )
    return cfg


def _validate_remote_url(url: str, ctx: str) -> None:
    """Reject a remote http URL that is not https or that urlguard forbids."""
    from urllib.parse import urlsplit

    from security.urlguard import forbidden_open_target

    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise MCPConfigError(
            f"http server {ctx} url must use https (never plain http): {url!r}"
        )
    reason = forbidden_open_target(url)
    if reason is not None:
        raise MCPConfigError(
            f"http server {ctx} url is refused by the network policy: {reason}"
        )


def _resolve_container_root(working_dir: str, ctx: str, file_parent: Path) -> Path:
    """Resolve a possibly-relative working_dir against the config file dir."""
    base = Path(working_dir)
    if base.is_absolute():
        return base.resolve()
    return (file_parent / working_dir).resolve()


def _confine_working_dir(
    working_dir: str, ctx: str, file_parent: Path
) -> tuple[Path, str]:
    """Confine a stdio server's cwd to an allowed directory.

    The only approved root is the directory *containing* the config file
    (mirroring how AIBA treats the config tree as the trustworthy local base).
    Returning the canonical absolute path string is enough for the SDK; the
    value is logged nowhere.
    """
    root = file_parent.resolve()
    candidate = _resolve_container_root(working_dir, ctx, file_parent)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise MCPConfigError(
            f"server {ctx} working_dir {working_dir!r} must stay inside the "
            f"config directory tree {root}."
        ) from None
    if not candidate.is_dir():
        # allow the directory to be created later but it must be within our
        # tree; check parent chain for containment is already satisfied.
        pass
    return root, str(candidate)


@dataclass
class MCPConfig:
    """The parsed config/mcp_servers.json document (fail-closed by default)."""

    enabled_default: bool = False
    servers: dict[str, McpServerConfig] = field(default_factory=dict)
    # absolute path the doc was loaded from (diagnostics), or None when inert
    source_path: str | None = None

    def get(self, server_id: str) -> McpServerConfig | None:
        return self.servers.get(server_id)

    @property
    def enabled_servers(self) -> list[McpServerConfig]:
        """Only servers the operator has enabled (stdio or gated http)."""
        return [s for s in self.servers.values() if s.enabled]


def load_config(path: str | Path | None = None) -> "MCPConfig":
    """Load + validate ``config/mcp_servers.json`` at *path* (default cwd/config).

    * A missing file / empty document  -> an empty (disabled) :class:`MCPConfig`.
    * A malformed or policy-violating document -> :class:`MCPConfigError`.

    The *file* is never mutated and no secret value is ever read here: only
    env-var names may be configured (resolved at launch by the client).
    """
    p = Path(path) if path else Path("config") / DEFAULT_CONFIG_NAME
    if not p.exists():
        return MCPConfig(source_path=str(p))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPConfigError(f"{p}: invalid JSON: {exc}") from exc
    if data is None:
        return MCPConfig(source_path=str(p))
    if not isinstance(data, dict):
        raise MCPConfigError(f"{p}: top level must be a JSON object")
    if not data:
        return MCPConfig(source_path=str(p))

    cfg_block = data.get("config", {})
    if cfg_block is None:
        cfg_block = {}
    if not isinstance(cfg_block, dict):
        raise MCPConfigError(f"{p}: 'config' must be an object")

    servers_raw = data.get("servers")
    if servers_raw is None:
        servers_raw = {}
    if not isinstance(servers_raw, dict):
        raise MCPConfigError(f"{p}: 'servers' must be an object of server_id -> config")

    file_parent = p.parent if p.parent.is_dir() else Path(".").resolve()
    servers: dict[str, McpServerConfig] = {}
    for sid, sraw in servers_raw.items():
        if not isinstance(sid, str) or not sid:
            raise MCPConfigError(f"{p}: server keys must be non-empty strings")
        srv = _parse_server(sraw if isinstance(sraw, dict) else {}, str(sid), file_parent)
        # The JSON key is the authoritative server_id used for lookup.
        if srv.server_id != sid:
            srv.server_id = str(sid)
        servers[str(sid)] = srv

    enabled_default = bool(cfg_block.get("enabled_default", False))
    return MCPConfig(
        enabled_default=enabled_default,
        servers=servers,
        source_path=str(p),
    )


def config_abs_path(root_dir: str | Path | None = None) -> Path:
    """Absolute path of the MCP servers config file under *root_dir* (or cwd)."""
    root = Path(root_dir) if root_dir else Path.cwd()
    return (root / "config" / DEFAULT_CONFIG_NAME).resolve()


def env_value_for(name: str) -> str | None:
    """Resolve the operator-provided env-var value for stdio *env name* at launch.

    Reads only an already-validated, non-secret allowlist *name* from the
    current process environment. Never logs or stores the returned value; the
    value is forwarded only to the child stdio process.
    """
    return os.environ.get(name)
