from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from personality import PersonalExperience

_POSIX = sys.platform.startswith(("linux", "darwin", "freebsd", "openbsd"))


class PersonalExperienceTests(unittest.TestCase):
    def make(self, root: Path):
        (root / "SOUL.md").write_text("AIBA is playful and clear.", encoding="utf-8")
        return PersonalExperience(root, root / "data")

    def profile_files(self, root: Path, user_id: str):
        exp = self.make(root)
        # The opaque filename is derived from the user id; find the json by content.
        opaque = exp._opaque_id(user_id)
        return (root / "data" / "profiles") / f"{opaque}.json", (root / "data" / "profiles") / f"{opaque}-USER.md"

    # ------------------------------------------------ soul applies everywhere
    def test_soul_applied_without_user_id(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            context = exp.prompt_context(None)
            self.assertIn("AIBA is playful", context)
            self.assertNotIn("User's preferred name", context)
            # anonymous calls have no blocked tools
            self.assertEqual(exp.blocked_tools(None), set())

    def test_soul_applied_to_connector_conversation(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:7")
            exp.intercept("telegram:7", "Sami")
            context = exp.prompt_context("telegram:7")
            self.assertIn("AIBA is playful", context)
            self.assertIn("Sami", context)

    # ------------------------------------------------- real memory pause
    def test_memory_tool_blocked_while_paused(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:42")
            exp.intercept("telegram:42", "Josh")
            exp.intercept("telegram:42", "/memory pause")
            # remember tool is blocked at the schema/runtime level for the user
            self.assertIn("remember", exp.blocked_tools("telegram:42"))
            # and NOT for anonymous / other users
            self.assertNotIn("remember", exp.blocked_tools(None))

            # registry-level runtime rejection when a paused user calls remember
            from tools.base import Tool, ToolResult
            from tools.registry import ToolRegistry
            from security.audit import AuditLog
            from security.policy import SecurityPolicy

            audit = AuditLog(Path(tmp) / "x_audit.jsonl")
            perms = Path(tmp) / "perms.json"
            perms.write_text(json.dumps({
                "version": 1,
                "tools": {"remember": {"enabled": True, "requires_approval": False}},
                "blocked_command_fragments": [],
            }), encoding="utf-8")
            policy = SecurityPolicy(Path(tmp), perms, False)
            reg = ToolRegistry(audit, object(), policy)
            reg.register(Tool("remember", "Store durable memory.", lambda **kw: ToolResult(True, {}), {
                "type": "object", "properties": {}, "additionalProperties": True}))
            call = reg.execute("remember", {"content": "secret"}, blocked=exp.blocked_tools("telegram:42"))
            self.assertFalse(call.ok)
            self.assertIn("disabled", call.error)
            # A non-paused user's call is NOT blocked at the registry level.
            ok_call = reg.execute("remember", {"content": "secret"}, blocked=exp.blocked_tools(None))
            self.assertTrue(ok_call.ok)

    # ------------------------------------------------ private identifiers
    def test_raw_connector_ids_absent_from_filenames_and_usermd(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:987654321")
            exp.intercept("telegram:987654321", "Josh")
            exp.intercept("telegram:987654321", "Builder")
            json_path, md_path = self.profile_files(Path(tmp), "telegram:987654321")
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            for f in [json_path.name, md_path.name]:
                self.assertRegex(f, r"^[0-9a-f]{32}(-USER\.md|\.json)$")
                self.assertNotIn("telegram", f)
                self.assertNotIn("987654321", f)
            md = md_path.read_text(encoding="utf-8")
            self.assertNotIn("telegram", md)
            self.assertNotIn("987654321", md)

    # ------------------------------------------------ file security
    def test_posix_permissions(self):
        if not _POSIX:
            self.skipTest("POSIX mode bits are only asserted on POSIX")
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:1")
            exp.intercept("telegram:1", "Josh")
            pd = Path(tmp) / "data" / "profiles"
            self.assertEqual(pd.stat().st_mode & 0o700, 0o700)  # dir 0700
            json_path, md_path = self.profile_files(Path(tmp), "telegram:1")
            self.assertEqual(json_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(md_path.stat().st_mode & 0o777, 0o600)

    def test_windows_permissions_not_faked(self):
        # On non-POSIX we do not claim 0600; the module must still function.
        if _POSIX:
            self.skipTest("Windows behavior test only applies off-POSIX")
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:2")
            exp.intercept("telegram:2", "Josh")
            self.assertTrue((Path(tmp) / "data" / "profiles").exists())

    def test_atomic_profile_write(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:3")
            json_path, _ = self.profile_files(Path(tmp), "telegram:3")
            self.assertTrue(json_path.exists())
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertTrue(data.get("introduced"))
            # No leftover temp files.
            leftovers = [p for p in (Path(tmp) / "data" / "profiles").glob("*.tmp")]
            self.assertEqual(leftovers, [])

    def test_malformed_profile_recovery(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:4")
            json_path, _ = self.profile_files(Path(tmp), "telegram:4")
            # Corrupt the profile, then ensure loading recovers (backup + fresh).
            json_path.write_text("{ this is not valid json !!!", encoding="utf-8")
            revived = PersonalExperience(Path(tmp), Path(tmp) / "data")
            profile = revived.load("telegram:4")
            self.assertEqual(profile.get("step"), 0)
            backups = list((Path(tmp) / "data" / "profiles").glob("*.corrupt-*.json"))
            self.assertEqual(len(backups), 1)

    # ------------------------------------------------ first-contact onboarding
    def test_whatsapp_first_contact_shows_intro_not_store_as_name(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            # First WhatsApp message is a task; it must NOT be stored as the name.
            reply = exp.intercept("whatsapp:15551234567", "Build me a deck please")
            self.assertIn("I'm AIBA", reply)
            self.assertIn("What should I call you", reply)
            profile = exp.load("whatsapp:15551234567")
            self.assertNotEqual(profile.get("name"), "Build me a deck please")
            self.assertIsNone(profile.get("name"))
            self.assertTrue(profile.get("introduced"))

    def test_telegram_start_sets_introduced_state(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            reply = exp.start_conversation("telegram:5")
            self.assertIn("What should I call you", reply)
            profile = exp.load("telegram:5")
            self.assertTrue(profile.get("introduced"))

    # ------------------------------------------------ selectable options
    def test_numbered_communication_choices(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:6")
            exp.intercept("telegram:6", "Josh")
            exp.intercept("telegram:6", "Builder")
            # third open question answered -> the style choices are presented
            goal_reply = exp.intercept("telegram:6", "Grow")
            self.assertIn("1. Quick and direct", goal_reply)
            self.assertIn("2. Friendly and conversational", goal_reply)
            self.assertIn("3. Detailed and strategic", goal_reply)
            self.assertIn("Reply 1, 2, or 3", goal_reply)
            # choose option 2 -> normalized
            reply = exp.intercept("telegram:6", "2")
            self.assertIn("tackle first", reply)
            profile = exp.load("telegram:6")
            self.assertEqual(profile.get("style"), "Friendly and conversational")
            self.assertTrue(profile.get("done"))

    def test_invalid_choice_retry(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:8")
            exp.intercept("telegram:8", "Josh")
            exp.intercept("telegram:8", "Builder")
            exp.intercept("telegram:8", "Grow")  # presents the numbered choices
            profile = exp.load("telegram:8")
            self.assertNotIn("style", profile)
            # an invalid choice is refused with a polite re-prompt and NOT stored
            reply = exp.intercept("telegram:8", "purple")
            self.assertIn("Please reply 1, 2, or 3", reply)
            self.assertNotIn("style", exp.load("telegram:8"))
            # the same step is still pending; a valid choice now succeeds
            reply2 = exp.intercept("telegram:8", "1")
            self.assertIn("tackle first", reply2)
            self.assertEqual(exp.load("telegram:8").get("style"), "Quick and direct - recommended for everyday work")

    # ------------------------------------------------ onboarding resume
    def test_onboarding_restart_resume(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:9")
            exp.intercept("telegram:9", "Josh")          # name -> step 1
            exp.intercept("telegram:9", "Business owner") # work -> step 2
            # restart from disk mid-onboarding (after name+work, before goal)
            resumed = PersonalExperience(Path(tmp), Path(tmp) / "data")
            self.assertIn("help with", resumed.begin("telegram:9").lower())
            # answer the goal -> style choices are presented
            style_reply = resumed.intercept("telegram:9", "Grow my business")
            self.assertIn("communicate", style_reply.lower())
            resumed.intercept("telegram:9", "3")
            self.assertTrue(resumed.load("telegram:9").get("done"))
            self.assertEqual(resumed.load("telegram:9").get("style"), "Detailed and strategic")
            # a finished user routes tasks to the agent (None = not intercepted)
            self.assertIsNone(resumed.intercept("telegram:9", "Please draft a summary"))

    # ------------------------------------------------ no chain-of-thought
    def test_context_never_exposes_chain_of_thought(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.intercept("telegram:10", "Priya")
            context = exp.prompt_context("telegram:10")
            for forbidden in ("chain-of-thought", "thinking", "reasoning", "secret prompt", "credentials"):
                self.assertNotIn(forbidden, context.lower())

    # ------------------------------------------------ memory controls
    def test_memory_controls(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:99")
            exp.intercept("telegram:99", "Josh")
            self.assertIn("paused", exp.intercept("telegram:99", "/memory pause").lower())
            self.assertFalse(exp.load("telegram:99")["memory_active"])
            context = exp.prompt_context("telegram:99")
            self.assertIn("paused", context)
            self.assertIn("resumed", exp.intercept("telegram:99", "/memory resume").lower())
            self.assertTrue(exp.load("telegram:99")["memory_active"])

    def test_skip_and_profile_commands(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            self.assertIn("skip", exp.intercept("whatsapp:1", "/skip").lower())
            self.assertIsNone(exp.intercept("whatsapp:1", "Do a task"))
            self.assertIn("what i know", exp.intercept("whatsapp:1", "/profile").lower())

    def test_finished_user_routes_tasks_to_agent(self):
        with TemporaryDirectory() as tmp:
            exp = self.make(Path(tmp))
            exp.start_conversation("telegram:11")
            exp.intercept("telegram:11", "Josh")
            exp.intercept("telegram:11", "Builder")
            exp.intercept("telegram:11", "Grow")
            exp.intercept("telegram:11", "1")
            self.assertTrue(exp.load("telegram:11").get("done"))
            self.assertIsNone(exp.intercept("telegram:11", "Please summarize this file"))

    # ------------------------------------------ soul reaches the model request
    def test_anonymous_and_api_calls_receive_soul_in_system_prompt(self):
        # End-to-end: the engine builds the model request with the soul in the
        # system message even when there is no per-user profile (API / CLI /
        # scheduled / background calls), and the SYSTEM prompt is not a
        # technical v1.0 persona.
        from reasoning.engine import ReasoningEngine, SYSTEM
        from memory.vault import MemoryVault
        from memory.retrieval import RetrievalEngine

        # SYSTEM must not be the old technical "Agent v1.0" persona.
        self.assertNotIn("Agent v1.0", SYSTEM)
        self.assertNotIn("AIBA Agent v1", SYSTEM)
        self.assertIn("AIBA", SYSTEM)

        captured = {}

        class DummyProvider:
            def __init__(self, capture):
                self._cap = capture
            def complete(self, messages, schemas, task_type=None, manual_model_id=None):
                self._cap["messages"] = messages
                self._cap["schemas"] = schemas
                return {"type": "final", "response": "ok"}

        class DummyTasks:
            def create(self, t): return 1
            def event(self, *a, **k): pass
            def finish(self, *a, **k): pass

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SOUL.md").write_text("AIBA is playful and clear.", encoding="utf-8")
            exp = PersonalExperience(root, root / "data")
            vault = MemoryVault(root / "aiba.db", root / "vault")
            retrieval = RetrievalEngine(vault)
            prov = DummyProvider(captured)

            class DummyRegistry:
                def schemas(self, excluded=None):
                    return []
                def execute(self, name, args, blocked=None):
                    return {"ok": False, "output": None, "error": "no-op"}

            engine = ReasoningEngine(prov, DummyRegistry(), retrieval, DummyTasks(), max_steps=3)

            # Anonymous (API/CLI/scheduled) call -> soul present, no profile.
            engine.run(1, "task", task_type="text", prompt_context=exp.prompt_context(None),
                       blocked_tools=exp.blocked_tools(None))
            system = captured["messages"][0]["content"]
            self.assertIn("AIBA is playful", system)

            # Onboarding a real user does not expose chain-of-thought, and the
            # paused-memory note appears while memory is paused.
            exp.start_conversation("telegram:7")
            exp.intercept("telegram:7", "Sam")
            exp.intercept("telegram:7", "/memory pause")
            engine.run(1, "task", prompt_context=exp.prompt_context("telegram:7"),
                       blocked_tools=exp.blocked_tools("telegram:7"))
            system2 = captured["messages"][0]["content"]
            self.assertIn("paused", system2)
            # The personal-context portion carries only approved facts, never
            # thought traces. (The SYSTEM prompt itself says to never expose
            # chain-of-thought, so we scope the check to after "Personal context:".)
            personal = system2.split("Personal context:", 1)[1]
            for forbidden in ("chain-of-thought", "thinking", "credentials"):
                self.assertNotIn(forbidden, personal.lower())


if __name__ == "__main__":
    unittest.main()
