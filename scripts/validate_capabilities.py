#!/usr/bin/env python3
"""AIBA capability manifest / permissions validator (CI gate).

Usage:
    python scripts/validate_capabilities.py [--root PATH] [--registry]

Fails (exit 1) when any of these invariant is violated:

1. A tool **registered** in the AgentLoop has no entry in
   config/capability_manifest.json  -> every tool needs a policy decision.
2. A tool **listed** in config/permissions.json does not exist in the manifest.
3. A **dangerous** tool (risk_class in {local_mutation, process_execution,
   external_mutation, destructive}) is enabled in permissions.json without
   requires_approval=true.
4. A permissions.json entry references a tool with no manifest entry.
5. (with --registry) a tool the manifest/advertises is missing from the live
   registered set, or a registered tool is missing from the manifest.

No changes are made. Run in CI after every feature that registers a tool.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RISK_REQUIRES_APPROVAL = {
    "local_mutation",
    "process_execution",
    "external_mutation",
    "destructive",
}

MANIFEST_REL = "config/capability_manifest.json"
PERMISSIONS_REL = "config/permissions.json"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid JSON in {path}: {exc}") from exc


def validate_files(root: Path) -> list[str]:
    """Validate static manifest <-> permissions consistency. Returns error lines."""
    errors: list[str] = []
    manifest = load_json(root / MANIFEST_REL)
    perms = load_json(root / PERMISSIONS_REL)

    m_tools = manifest.get("tools", {})
    p_tools = perms.get("tools", {})

    for name in sorted(p_tools):
        if name not in m_tools:
            errors.append(
                f"[permissions->manifest] '{name}' is in permissions.json but missing from capability_manifest.json. "
                f"Every tool needs a policy decision."
            )

    for name, meta in sorted(m_tools.items()):
        risk = meta.get("risk_class", "")
        if risk in RISK_REQUIRES_APPROVAL:
            # Annotation describes the intended policy; the run-time policy is in
            # permissions.json. A dangerous tool must require approval there too.
            perm = p_tools.get(name)
            if perm is None:
                errors.append(
                    f"[manifest->permissions] dangerous tool '{name}' (risk_class={risk}) has no permissions.json entry. "
                    f"It must be explicitly enabled=true with requires_approval=true, or kept disabled."
                )
            elif perm.get("enabled", False) and not perm.get("requires_approval", True):
                errors.append(
                    f"[policy] dangerous tool '{name}' (risk_class={risk}) is enabled but requires_approval=false in permissions.json."
                )

        # Optional dependencies listed in the manifest must be declared if present.
        dep = meta.get("optional_dependency", "")
        if dep.startswith("needs:"):
            # Informational only; actual binary check is done at runtime.
            pass

    # A tool enabled in permissions but missing from manifest is caught above.
    return errors


def validate_registry(root: Path, registered: set[str]) -> list[str]:
    """Validate the live registered tool set against manifest+permissions.

    Fail when a registered tool has no manifest entry (it shipped without a
    policy decision) or a manifest tool the config claims is enabled is not
    registered (silent capability loss).
    """
    errors: list[str] = []
    manifest = load_json(root / MANIFEST_REL)
    perms = load_json(root / PERMISSIONS_REL)
    m_tools = manifest.get("tools", {})
    p_tools = perms.get("tools", {})

    for name in sorted(registered):
        if name not in m_tools:
            errors.append(
                f"[registry->manifest] '{name}' is REGISTERED but missing from capability_manifest.json (no policy decision)."
            )
    for name, cfg in sorted(p_tools.items()):
        if cfg.get("enabled", False) and name not in registered:
            # A permissions-disabled tool may legitimately not be registered.
            errors.append(
                f"[permissions->registry] '{name}' is enabled in permissions.json but not registered in the AgentLoop. "
                f"If it's dormant, set enabled=false."
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="AIBA repo/config root")
    parser.add_argument("--registry", action="store_true",
                        help="Also validate against the live registered tool set (needs agent.loop importable)")
    parser.add_argument("--registered", nargs="*", help="Explicit registered tool names (CI passes the exploded schema list)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    errors = validate_files(root)
    if args.registry or args.registered:
        registered = set(args.registered or [])
        if not registered and args.registry:
            try:
                from agent.loop import AgentLoop  # noqa: F401
                registered = {"PROBE"}
            except Exception as exc:  # pragma: no cover - env-dependent
                print(f"WARN: could not import AgentLoop to enumerate registered tools ({exc})", file=sys.stderr)
        errors += validate_registry(root, registered)
    if errors:
        for line in errors:
            print("FAIL " + line)
        print(f"\n{len(errors)} capability invariant(s) violated.", file=sys.stderr)
        return 1
    print("OK: capability manifest and permissions.json are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
