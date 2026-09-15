#!/usr/bin/env python3
"""Safely enable or disable AIBA's browser permission family.

Browser automation remains defense-in-depth gated:

1. runtime feature flag: AIBA_BROWSER_ENABLED=true
2. explicit permissions.json entries
3. per-action approval for site-changing operations

This helper manages only gate #2 and never weakens approval requirements.
It intentionally does not touch desktop-control permissions.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "permissions.json"

BROWSER_TOOLS = {
    "browser_fetch",
    "browser_open",
    "browser_state",
    "browser_page_text",
    "browser_screenshot",
    "browser_wait",
    "browser_scroll",
    "browser_status",
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_submit",
    "browser_download",
    "browser_upload",
}

# Mutating or otherwise sensitive browser actions must retain approval.
APPROVAL_REQUIRED = {
    "browser_fetch",  # legacy rendered-fetch adapter keeps its conservative posture
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_submit",
    "browser_download",
    "browser_upload",
}


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"permissions file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid permissions JSON: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("tools"), dict):
        raise SystemExit("permissions file must contain a tools object")
    return value


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def configure(path: Path, enabled: bool) -> tuple[list[str], list[str]]:
    policy = _load(path)
    tools = policy["tools"]
    missing = sorted(BROWSER_TOOLS - set(tools))
    if missing:
        raise SystemExit("browser policy is incomplete; missing: " + ", ".join(missing))

    changed: list[str] = []
    for name in sorted(BROWSER_TOOLS):
        entry = tools[name]
        if not isinstance(entry, dict):
            raise SystemExit(f"invalid permissions entry for {name}")
        desired_approval = name in APPROVAL_REQUIRED
        if entry.get("enabled") is not enabled:
            entry["enabled"] = enabled
            changed.append(name)
        # Never let this convenience helper reduce mutation approval policy.
        if desired_approval and entry.get("requires_approval") is not True:
            entry["requires_approval"] = True
            if name not in changed:
                changed.append(name)

    _atomic_write(path, policy)
    gated = sorted(name for name in BROWSER_TOOLS if tools[name].get("requires_approval"))
    return changed, gated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true", help="enable browser tools in permissions.json")
    group.add_argument("--disable", action="store_true", help="disable browser tools in permissions.json")
    parser.add_argument("--permissions", type=Path, default=DEFAULT_POLICY,
                        help="permissions.json path (defaults to repository config)")
    args = parser.parse_args(argv)

    enabled = bool(args.enable)
    changed, approval_gated = configure(args.permissions.resolve(), enabled)
    state = "enabled" if enabled else "disabled"
    print(f"Browser permission family {state}: {args.permissions}")
    print(f"Changed {len(changed)} tool entries.")
    if enabled:
        print("Approval remains required for: " + ", ".join(approval_gated))
        print("Also set AIBA_BROWSER_ENABLED=true and restart AIBA to activate the runtime feature gate.")
    else:
        print("Browser tools are denied by permissions even if the runtime feature flag remains on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
