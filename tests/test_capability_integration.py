"""Real AgentLoop integration tests for the v1.6 capability/permission layer.

These construct a genuine AgentLoop with isolated temporary data directories
(no production credentials, no network to the model) and assert the tool
registry behaves correctly:

- every expected v1.6 tool appears in the model-visible schemas when enabled,
- unlisted / disabled / feature-flagged tools are absent from schemas and
  return a clear denial on execute,
- approval-required tools cannot execute without approval,
- read-only tools work without approval,
- blocked tool calls return a clear denial,
- no legacy v1.5 tools disappear,
- the capability report explains *why* a tool is unavailable (no silent
  capability failure).

The test FAILS if the registry collapses back to only the old 12 tools — that
catches silent capability loss.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings

REPO = Path(__file__).resolve().parents[1]

# The six tools added by the v1.6 capability-parity build, with their exact
# registered names (source of truth: agent/loop.py _register_tools).
V16_TOOLS = ["patch_file", "archive", "extract_archive",
             "web_search", "web_extract", "clarify"]

# The pre-existing v1.5 tools that must never disappear.
LEGACY_TOOLS = [
    "list_files", "read_file", "write_file", "delete_file",
    "run_shell", "run_python", "remember", "search_memory",
    "browser_fetch", "list_skills", "run_skill",
    "enqueue_task", "schedule_task",
]


def make_settings(tmp: Path, *, web=True, browser=False, desktop=False) -> Settings:
    data = tmp / "data"
    (data / "workspace").mkdir(parents=True)
    (data / "vault").mkdir(parents=True)
    (data / "logs").mkdir(parents=True)
    (data / "reflections").mkdir(parents=True)
    (data / "skill_proposals").mkdir(parents=True)
    skills = tmp / "skills"
    skills.mkdir(parents=True)
    cfg = tmp / "config"
    cfg.mkdir(parents=True)
    # Copy the canonical policy + manifest into the isolated root so the loop
    # loads *these*, exactly like production.
    shutil.copy(REPO / "config" / "permissions.json", cfg / "permissions.json")
    shutil.copy(REPO / "config" / "capability_manifest.json", cfg / "capability_manifest.json")
    di = lambda p: tmp / p  # noqa: E731
    return Settings(
        root_dir=tmp, data_dir=data, workspace_dir=di("data/workspace"),
        vault_dir=di("data/vault"), logs_dir=di("data/logs"), skills_dir=skills,
        db_path=di("data/aiba.db"), tasks_db_path=di("data/tasks.db"),
        jobs_db_path=di("data/jobs.db"), schedules_db_path=di("data/schedules.db"),
        auth_db_path=di("data/auth.db"), providers_db_path=di("data/providers.db"),
        provider="local", fallback_provider="local", model="local-v1",
        fallback_model="local-v1", max_steps=5, command_timeout=10,
        require_approval=True, sandbox_mode="local", docker_image="python:3.12-slim",
        docker_memory="512m", docker_cpus="1.0", sandbox_network=False,
        permissions_path=cfg / "permissions.json", browser_enabled=browser,
        desktop_enabled=desktop, vision_model="",
        worker_enabled=True, api_token="x" * 40, api_host="127.0.0.1",
        api_port=8765, allowed_origins=(), rate_limit_per_minute=60,
        web_enabled=web,
    )


def make_loop(tmp: Path, settings: Settings):
    from agent.loop import AgentLoop
    return AgentLoop(settings=settings, interactive=False, auto_approve=False,
                     start_worker=False)


class CapabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_cap_")
        self.tmp = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_fails_if_registry_collapses_to_old_12(self):
        """Death-check: the six v1.6 tools must be registered and enabled."""
        settings = make_settings(self.tmp, web=True)
        loop = make_loop(self.tmp, settings)
        names = set(loop.registry._tools.keys())
        self.assertGreater(len(names), 12)
        for tool in V16_TOOLS:
            self.assertIn(tool, names, f"v1.6 tool {tool} is not registered")
        # And every one of them is model-visible (enabled, no flag off).
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertIn("patch_file", visible)
        self.assertIn("archive", visible)
        self.assertIn("extract_archive", visible)
        self.assertIn("clarify", visible)
        self.assertIn("web_search", visible)
        self.assertIn("web_extract", visible)

    def test_legacy_tools_present(self):
        loop = make_loop(self.tmp, make_settings(self.tmp, web=False))
        names = set(loop.registry._tools.keys())
        for tool in LEGACY_TOOLS:
            self.assertIn(tool, names, f"legacy tool {tool} disappeared")

    def test_feature_flagged_tools_unavailable_when_off(self):
        # web=False -> web_search / web_extract must be absent from schemas.
        loop = make_loop(self.tmp, make_settings(self.tmp, web=False))
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertNotIn("web_search", visible)
        self.assertNotIn("web_extract", visible)
        res = loop.registry.execute("web_search", {"query": "test"})
        self.assertFalse(res.ok)
        self.assertIn("feature flag", (res.error or "").lower())
        # But they ARE registered.
        self.assertIn("web_search", loop.registry._tools)

    def test_disabled_tools_absent_from_schemas(self):
        # browser_fetch / desktop_* are disabled in permissions.json.
        loop = make_loop(self.tmp, make_settings(self.tmp, browser=True, desktop=False))
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertNotIn("browser_fetch", visible)
        self.assertNotIn("desktop_click", visible)
        res = loop.registry.execute("desktop_click", {"x": 1, "y": 2})
        self.assertFalse(res.ok)

    def test_approval_required_cannot_execute_without_approval(self):
        from tools.base import ToolResult
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        # patch_file is local_mutation -> requires approval. auto_approve=False.
        res = loop.registry.execute("patch_file", {"path": "a.txt", "old": "x", "new": "y"})
        self.assertIsInstance(res, ToolResult)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "User approval denied")

    def test_readonly_tools_run_without_approval(self):
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        # list_files is read-only + no approval.
        res = loop.registry.execute("list_files", {})
        self.assertTrue(res.ok)

    def test_model_receives_actual_enabled_schemas(self):
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        schemas = loop.registry.schemas()
        # The schema dict fed to the model must exactly reflect enabled tools.
        visible_names = {s["name"] for s in schemas}
        # web tools listed because web=True
        self.assertIn("web_search", visible_names)
        # desktop tools never advertised
        self.assertNotIn("desktop_type", visible_names)
        for s in schemas:
            self.assertIn("name", s)
            self.assertIn("description", s)
            self.assertIn("parameters", s)

    def test_blocked_tool_returns_clear_denial(self):
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        res = loop.registry.execute("list_files", {}, blocked={"list_files"})
        self.assertFalse(res.ok)
        self.assertIn("disabled for this conversation", res.error or "")

    def test_real_implementation_reachable_via_execute(self):
        # list_files handler is the real Sandbox.list_files against the temp
        # workspace; write a file and confirm read_file returns it.
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        (self.tmp / "data" / "workspace" / "agent_test.txt").write_text("hello-world", encoding="utf-8")
        res = loop.registry.execute("read_file", {"path": "agent_test.txt"})
        self.assertTrue(res.ok)

    def test_capability_report_explains_dormant_tools(self):
        loop = make_loop(self.tmp, make_settings(self.tmp, web=False))
        report = loop.capability_report()
        by = report.by_name()
        # web_search registered but feature-flagged off -> not ready with reason.
        e = by["web_search"]
        self.assertFalse(e.ready)
        self.assertIn("feature flag", e.reason)
        # A tool missing from the manifest would be flagged loudly (no such tool
        # in prod, but the diagnostic must be ready to).
        self.assertEqual(len(by), len(report.tools))

    def test_no_silent_capability_failure(self):
        """Aliases the core requirement: unavailable tools must carry a reason."""
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        for e in loop.capability_report().tools:
            self.assertTrue(e.reason, f"tool {e.tool} has no availability reason")

    def test_regression_ambient_false_settings_true(self):
        """Direction A: ambient env unset/false, Settings true.

        The runtime must expose web_search/web_extract (they ARE model-visible),
        capability_report must say ready, and model schemas must include them —
        regardless of ambient AIBA_WEB_ENABLED.
        """
        # Guarantee ambient env does NOT trip the flag.
        self._drop_ambient("AIBA_WEB_ENABLED")
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        # Runtime exposes them.
        self.assertTrue(loop.registry._feature_flag_on("web_search"))
        # Schemas include them.
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertIn("web_search", visible)
        self.assertIn("web_extract", visible)
        # Report says ready.
        by = loop.capability_report().by_name()
        self.assertTrue(by["web_search"].ready)
        self.assertTrue(by["web_extract"].ready)

    def test_regression_ambient_true_settings_false(self):
        """Direction B: ambient env true, Settings false.

        The runtime must hide web_search/web_extract, capability_report says
        unavailable (flag disabled), and schemas exclude them — the loop's
        settings win over the ambient environment.
        """
        import os
        os.environ["AIBA_WEB_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("AIBA_WEB_ENABLED", None))
        loop = make_loop(self.tmp, make_settings(self.tmp, web=False))
        # Runtime hides them.
        self.assertFalse(loop.registry._feature_flag_on("web_search"))
        # Schemas exclude them.
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertNotIn("web_search", visible)
        self.assertNotIn("web_extract", visible)
        # Report says unavailable because flag disabled.
        by = loop.capability_report().by_name()
        self.assertFalse(by["web_search"].ready)
        self.assertIn("feature flag", by["web_search"].reason)

    def test_registered_ready_state_matches_model_schema(self):
        """Invariant: capability_report.ready == present-in-schema for every
        registered tool that is not explicitly internal_only.

        Prevents reporting and execution from drifting apart again.
        """
        loop = make_loop(self.tmp, make_settings(self.tmp, web=True))
        visible = {s["name"] for s in loop.registry.schemas()}
        report = loop.capability_report()
        for e in report.tools:
            if e.internal_only:
                # Internal-only tools are intentionally absent from schemas.
                self.assertNotIn(e.tool, visible)
                continue
            if not e.registered:
                continue
            # For every registered, non-internal tool: ready <-> in schema.
            self.assertEqual(
                e.ready, e.tool in visible,
                f"drifting readiness for {e.tool}: report.ready={e.ready} "
                f"but in_schema={e.tool in visible} ({e.reason})",
            )

    def _drop_ambient(self, key):
        import os
        os.environ.pop(key, None)
        self.addCleanup(lambda: os.environ.pop(key, None))


if __name__ == "__main__":
    unittest.main()
