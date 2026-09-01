"""AIBA capability diagnostics.

Merges three sources of truth into one actionable per-tool report:

1. **config/capability_manifest.json** — the authoritative manifest: every
   tool's description, risk class, default enabled state, approval
   requirement, feature flag, and optional dependency.
2. **config/permissions.json** — the run-time security policy that gates
   enablement and approval.
3. **Live AgentLoop registry** — which tools are actually registered.

The goal (per the v1.6 capability-parity plan) is to *never silently
advertise an unavailable tool to the model*. A tool is ``ready`` only if it
is registered, listed in the policy, enabled, and (if gated) its feature
flag is on and its optional dependency is present. Otherwise the report
states the single most actionable reason it is unavailable.
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Feature-flag name -> env var name to read the current on/off state.
# These mirror the env vars consumed by config/settings.py.
FEATURE_FLAG_ENV = {
    "AIBA_WEB_ENABLED": "AIBA_WEB_ENABLED",
    "AIBA_BROWSER_ENABLED": "AIBA_BROWSER_ENABLED",
    "AIBA_DESKTOP_ENABLED": "AIBA_DESKTOP_ENABLED",
    "AIBA_VISION_ENABLED": "AIBA_VISION_ENABLED",
}

DEFAULT_MANIFEST_PATH = "config/capability_manifest.json"


FlagOverrides = Mapping[str, bool]


def flag_is_on(name: str, overrides: FlagOverrides | None = None) -> bool:
    """Return True if a feature flag is enabled.

    Resolution order:
    1. If an explicit runtime override supplies this flag, use its boolean
       value directly (the caller — e.g. AgentLoop — is authoritative).
    2. Otherwise fall back to the ambient process environment variable.
    3. Unknown/empty flags (including "none") are always on.

    ``overrides`` carries *booleans*, never strings — the loop passes its
    actual ``settings.*_enabled`` values so runtime reporting and execution
    cannot drift apart.
    """
    if not name or name == "none":
        return True
    if overrides is not None and name in overrides:
        return bool(overrides[name])
    env_name = FEATURE_FLAG_ENV.get(name, name)
    value = os.getenv(env_name, "").strip().lower()
    return value in {"1", "true", "yes", "on", "y"}


@dataclass
class CapabilityEntry:
    tool: str
    description: str
    risk_class: str
    registered: bool
    listed: bool                 # has an entry in permissions.json
    enabled: bool                # permissions.json says enabled
    requires_approval: bool
    feature_flag: str            # manifest feature_flag ("" if none)
    flag_on: bool
    dependency: str              # optional dependency label ("" if none)
    dep_satisfied: bool          # optional dependency present
    ready: bool
    reason: str = ""             # the single most actionable blocker
    internal_only: bool = False  # registered for internal use, never model-visible


@dataclass
class CapabilityReport:
    tools: list[CapabilityEntry] = field(default_factory=list)

    def by_name(self) -> dict[str, CapabilityEntry]:
        return {e.tool: e for e in self.tools}

    def ready(self) -> list[CapabilityEntry]:
        return [e for e in self.tools if e.ready]

    def unavailable(self) -> list[CapabilityEntry]:
        return [e for e in self.tools if not e.ready]


def _dep_satisfied(dependency: str) -> bool:
    """Return True if an optional dependency is present.

    ``dependency`` may be ``""`` (always satisfied) or a label such as
    ``"browser automation engine (playwright/nebuia)"``. We resolve a small
    allowlist of known binaries/commands; anything else we conservatively
    treat as satisfied (the dependency note is informational, not a hard gate)
    unless a magic marker ``needs:<executable>`` is present.
    """
    if not dependency:
        return True
    if dependency.startswith("needs:"):
        exe = dependency.split(":", 1)[1].strip()
        return shutil.which(exe) is not None
    return True


def load_manifest(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else Path(DEFAULT_MANIFEST_PATH)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("tools"), dict):
        raise ValueError("Invalid capability manifest schema")
    return data


def build_report(
    manifest: dict[str, Any] | Path | str | None,
    permissions: dict[str, Any],
    registered: set[str] | list[str],
    flag_overrides: FlagOverrides | None = None,
    dependency_probe: Callable[[str], bool] = _dep_satisfied,
) -> CapabilityReport:
    """Build a per-tool capability report for every tool in the manifest.

    Registered/listed tools not present in the manifest are reported as
    ``ready=False`` with reason "missing from capability manifest" — a future
    tool cannot be silently enabled without a policy decision.

    ``flag_overrides`` is an optional map of feature-flag name -> bool (the
    runtime state as resolved by AgentLoop). When a flag is present here it is
    authoritative; otherwise the ambient environment is consulted.
    """
    if not isinstance(manifest, dict):
        manifest = load_manifest(manifest)
    tools = manifest.get("tools", {})
    reg = set(registered)

    entries: list[CapabilityEntry] = []
    for name, meta in tools.items():
        perm = permissions.get("tools", {}).get(name)
        listed = perm is not None
        enabled = bool(perm.get("enabled", False)) if listed else False
        req_approval = bool(perm.get("requires_approval", True)) if listed else True
        flag = meta.get("feature_flag", "") or ""
        flag_on = flag_is_on(flag, flag_overrides) if (flag and flag != "none") else True
        dep = meta.get("optional_dependency", "") or ""
        dep_ok = dependency_probe(dep)
        internal_only = bool(meta.get("internal_only", False))

        reason = ""
        if name not in reg:
            reason = f"{name} is not registered in the AgentLoop tool registry."
        elif not listed:
            reason = f"{name} is registered but unavailable because it is missing from config/permissions.json."
        elif not enabled:
            reason = f"{name} is listed in permissions.json but disabled (enabled=false)."
        elif not flag_on:
            reason = f"{name} requires feature flag {flag} (set {FEATURE_FLAG_ENV.get(flag, flag)}=true)."
        elif not dep_ok:
            reason = f"{name} requires optional dependency: {dep}."
        else:
            reason = "Ready."

        ready = (name in reg and listed and enabled and flag_on and dep_ok)
        # Internal-only tools share the same readiness semantics: they must be
        # runnable even though they are intentionally absent from model-visible
        # schemas. The model-visible invariant (below) simply skips them.

        entries.append(
            CapabilityEntry(
                tool=name,
                description=meta.get("description", ""),
                risk_class=meta.get("risk_class", ""),
                registered=name in reg,
                listed=listed,
                enabled=enabled,
                requires_approval=req_approval,
                feature_flag=flag,
                flag_on=flag_on,
                dependency=dep,
                dep_satisfied=dep_ok,
                ready=ready,
                reason=reason,
                internal_only=internal_only,
            )
        )

    # Any registered tool absent from the manifest is a policy violation.
    for name in sorted(reg - set(tools.keys())):
        entries.append(
            CapabilityEntry(
                tool=name,
                description="(no manifest entry)",
                risk_class="(unclassified)",
                registered=True,
                listed=permissions.get("tools", {}).get(name) is not None,
                enabled=bool((permissions.get("tools", {}).get(name) or {}).get("enabled", False)),
                requires_approval=bool((permissions.get("tools", {}).get(name) or {}).get("requires_approval", True)),
                feature_flag="",
                flag_on=True,
                dependency="",
                dep_satisfied=True,
                ready=False,
                reason=(
                    f"{name} IS REGISTERED but has NO capability-manifest entry. "
                    f"Every tool needs a policy decision in config/capability_manifest.json."
                ),
            )
        )

    entries.sort(key=lambda e: (not e.ready, e.tool))
    return CapabilityReport(entries)
