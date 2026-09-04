"""Phase 11 capability-management CLI handlers.

These functions back the new ``aiba tools|nodes|mcp|sessions|subagents``
subcommands. Each handler takes the already-constructed ``agent`` (an
``AgentLoop``) plus the parsed sub-args and returns a JSON-serializable dict;
the launcher in ``main.py`` prints it. Query handlers are read-only.
``tools enable|disable`` is the one mutation path, delegating to
``diagnostics.capability_state.set_tool_permission`` (a pure permissions.json
writer).

Read paths reuse ``diagnostics.capability_state`` so the CLI and the
dashboard/API report identical facts.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from diagnostics import capability_state as cs
from diagnostics.capabilities import CapabilityReport
from diagnostics.capability_state import DEFAULT_USER

SECTIONS = ("tools", "nodes", "mcp", "sessions", "subagents")


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

def tools_list(agent) -> dict[str, Any]:
    report: CapabilityReport = cs.tools_report(agent)
    rows = [cs._serialize(e) for e in report.tools]
    return {"count": len(rows), "tools": rows}


def tools_enabled(agent) -> dict[str, Any]:
    report: CapabilityReport = cs.tools_report(agent)
    return {"count": len(report.ready()), "tools": [cs._serialize(e) for e in report.ready()]}


def tools_doctor(agent) -> dict[str, Any]:
    report: CapabilityReport = cs.tools_report(agent)
    ready = report.ready()
    unavailable = report.unavailable()
    return {
        "registered": len({e.tool for e in report.tools}),
        "ready": len(ready),
        "unavailable": len(unavailable),
        "blockers": [
            {"tool": e.tool, "reason": e.reason} for e in unavailable
        ],
    }


def tools_enable(agent, name: str) -> dict[str, Any]:
    perm = cs.set_tool_permission(
        agent.settings.permissions_path,
        agent.settings.root_dir / "config" / "capability_manifest.json",
        name,
        True,
    )
    # Warn if a feature flag or optional dep still blocks it at runtime.
    meta = (agent.manifest or {}).get("tools", {}).get(name, {}) or {}
    warnings: list[str] = []
    flag = meta.get("feature_flag", "") or ""
    if flag and flag != "none" and not agent.runtime_flags.get(flag):
        env = cs.FEATURE_FLAG_ENV.get(flag, flag)
        warnings.append(
            f"permissions now allow {name}, but runtime feature flag {flag} "
            f"is off (set {env}=true in your environment to expose it to the model)."
        )
    dep = meta.get("optional_dependency", "") or ""
    if dep and dep != "none":
        warnings.append(f"{name} also needs optional dependency {dep} installed.")
    perm["warnings"] = warnings
    # available_to_model must reflect the true post-write state: the tool is
    # enabled on disk AND (no feature flag / flag on). Read fresh from disk
    # because agent.policy.config was captured when the loop was constructed.
    enabled_on_disk = cs.tool_now_enabled(agent.settings.permissions_path, name)
    perm["available_to_model"] = bool(
        enabled_on_disk and (not flag or flag == "none" or agent.runtime_flags.get(flag))
    )
    return perm


def tools_disable(agent, name: str) -> dict[str, Any]:
    result = cs.set_tool_permission(
        agent.settings.permissions_path,
        agent.settings.root_dir / "config" / "capability_manifest.json",
        name,
        False,
    )
    result["available_to_model"] = False
    result["warnings"] = []
    return result


# ---------------------------------------------------------------------------
# nodes
# ---------------------------------------------------------------------------

def nodes_status(agent) -> dict[str, Any]:
    return cs.nodes_state(agent)


def nodes_paired(agent) -> dict[str, Any]:
    st = cs.nodes_state(agent)
    return {"paired": st.get("paired", False), "node": st}


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------

def mcp_status(agent) -> dict[str, Any]:
    return cs.mcp_state()


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def sessions_list(agent, user: str = DEFAULT_USER, limit: int = 30) -> dict[str, Any]:
    return cs.sessions_state(agent, user=user, limit=limit)


# ---------------------------------------------------------------------------
# subagents
# ---------------------------------------------------------------------------

def subagents_status(agent) -> dict[str, Any]:
    return cs.subagents_state(agent)


# ---------------------------------------------------------------------------
# Human-friendly printers (used when stdout is a TTY / default output).
# Subcommands that need JSON (for scripting) pass --json.
# ---------------------------------------------------------------------------

def _print_human(agent, cmd: str, args: Any, result: dict[str, Any]) -> None:
    section = args.section
    if section == "tools":
        if cmd in ("list", "enabled"):
            rows = result.get("tools", []) if isinstance(result.get("tools"), list) else []
            header = "model-visible (ready) tools" if cmd == "enabled" else f"tools ({result.get('count', len(rows))} in manifest)"
            print(f"TOOLS {cmd}: {header}")
            for r in sorted(rows, key=lambda x: (not x.get("ready", False), x.get("tool", ""))):
                t = r.get("tool", "")
                state = "ready" if r.get("ready") else ("perm-off" if not r.get("enabled") else "blocked")
                extra = ""
                if not r.get("ready") and r.get("enabled"):
                    if not r.get("flag_on"):
                        extra = f" (flag {r.get('feature_flag')} off)"
                    elif not r.get("dep_satisfied"):
                        extra = f" (missing dep {r.get('dependency')})"
                reason = f" — {r.get('reason')}" if (not r.get("ready") and (cmd == "list")) else ""
                print(f"  [{state:<8}] {t:<22} {r.get('risk_class','')}{extra}{reason}")
        elif cmd == "doctor":
            print(
                f"TOOLS DOCTOR: registered={result['registered']} ready={result['ready']} "
                f"unavailable={result['unavailable']}"
            )
            for b in result.get("blockers", []):
                print(f"  - {b['tool']}: {b['reason']}")
        elif cmd in ("enable", "disable"):
            print(
                f"tool {args.tool!r} {'enabled' if cmd == 'enable' else 'disabled'} "
                f"in permissions.json (available_to_model={result.get('available_to_model')})"
            )
            for w in result.get("warnings", []):
                print(f"  ! {w}")
    elif section == "nodes":
        print(json.dumps(result, indent=2, sort_keys=True))
    elif section == "mcp":
        print(json.dumps(result, indent=2, sort_keys=True))
    elif section == "sessions":
        rows = result.get("recent", [])
        total = result.get("total")
        print(f"SESSIONS [{result.get('user')}]: total={total} recent={len(rows)} active_in_recent={result.get('recent_active')}")
        for s in rows:
            print(f"  {str(s.get('session_id',''))[:8]} {s.get('status','')} {s.get('started_at') or s.get('created_at') or ''} {str(s.get('title',''))[:40]}")
    elif section == "subagents":
        print(json.dumps(result, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Top-level argparse CLI (invoked by main.py when the first bare word is one
# of our section keywords, so the legacy flat-flag surface is untouched).
# ---------------------------------------------------------------------------

def add_parser(sub) -> None:
    """Register the capability-management subparsers on an argparse subparser
    group (or standalone parser) ``sub``."""
    p_tools = sub.add_parser(
        "tools", help="Inspect and toggle model-visible tools.",
        description="AIBA capability/tool management.",
    )
    tg = p_tools.add_subparsers(dest="action")
    tg.add_parser("list", help="List every manifest tool with readiness state.")
    tg.add_parser("enabled", help="List only model-visible (ready) tools.")
    tg.add_parser("doctor", help="Summary of tool readiness + actionable blockers.")
    pe = tg.add_parser("enable", help="Enable a tool in permissions.json.")
    pe.add_argument("tool")
    pd = tg.add_parser("disable", help="Disable a tool in permissions.json.")
    pd.add_argument("tool")

    p_nodes = sub.add_parser(
        "nodes", help="Show computer-node pairing / desktop-control state.",
    )
    ng = p_nodes.add_subparsers(dest="action")
    ng.add_parser("status", help="Full node status (paired/enabled/budget).")
    ng.add_parser("list", help="Alias of status.")

    p_mcp = sub.add_parser(
        "mcp", help="Show MCP server state (Phase 7: not available).",
    )
    mg = p_mcp.add_subparsers(dest="action")
    mg.add_parser("status", help="Show MCP server/availability state.")

    p_sessions = sub.add_parser(
        "sessions", help="List recent per-user AIBA sessions.",
    )
    p_sessions.add_argument("--user", default=DEFAULT_USER)
    p_sessions.add_argument("--limit", type=int, default=30)

    p_subs = sub.add_parser(
        "subagents", help="Show bounded internal-worker (subagent) status.",
    )
    sg = p_subs.add_subparsers(dest="action")
    sg.add_parser("status", help="Worker counts / enablement / concurrency.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aiba", description="AIBA capability management (v1.6)."
    )
    sub = p.add_subparsers(dest="section", metavar="{tools,nodes,mcp,sessions,subagents}", required=True)
    add_parser(sub)
    return p


def dispatch(argv: list[str], agent=None) -> int:
    """Run a capability subcommand.

    ``agent`` is created lazily (an isolated ``AgentLoop`` with no background
    worker) when the handler needs live registry/node/session state; ``mcp``
    needs none. Prints JSON to stdout unless ``--human``. Returns an exit code.
    """
    p = build_parser()
    human = "--human" in argv
    if human:
        argv = [a for a in argv if a != "--human"]
    args = p.parse_args(argv)
    action = getattr(args, "action", None)

    need_agent = {"nodes", "tools", "sessions", "subagents"}
    if args.section == "mcp":
        result = mcp_status(None)
        _emit(args, result, human)
        return 0
    if args.section not in need_agent:
        p.error(f"unsupported section: {args.section}")

    if agent is None:
        agent = _fresh_loop()

    try:
        if args.section == "tools":
            result = _run_tools(agent, args)
        elif args.section == "nodes":
            if action in (None, "status", "list"):
                result = nodes_status(agent)
            else:
                p.error(f"unknown nodes action: {action}")
        elif args.section == "sessions":
            result = sessions_list(agent, user=args.user, limit=max(1, int(args.limit)))
        elif args.section == "subagents":
            if action in (None, "status"):
                result = subagents_status(agent)
            else:
                p.error(f"unknown subagents action: {action}")
        else:
            p.error(f"unsupported section: {args.section}")
    finally:
        agent.close()

    _emit(args, result, human)
    return 0


def _run_tools(agent, args) -> dict[str, Any]:
    action = args.action
    if action in (None, "list"):
        return tools_list(agent)
    if action == "enabled":
        return tools_enabled(agent)
    if action == "doctor":
        return tools_doctor(agent)
    if action == "enable":
        return tools_enable(agent, args.tool)
    if action == "disable":
        return tools_disable(agent, args.tool)
    raise SystemExit(f"unknown tools action: {action}")


def _fresh_loop():
    from agent.loop import AgentLoop
    return AgentLoop(interactive=False, auto_approve=False, start_worker=False)


def _emit(args, result, human: bool) -> None:
    if human:
        _print_human(None, args.action or "status", args, result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
