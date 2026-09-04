"""AIBA capability-state snapshot for the CLI and dashboard (Phase 11).

One canonical collector that the ``aiba tools|nodes|mcp|sessions|subagents``
CLI subcommands and the ``/v1/capabilities`` dashboard endpoint both call, so
they can never drift apart in what they report.

It composes already-existing, authoritative sources:

* ``diagnostics/capabilities.build_report`` — the per-tool manifest<->policy
  report (registered/listed/enabled/feature-flag/optional-dep/ready + reason),
  used verbatim so reporting matches execution gating exactly.
* ``computer.node.ComputerNodeGate.status()`` — paired-node state.
* ``agent.SubagentManager.status()`` — bounded internal-worker counts.
* ``agent.SessionStore.list_by_user()``/``count()`` — session awareness.
* the audit JSONL tail — a small bounded window of recent tool activity.

No command here mutates state; ``aiba tools enable/disable`` is handled by the
pure permission writer in this module (``set_tool_permission``). Everything is
read-only with respect to the model/agent runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from diagnostics.capabilities import (
    FEATURE_FLAG_ENV,
    CapabilityReport,
    build_report,
    load_manifest,
)

# Default user key the AgentLoop assigns when no per-user scope is selected.
DEFAULT_USER = "default"

_ACTIVITY_LIMIT = 25
_ACTIVITY_BYTES = 256 * 1024  # bounded tail read (audit file can grow large)


def _serialize(entry: Any) -> dict[str, Any]:
    """Turn a CapabilityEntry into a plain JSON-ready dict."""
    return {
        "tool": entry.tool,
        "description": entry.description,
        "risk_class": entry.risk_class,
        "registered": entry.registered,
        "listed": entry.listed,
        "enabled": entry.enabled,
        "requires_approval": entry.requires_approval,
        "feature_flag": entry.feature_flag,
        "flag_on": entry.flag_on,
        "dependency": entry.dependency,
        "dep_satisfied": entry.dep_satisfied,
        "ready": entry.ready,
        "internal_only": entry.internal_only,
        "reason": entry.reason,
    }


def tools_report(loop) -> CapabilityReport:
    """Per-tool capability report resolved against the *live* AgentLoop.

    Uses the loop's own manifest (already loaded), its runtime feature-flag
    map (so reporting and execution agree) and its registered tool set.
    """
    registered = set(getattr(loop.registry, "_tools", {}).keys())
    permissions = getattr(loop.policy, "config", {})
    flag_overrides = dict(getattr(loop, "runtime_flags", {}) or {})
    manifest = getattr(loop, "manifest", None) or {}
    return build_report(
        manifest,
        permissions,
        registered,
        flag_overrides=flag_overrides or None,
    )


def flag_state(loop) -> dict[str, dict[str, Any]]:
    """List every manifest feature flag with its current on/off + env var."""
    manifest = getattr(loop, "manifest", None) or {}
    flags = manifest.get("feature_flags", {})
    runtime = dict(getattr(loop, "runtime_flags", {}) or {})
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(flags):
        if name == "none":
            continue
        env_name = FEATURE_FLAG_ENV.get(name, name)
        env = env_name if isinstance(env_name, str) and env_name else str(name)
        on = runtime.get(name)
        if on is None:
            on = os.getenv(env, "").strip().lower() in {"1", "true", "yes", "on", "y"}
        out[name] = {
            "name": name,
            "running": bool(on),
            "env_var": env,
            "description": flags[name],
        }
    return out


def _audit_tail(path: Path, limit: int = _ACTIVITY_LIMIT) -> list[dict[str, Any]]:
    """Return the last ``limit`` tool events from an audit JSONL file.

    Reads from the tail (bounded) and filters to tool_* lifecycle records so a
    huge audit file cannot be loaded whole. Returns a list of
    ``{ts, event, tool, ok, error}`` summarised rows (never raw arguments).
    """
    result: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError:
        return result
    # Read at most the trailing _ACTIVITY_BYTES then split into lines.
    start = max(0, size - _ACTIVITY_BYTES)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if start:
                fh.seek(start)
                fh.readline()  # drop the possibly-partial first line
            lines = fh.readlines()
    except OSError:
        return result
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        event = rec.get("event", "")
        if not event.startswith("tool_"):
            continue
        result.append(
            {
                "ts": rec.get("ts", rec.get("time", rec.get("timestamp", ""))),
                "event": event,
                "tool": rec.get("tool", ""),
                "ok": rec.get("ok"),
                "error": (rec.get("error") or "")[:200],
            }
        )
    return result[-limit:]


def recent_activity(loop, limit: int = _ACTIVITY_LIMIT) -> list[dict[str, Any]]:
    path = Path(getattr(loop.settings, "logs_dir", Path("."))) / "audit.jsonl"
    return _audit_tail(path, limit=limit)


def session_rows(loop, user: str = DEFAULT_USER, limit: int = 30) -> list[dict[str, Any]]:
    try:
        return list(loop.sessions.list_by_user(user, limit=int(limit)))
    except Exception:
        return []


def sessions_state(loop, user: str = DEFAULT_USER, limit: int = 30) -> dict[str, Any]:
    store = loop.sessions
    rows = session_rows(loop, user=user, limit=limit)
    try:
        total = int(getattr(store, "count")())
    except Exception:
        total = len(rows)
    active = [s for s in rows if (s.get("status") or "").lower() in {"open", "active"}]
    return {
        "total": total,
        "recent": rows,
        "recent_active": len(active),
        "user": user,
    }


def nodes_state(loop) -> dict[str, Any]:
    gate = loop.computer_node
    try:
        status = gate.status()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc), "paired": False, "enabled": False}
    # status() is safe (no digest/token); enforce non-secret shape defensively.
    for key in ("token_digest", "digest"):
        status.pop(key, None)
    status["control"] = {
        "pair": "aiba --computer-pair",
        "enable": "aiba nodes enable",
        "disable": "aiba nodes disable",
        "stop": "aiba --computer-stop",
        "reset_budget": "aiba --computer-reset-budget",
    }
    return status


def subagents_state(loop) -> dict[str, Any]:
    try:
        return dict(loop.subagents.status())
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc), "enabled": False}


def mcp_state() -> dict[str, Any]:
    """MCP client state (Phase 7 landed).

    AIBA exposes a single gated ``mcp_call`` gateway to operator-configured
    external MCP servers. It is OPTIONAL and DISABLED by default on three
    independent axes (the ``AIBA_MCP_ENABLED`` feature flag, an ``enabled:true``
    ``mcp_call`` entry in permissions.json, and at least one enabled allowlisted
    server in config/mcp_servers.json). This pure collector has no live server
    manager handle, so it truthfully reports the opt-in posture + configuration
    file location rather than fabricating a running-manager state.
    """
    return {
        "available": False,  # fail-closed default: not enabled until operator opts in
        "disabled_by_default": True,
        "servers": [],
        "note": "Optional MCP client (Phase 7) is landed but off by default. Enable AIBA_MCP_ENABLED, list "
                "mcp_call (enabled:true) in config/permissions.json, and add allowlisted servers in "
                "config/mcp_servers.json (see mcp_servers.example.json).",
        "enable": "set AIBA_MCP_ENABLED=true + enable 'mcp_call' in permissions.json + configure config/mcp_servers.json",
    }


def snapshot(loop, user: str = DEFAULT_USER, activity_limit: int = _ACTIVITY_LIMIT,
             session_limit: int = 30) -> dict[str, Any]:
    """One complete capability overview for the dashboard/API."""
    report = tools_report(loop)
    return {
        "tools": {
            "ready": [_serialize(e) for e in report.ready()],
            "unavailable": [_serialize(e) for e in report.unavailable()],
            "registered_count": len({e.tool for e in report.tools}),
            "ready_count": len(report.ready()),
            "enabled_count": len([e for e in report.tools if e.enabled]),
        },
        "flags": flag_state(loop),
        "nodes": nodes_state(loop),
        "sessions": sessions_state(loop, user=user, limit=session_limit),
        "subagents": subagents_state(loop),
        "mcp": mcp_state(),
        "activity": recent_activity(loop, limit=activity_limit),
    }


# ---------------------------------------------------------------------------
# Pure permission writer used by `aiba tools enable|disable`.
# ---------------------------------------------------------------------------

def _read_permissions(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("tools"), dict):
        raise ValueError("Invalid permissions.json schema")
    return data


def tool_now_enabled(permissions_path: Path, name: str) -> bool:
    """Return whether ``name`` is currently ``enabled`` on disk.

    Reads the permissions file fresh (not the agent's cached policy), so a
    CLI enable/disable can report the true post-write state.
    """
    data = _read_permissions(permissions_path)
    return bool((data.get("tools", {}) or {}).get(name, {}).get("enabled"))


def _tool_in_manifest(manifest_path: Path, name: str) -> bool:
    manifest = load_manifest(manifest_path)
    return name in (manifest.get("tools", {}) or {})


def set_tool_permission(
    permissions_path: Path,
    manifest_path: Path,
    name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Enable/disable a single tool in permissions.json (the master gate).

    Writes atomically and preserves the file's formatting style (compact
    ``{"key": value}`` entries). Refuses unknown tools and refuses to strip
    ``requires_approval`` from a dangerous tool (approval is never removed by
    this command). Returns the resulting permission entry for the named tool.
    """
    permissions_path = Path(permissions_path)
    manifest_path = Path(manifest_path)
    if not isinstance(enabled, bool):
        raise TypeError(
            f"enabled must be a real boolean (True or False), got {type(enabled).__name__}: {enabled!r}"
        )
    if not _tool_in_manifest(manifest_path, name):
        raise ValueError(
            f"Unknown tool: {name!r}. It has no capability-manifest entry; "
            f"every tool needs a policy decision before it can be enabled."
        )
    data = _read_permissions(permissions_path)
    tools: dict[str, Any] = data["tools"]
    entry = tools.get(name)
    if entry is None:
        # A manifest tool that is not yet listed: default approval per manifest.
        manifest = load_manifest(manifest_path)
        meta = manifest["tools"][name]
        entry = {"enabled": False, "requires_approval": bool(meta.get("requires_approval", True))}
        tools[name] = entry
    entry["enabled"] = enabled
    # Never remove requires_approval here — mutating approval is a separate,
    # deliberate act; this command only flips availability.
    if "requires_approval" not in entry:
        entry["requires_approval"] = True

    # Deterministic, policy-preserving key order: version, defaults, tools.
    ordered = {
        "version": data.get("version", 1),
        "defaults": data.get("defaults", {"requires_approval": True}),
        "tools": tools,
        # Preserve any extra top-level keys the operator may have added.
        **{k: v for k, v in data.items() if k not in {"version", "defaults", "tools"}},
    }
    _atomic_write_pretty(permissions_path, ordered)
    return {"tool": name, **tools[name]}


def _atomic_write_pretty(path: Path, data: dict[str, Any]) -> None:
    """Write JSON in the canonical compact-per-line shape, atomically.

    Mirrors the hand-maintained ``config/permissions.json`` style (version,
    defaults, then one ``"tool": {...},`` entry per line, tools in their
    existing order so a single enable/disable produces a tiny, reviewable
    diff instead of a full re-sort or reformat.
    """
    tools = data.get("tools", {})
    if not isinstance(tools, dict):
        raise ValueError("permissions.tools must be an object")

    segments: list[str] = []
    extras = [(k, v) for k, v in data.items() if k not in {"version", "defaults", "tools"}]
    if "defaults" in data:
        segments.append(f'  "defaults": {json.dumps(data["defaults"], sort_keys=True)},')
    segments.append('  "tools": {')
    if tools:
        # Iterate in insertion order (Python dicts are ordered). New tool
        # entries are appended at the end by dict insertion, so this preserves
        # the curated operational ordering of the hand-maintained file.
        for name in tools:
            segments.append(
                f'    {json.dumps(name)}: {json.dumps(tools[name], sort_keys=True)},'
            )
        # Drop the trailing comma on the final tool line.
        segments[-1] = segments[-1].rstrip(",")
    # Close tools. If there are trailing top-level keys, separate with a comma.
    segments.append("  }" + ("," if extras else ""))
    for i, (k, v) in enumerate(extras):
        comma = "," if i < len(extras) - 1 else ""
        segments.append(f'  {json.dumps(k)}: {json.dumps(v, sort_keys=True)}{comma}')
    version_line = f'  "version": {json.dumps(data.get("version", 1))},'
    body = "{\n" + version_line + "\n" + "\n".join(segments) + "\n}\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
