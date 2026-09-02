"""Tests for the capability manifest + permissions validator and diagnostics."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_capabilities import validate_files  # type: ignore[import-not-found]
from diagnostics.capabilities import _dep_satisfied, build_report, flag_is_on, load_manifest

REPO = Path(__file__).resolve().parents[1]

MANIFEST = json.loads((REPO / "config" / "capability_manifest.json").read_text(encoding="utf-8"))


def _perms(with_tools: dict | None = None) -> dict:
    p = {"version": 1, "tools": {
        "list_files": {"enabled": True, "requires_approval": False},
        "read_file": {"enabled": True, "requires_approval": False},
        "write_file": {"enabled": True, "requires_approval": True},
        "delete_file": {"enabled": True, "requires_approval": True},
        "patch_file": {"enabled": True, "requires_approval": True},
        "archive": {"enabled": True, "requires_approval": True},
        "extract_archive": {"enabled": True, "requires_approval": True},
        "run_shell": {"enabled": True, "requires_approval": True},
        "run_python": {"enabled": True, "requires_approval": True},
        "web_search": {"enabled": True, "requires_approval": False},
        "web_extract": {"enabled": True, "requires_approval": False},
        "remember": {"enabled": True, "requires_approval": True},
        "search_memory": {"enabled": True, "requires_approval": False},
        "browser_fetch": {"enabled": False, "requires_approval": True},
        "desktop_screenshot": {"enabled": False, "requires_approval": True},
        "desktop_click": {"enabled": False, "requires_approval": True},
        "desktop_type": {"enabled": False, "requires_approval": True},
        "vision_analyze": {"enabled": False, "requires_approval": True},
        "list_skills": {"enabled": True, "requires_approval": False},
        "skill_instructions": {"enabled": True, "requires_approval": False},
        "run_skill": {"enabled": True, "requires_approval": True},
        "clarify": {"enabled": True, "requires_approval": False},
        "enqueue_task": {"enabled": True, "requires_approval": True},
        "schedule_task": {"enabled": True, "requires_approval": True},
    }, "blocked_command_fragments": []}
    if with_tools:
        p["tools"].update(with_tools)
    return p


class ManifestValidatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_mv_")
        self.root = Path(self._tmp)
        (self.root / "config").mkdir(parents=True)
        shutil.copy(REPO / "config" / "permissions.json", self.root / "config" / "permissions.json")
        shutil.copy(REPO / "config" / "capability_manifest.json", self.root / "config" / "capability_manifest.json")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_production_config_is_consistent(self):
        self.assertEqual(validate_files(self.root), [])

    def test_registered_tool_missing_from_manifest_fails(self):
        # Add a tool to permissions.json that has no manifest entry.
        p = json.loads((self.root / "config" / "permissions.json").read_text())
        p["tools"]["rogue_tool"] = {"enabled": True, "requires_approval": True}
        (self.root / "config" / "permissions.json").write_text(json.dumps(p))
        errs = validate_files(self.root)
        self.assertTrue(any("rogue_tool" in e for e in errs))
        # The inverse direction (permissions references a tool the manifest
        # does not describe) is the very same invariant.
        self.assertTrue(any(e.startswith("[permissions->manifest]") for e in errs))

    def test_dangerous_tool_without_approval_fails(self):
        p = json.loads((self.root / "config" / "permissions.json").read_text())
        # run_shell is process_execution (dangerous): flip to no approval.
        p["tools"]["run_shell"] = {"enabled": True, "requires_approval": False}
        (self.root / "config" / "permissions.json").write_text(json.dumps(p))
        errs = validate_files(self.root)
        self.assertTrue(any("run_shell" in e and "requires_approval" in e for e in errs))


class CapabilityDiagnosticsTests(unittest.TestCase):
    def test_manifest_loads(self):
        m = load_manifest(REPO / "config" / "capability_manifest.json")
        self.assertIn("patch_file", m["tools"])
        self.assertEqual(m["tools"]["web_search"]["risk_class"], "read_only_network")

    def test_flag_is_on_none(self):
        self.assertTrue(flag_is_on("none"))
        self.assertTrue(flag_is_on(""))

    def test_flag_is_on_overrides(self):
        import os
        prev = os.environ.pop("AIBA_WEB_ENABLED", None)
        self.addCleanup(lambda: os.environ.__setitem__("AIBA_WEB_ENABLED", prev) if prev is not None else os.environ.pop("AIBA_WEB_ENABLED", None))
        # Overrides carry booleans (never strings).
        self.assertTrue(flag_is_on("AIBA_WEB_ENABLED", {"AIBA_WEB_ENABLED": True}))
        self.assertFalse(flag_is_on("AIBA_WEB_ENABLED", {"AIBA_WEB_ENABLED": False}))
        self.assertTrue(flag_is_on("AIBA_BROWSER_ENABLED", {"AIBA_BROWSER_ENABLED": True}))
        # An override not present falls back to (unset) ambient env -> off.
        self.assertFalse(flag_is_on("AIBA_WEB_ENABLED", {"AIBA_DESKTOP_ENABLED": True}))

    def test_registered_unlisted_tool_reported_unavailable_with_reason(self):
        # skill_instructions is in the manifest but we remove it from
        # permissions.json -> registered + manifest-present but unlisted.
        perms = _perms()
        perms["tools"].pop("skill_instructions")
        report = build_report(MANIFEST, perms, {"list_files", "patch_file", "skill_instructions"},
                              flag_overrides={"AIBA_WEB_ENABLED": False})
        e = report.by_name()["skill_instructions"]
        self.assertFalse(e.ready)
        self.assertIn("missing from config/permissions.json", e.reason)

    def test_registered_tool_absent_from_manifest_is_loud(self):
        # A registered tool the manifest has never seen must be flagged hard.
        perms = _perms()
        report = build_report(MANIFEST, perms, {"mem_tool"})
        e = report.by_name()["mem_tool"]
        self.assertFalse(e.ready)
        self.assertIn("NO capability-manifest entry", e.reason)

    def test_feature_flagged_tool_not_ready_when_off(self):
        perms = _perms()
        report = build_report(MANIFEST, perms, {"web_search", "web_extract"},
                              flag_overrides={"AIBA_WEB_ENABLED": False})
        e = report.by_name()["web_search"]
        self.assertFalse(e.ready)
        self.assertIn("feature flag", e.reason)

    def test_ready_tool_report(self):
        perms = _perms()
        report = build_report(MANIFEST, perms, {"list_files", "read_file", "clarify"},
                              flag_overrides={"AIBA_WEB_ENABLED": False})
        self.assertTrue(report.by_name()["list_files"].ready)
        self.assertTrue(report.by_name()["read_file"].ready)
        self.assertTrue(report.by_name()["clarify"].ready)


class DependencyProbeTests(unittest.TestCase):
    """Task: optional-dependency labels must fail closed on unknown probe types
    and reflect the real environment (importlib find_spec / shutil.which)."""

    def test_installed_python_dependency_satisfied(self):
        # importlib.util works right now -> satisfied.
        self.assertTrue(_dep_satisfied("python:importlib.util"))

    def test_installed_binary_dependency_satisfied(self):
        self.assertTrue(_dep_satisfied("binary:python"))

    def test_missing_python_dependency_unavailable(self):
        self.assertFalse(_dep_satisfied("python:definitely_not_a_real_module_xyz"))

    def test_missing_binary_dependency_unavailable(self):
        self.assertFalse(_dep_satisfied("binary:definitely_not_a_real_binary_xyz"))

    def test_none_dependency_always_satisfied(self):
        self.assertTrue(_dep_satisfied("none"))
        self.assertTrue(_dep_satisfied(""))

    def test_unknown_probe_type_fails_closed(self):
        # Unknown probe types must NOT silently report ready.
        self.assertFalse(_dep_satisfied("needs:python"))           # legacy syntax
        self.assertFalse(_dep_satisfied("frobnicate:python"))       # unknown type
        self.assertFalse(_dep_satisfied("docker"))                  # no colon at all
        self.assertFalse(_dep_satisfied("python:"))                 # empty target

    def test_build_report_uses_probe_for_ready(self):
        # A tool whose manifest declares a dependency on a missing module must
        # be reported unavailable, not ready.
        manifest = {"version": 1, "tools": {
            "web_search": {
                "description": "x", "risk_class": "read_only_network",
                "default_enabled": True, "requires_approval": False,
                "feature_flag": "none", "optional_dependency": "python:definitely_not_a_real_module_xyz",
            }
        }}
        perms = {"version": 1, "tools": {"web_search": {"enabled": True, "requires_approval": False}}}
        report = build_report(manifest, perms, {"web_search"})
        e = report.by_name()["web_search"]
        self.assertFalse(e.ready)
        self.assertFalse(e.dep_satisfied)
        self.assertIn("optional dependency", e.reason)

    def test_build_report_probe_override_injected(self):
        # Injecting a probe lets the caller control dependency resolution; a
        # False probe must make the tool unavailable and not silently ready.
        manifest = {"version": 1, "tools": {
            "web_search": {
                "description": "x", "risk_class": "read_only_network",
                "default_enabled": True, "requires_approval": False,
                "feature_flag": "none", "optional_dependency": "binary:whatever",
            }
        }}
        perms = {"version": 1, "tools": {"web_search": {"enabled": True, "requires_approval": False}}}
        report = build_report(manifest, perms, {"web_search"},
                              dependency_probe=lambda dep: dep == "binary:whatever")
        self.assertTrue(report.by_name()["web_search"].ready)
        report2 = build_report(manifest, perms, {"web_search"},
                               dependency_probe=lambda dep: False)
        self.assertFalse(report2.by_name()["web_search"].ready)


if __name__ == "__main__":
    unittest.main()
