"""AgentLoop integration tests for Phase 9 — memory maintenance + session
history surfaced as model tools, and per-turn session auto-logging.

These build a *genuine* AgentLoop over an isolated temporary root (canonical
Phase 9 isolation: no cross-user leak, key-free, headless-safe) with a
scripted FakeRouter compatible with the main-engine provider call so no real
provider is contacted. The loop auto-opens a session row per handled turn and
exposes read-only session tools plus memory edit/delete/list/export tools kept
in manifest/permissions parity.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings

REPO = Path(__file__).resolve().parents[1]
CANONICAL_PERMISSIONS = REPO / "config" / "permissions.json"
CANONICAL_MANIFEST = REPO / "config" / "capability_manifest.json"


def make_settings(tmp: Path) -> Settings:
    data = tmp / "data"
    for d in ("workspace", "vault", "logs", "reflections", "skill_proposals"):
        (data / d).mkdir(parents=True, exist_ok=True)
    skills = tmp / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    cfg = tmp / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    shutil.copy(CANONICAL_PERMISSIONS, cfg / "permissions.json")
    shutil.copy(CANONICAL_MANIFEST, cfg / "capability_manifest.json")
    di = lambda p: tmp / p  # noqa: E731
    return Settings(
        root_dir=tmp, data_dir=data, workspace_dir=di("data/workspace"),
        vault_dir=di("data/vault"), logs_dir=di("data/logs"),
        skills_dir=skills,
        db_path=di("data/aiba.db"), tasks_db_path=di("data/tasks.db"),
        sessions_db_path=di("data/sessions.db"),
        jobs_db_path=di("data/jobs.db"),
        schedules_db_path=di("data/schedules.db"),
        auth_db_path=di("data/auth.db"),
        providers_db_path=di("data/providers.db"),
        provider="local", fallback_provider="local", model="local-v1",
        fallback_model="local-v1", max_steps=3, command_timeout=10,
        require_approval=True, sandbox_mode="local",
        docker_image="python:3.12-slim", docker_memory="512m", docker_cpus="1.0",
        sandbox_network=False, permissions_path=cfg / "permissions.json",
        browser_enabled=False, desktop_enabled=False, vision_model="",
        worker_enabled=True, api_token="x" * 40, api_host="127.0.0.1",
        api_port=8765, allowed_origins=(), rate_limit_per_minute=60,
        web_enabled=False, computer_node_path=data / "computer_node.json",
        desktop_clipboard_enabled=False, desktop_process_enabled=False,
    )


class FakeRouter:
    """Stand-in for the main-engine provider call.

    ``engine.run`` invokes ``provider.complete(messages, schemas,
    task_type=..., manual_model_id=...)`` and ``_parse`` consumes the returned
    JSON string. Return a single 'final' action so a handled turn completes
    after one step (enough to exercise session auto-logging).
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def complete(self, messages, schemas, task_type=None, manual_model_id=None):
        self.calls.append([s.get("name") for s in (schemas or [])])
        idx = max(0, len(self.calls) - 1)
        action = self._script[min(idx, len(self._script) - 1)] if self._script \
            else {"type": "final", "response": "done"}
        return json.dumps(action)


class Phase9LoopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_phase9_loop_")
        self.tmp = Path(self._tmp)
        self.settings = make_settings(self.tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_loop(self, auto_approve=True):
        from agent.loop import AgentLoop
        return AgentLoop(settings=self.settings, interactive=False,
                         auto_approve=auto_approve, start_worker=False)

    # -- tools registered + model-visible (parity) -------------------------
    def test_phase9_tools_registered_and_visible(self):
        loop = self._make_loop()
        try:
            wanted = {"session_search", "session_history", "update_memory",
                      "delete_memory", "list_memories", "export_memories"}
            self.assertTrue(wanted <= set(loop.registry._tools.keys()))
            visible = {s["name"] for s in loop.registry.schemas()}
            self.assertTrue(wanted <= visible,
                            f"missing from model surface: {wanted - visible}")
        finally:
            loop.close()

    def test_permission_posture(self):
        loop = self._make_loop(auto_approve=False)
        try:
            self.assertTrue(loop.policy.check_tool("delete_memory").requires_approval)
            self.assertTrue(loop.policy.check_tool("update_memory").requires_approval)
            self.assertTrue(loop.policy.check_tool("export_memories").requires_approval)
            self.assertFalse(loop.policy.check_tool("session_search").requires_approval)
            self.assertFalse(loop.policy.check_tool("session_history").requires_approval)
            self.assertFalse(loop.policy.check_tool("list_memories").requires_approval)
        finally:
            loop.close()

    # -- session auto-logging on a handled turn ----------------------------
    def test_handle_records_a_closed_session(self):
        loop = self._make_loop()
        try:
            loop.router.complete = FakeRouter(
                [{"type": "final", "response": "summarised the q3 epic"}]).complete
            answer = loop.handle("please summarise the q3 launch epic", user_id="u1")
            self.assertIn("summarised", answer)
            rows = loop.sessions.list_by_user("u1", limit=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "closed")
            self.assertIn("epic", (rows[0].get("title") or "").lower())
        finally:
            loop.close()

    def test_session_rows_are_user_scoped(self):
        loop = self._make_loop()
        try:
            loop.router.complete = FakeRouter(
                [{"type": "final", "response": "ok"}]).complete
            loop.handle("alice note about the launch date", user_id="alice")
            loop.handle("bob about the weekend coffee roast", user_id="bob")
            bob = loop.sessions.list_by_user("bob", limit=10)
            alice = loop.sessions.list_by_user("alice", limit=10)
            self.assertEqual(len(bob), 1)
            self.assertIn("coffee", (bob[0].get("title") or ""))
            # strict isolation: bob's log must not contain alice's content
            self.assertNotIn("launch", json.dumps(bob))
            self.assertIn("launch", json.dumps(alice))
        finally:
            loop.close()

    def test_handle_default_user_tags_sessions(self):
        loop = self._make_loop()
        try:
            loop.router.complete = FakeRouter(
                [{"type": "final", "response": "done"}]).complete
            loop.handle("general housekeeping note")
            rows = loop.sessions.list_by_user("default", limit=10)
            self.assertEqual(len(rows), 1)
            # unused explicit user does not see it either
            self.assertEqual(loop.sessions.list_by_user("someone_else", 10), [])
        finally:
            loop.close()

    # -- session read tools over the ambient user --------------------------
    def test_session_history_surfaces_recent_turns(self):
        loop = self._make_loop()
        try:
            # Handled turns restore the caller's context. The next tool call
            # must carry Amber's identity explicitly, not reuse a stale user.
            loop.router.complete = FakeRouter(
                [{"type": "final", "response": "noted the onboarding checklist"}]).complete
            loop.handle("remember to finish the q3 onboarding checklist", user_id="amber")
            self.assertEqual(loop._current_user, 'default')
            loop._current_user = 'amber'
            res = loop.registry.execute("session_history", {"limit": 5})
            self.assertTrue(res.ok, msg=f"session_history failed: {res.error}")
            self.assertGreaterEqual(len(res.output), 1)
        finally:
            loop.close()

    def test_session_search_read_tool_is_available(self):
        loop = self._make_loop()
        try:
            visible = {s["name"] for s in loop.registry.schemas()}
            self.assertIn("session_search", visible)
            # callable shape: read-only, no approval required
            res = loop.registry.execute("session_search", {"query": "nothing"})
            self.assertTrue(res.ok, msg=f"session_search failed: {res.error}")
        finally:
            loop.close()

    # -- memory maintenance tools ------------------------------------------
    def test_memory_update_delete_list_export_roundtrip(self):
        loop = self._make_loop(auto_approve=True)
        try:
            add = loop.registry.execute(
                "remember",
                {"content": "client prefers navy awnings", "category": "prefs",
                 "importance": 0.8})
            self.assertTrue(add.ok)
            mid = add.output["memory_id"]
            upd = loop.registry.execute(
                "update_memory",
                {"memory_id": mid, "content": "client prefers charcoal awnings"})
            self.assertTrue(upd.ok, msg=f"update failed: {upd.error}")
            got = loop.vault.get(mid)
            self.assertEqual(got["content"], "client prefers charcoal awnings")
            lst = loop.registry.execute("list_memories", {"category": "prefs"})
            self.assertTrue(lst.ok)
            self.assertTrue(any(r["id"] == mid for r in lst.output))
            exp = loop.registry.execute("export_memories", {"filename": "m.md"})
            self.assertTrue(exp.ok, msg=f"export failed: {exp.error}")
            self.assertTrue((loop.settings.workspace_dir / "m.md").exists())
            dele = loop.registry.execute("delete_memory", {"memory_id": mid})
            self.assertTrue(dele.ok, msg=f"delete failed: {dele.error}")
            self.assertIsNone(loop.vault.get(mid))
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
