"""AgentLoop integration tests for the Internal Subagents (Phase 3) capability.

These build a *genuine* AgentLoop over an isolated temporary root (canonical
config/capability_manifest.json + permissions.json copied in, no credentials,
no live model, no browser/desktop) and assert the tool-surface contract:

  Disabled-by-default (the shipped posture)
    * delegate_task is REGISTERED (so capability reporting sees it) but absent
      from the model-visible schema list
    * a direct execute() returns an actionable denial
    * the capability report explains that it is disabled in permissions.json

  Feature flag alone is NOT enough
    * with subagents_enabled=True but delegate_task still disabled in
      permissions.json, execute() still blocks (permissions are authoritative)

  Both enabled (operator opt-in)
    * delegate_task becomes visible under the intended approval rules
    * a fake-provider delegation runs to completion and the main loop gets a
      concise, structured result — never a worker transcript
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings

REPO = Path(__file__).resolve().parents[1]

CANONICAL_PERMISSIONS = REPO / "config" / "permissions.json"
CANONICAL_MANIFEST = REPO / "config" / "capability_manifest.json"


def make_settings(tmp: Path, *, subagents=False, delegate_enabled=False,
                  auto_approve=False) -> tuple[Settings, Path]:
    """Build an isolated Settings (and return the isolated permissions path).

    ``delegate_enabled=True`` writes an operator-opted-in permissions.json
    (delegate_task -> enabled:true) under the temp root, emulating a real user
    having enabled the feature in addition to the runtime flag.
    """
    data = tmp / "data"
    for d in ("workspace", "vault", "logs", "reflections", "skill_proposals"):
        (data / d).mkdir(parents=True, exist_ok=True)
    skills = tmp / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    cfg = tmp / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    # copy canonical policy, then optionally override delegate_task to enabled
    shutil.copy(CANONICAL_PERMISSIONS, cfg / "permissions.json")
    shutil.copy(CANONICAL_MANIFEST, cfg / "capability_manifest.json")
    if delegate_enabled:
        perms = json.loads((cfg / "permissions.json").read_text())
        perms["tools"]["delegate_task"]["enabled"] = True
        (cfg / "permissions.json").write_text(json.dumps(perms, indent=2))
    di = lambda p: tmp / p  # noqa: E731
    settings = Settings(
        root_dir=tmp, data_dir=data, workspace_dir=di("data/workspace"),
        vault_dir=di("data/vault"), logs_dir=di("data/logs"),
        skills_dir=skills,
        db_path=di("data/aiba.db"), tasks_db_path=di("data/tasks.db"),
        jobs_db_path=di("data/jobs.db"),
        schedules_db_path=di("data/schedules.db"),
        auth_db_path=di("data/auth.db"),
        providers_db_path=di("data/providers.db"),
        provider="local", fallback_provider="local", model="local-v1",
        fallback_model="local-v1", max_steps=20, command_timeout=10,
        require_approval=True, sandbox_mode="local",
        docker_image="python:3.12-slim", docker_memory="512m", docker_cpus="1.0",
        sandbox_network=False, permissions_path=cfg / "permissions.json",
        browser_enabled=False, desktop_enabled=False, vision_model="",
        worker_enabled=True, api_token="x" * 40, api_host="127.0.0.1",
        api_port=8765, allowed_origins=(), rate_limit_per_minute=60,
        web_enabled=False, computer_node_path=data / "computer_node.json",
        desktop_clipboard_enabled=False, desktop_process_enabled=False,
        subagents_enabled=subagents,
    )
    _ = auto_approve  # surfaced via make_loop auto_approve, not Settings
    return settings, cfg / "permissions.json"


def make_loop(tmp: Path, settings: Settings, *, auto_approve=False):
    from agent.loop import AgentLoop
    return AgentLoop(settings=settings, interactive=False,
                     auto_approve=auto_approve, start_worker=False)


class FakeRouter:
    """Stand-in for loop.router.complete: returns scripted model action JSON."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def complete(self, messages, schemas):
        self.calls.append([s.get("name") for s in (schemas or [])])
        idx = max(0, len(self.calls) - 1)
        action = self._script[min(idx, len(self._script) - 1)] if self._script \
            else {"type": "final", "response": "done"}
        return json.dumps(action)


class SubagentsLoopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_subag_loop_")
        self.tmp = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- disabled by default -------------------------------------------------
    def test_disabled_registered_but_not_model_visible(self):
        settings, _ = make_settings(self.tmp, subagents=False)
        loop = make_loop(self.tmp, settings)
        self.assertIn("delegate_task", loop.registry._tools)
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertNotIn("delegate_task", visible)

    def test_disabled_direct_execute_actionable_denial(self):
        settings, _ = make_settings(self.tmp, subagents=False)
        loop = make_loop(self.tmp, settings)
        res = loop.registry.execute("delegate_task",
                                    {"objectives": ["anything"]})
        self.assertFalse(res.ok)
        self.assertTrue(res.error)
        self.assertIn("delegate_task", res.error)

    def test_disabled_capability_report_explains(self):
        settings, _ = make_settings(self.tmp, subagents=False)
        loop = make_loop(self.tmp, settings)
        report = loop.capability_report().by_name()
        e = report["delegate_task"]
        self.assertFalse(e.ready)
        self.assertIn("disabled", (e.reason or "").lower())

    def test_loop_close_is_idempotent_and_safe_with_subagents(self):
        # Building the loop always attaches the (disabled) manager; a benign
        # initialisation + close should not raise.
        settings, _ = make_settings(self.tmp, subagents=False)
        loop = make_loop(self.tmp, settings)
        self.assertTrue(hasattr(loop, "subagents"))
        loop.close()
        loop.close()   # idempotent second close (no lingering threads)

    def test_no_admin_subagent_tools_ever_registered(self):
        # Status/cancel/administration stay OFF the model tool surface entirely.
        settings, _ = make_settings(self.tmp, subagents=True,
                                    delegate_enabled=True)
        loop = make_loop(self.tmp, settings, auto_approve=True)
        names = set(loop.registry._tools.keys())
        for admin in ("subagent_status", "subagent_cancel", "spawn_subagent",
                      "subagent_list"):
            self.assertNotIn(admin, names,
                             f"{admin} must not be registered as a model tool")
        # only the single delegation entry point is model-visible
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertIn("delegate_task", visible)
        self.assertNotIn("subagent_status", visible)

    # -- flag alone is insufficient -----------------------------------------
    def test_feature_flag_without_permission_still_blocks(self):
        # subagents_enabled=True flips the runtime flag, but delegate_task stays
        # enabled:false in the canonical permissions -> still denied.
        settings, _ = make_settings(self.tmp, subagents=True,
                                    delegate_enabled=False)
        loop = make_loop(self.tmp, settings, auto_approve=True)
        res = loop.registry.execute("delegate_task",
                                    {"objectives": ["x"]})
        self.assertFalse(res.ok)
        self.assertIn("delegate_task", res.error)
        # and not advertised to the model
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertNotIn("delegate_task", visible)

    # -- both enabled --------------------------------------------------------
    def test_both_enabled_visible_and_fake_delegation_completes(self):
        settings, _ = make_settings(self.tmp, subagents=True,
                                    delegate_enabled=True)
        loop = make_loop(self.tmp, settings, auto_approve=True)
        visible = {s["name"] for s in loop.registry.schemas()}
        self.assertIn("delegate_task", visible)
        # Prove the real registry refuses WITHOUT approval (auto_approve False
        # and an approval manager that denies) — delegate_task requires approval.
        settings2, _ = make_settings(self.tmp, subagents=True,
                                     delegate_enabled=True)
        loop_na = make_loop(self.tmp, settings2, auto_approve=False)
        res_na = loop_na.registry.execute("delegate_task",
                                          {"objectives": ["nope"]})
        self.assertFalse(res_na.ok)
        loop_na.close()
        # Now with approval granted inject a safe fake router for the worker.
        fake = FakeRouter([
            {"type": "tool_call", "tool": "list_files", "arguments": {}},
            {"type": "final", "response": "Concluded: workspace is empty"},
        ])
        loop.router.complete = fake.complete
        res = loop.registry.execute(
            "delegate_task",
            {"objectives": ["summarise the workspace"],
             "tools": ["list_files"]},
        )
        self.assertTrue(res.ok, msg=f"delegation failed: {res.error}")
        payload = res.output
        self.assertIsInstance(payload, dict)
        results = payload.get("worker_results", [])
        self.assertTrue(len(results) >= 1)
        top = results[0]
        self.assertEqual(top["status"], "completed")
        self.assertIn("Concluded", top["result"])
        # synthesis is concise and structured, never a raw transcript
        synth = payload.get("synthesis", "")
        self.assertIn("completed", synth)
        self.assertLess(len(synth), 800)
        # The model surface got a concise final; it does NOT see the objective
        # echoed nor a giant machine transcript.
        loop.close()

    def test_delegation_denied_when_subagent_manager_disabled_via_settings(self):
        # Guard rails hold even if the registry were flipped somehow: the tool
        # handler refuses when settings.subagents_enabled is False. (Here the
        # manager itself is disabled so this exercises the ValueError path.)
        settings, _ = make_settings(self.tmp, subagents=False,
                                    delegate_enabled=True)
        loop = make_loop(self.tmp, settings, auto_approve=True)
        # delegate_task is registered & permission-enabled here, but the manager
        # is disabled -> the tool body raises an actionable disabled reason.
        res = loop.registry.execute("delegate_task",
                                    {"objectives": ["should fail closed"]})
        self.assertFalse(res.ok)
        self.assertTrue(res.error)
        loop.close()


if __name__ == "__main__":
    unittest.main()
