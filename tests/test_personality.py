from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from personality import PersonalExperience


class PersonalExperienceTests(unittest.TestCase):
    def make(self, root: Path):
        (root / "SOUL.md").write_text("AIBA is playful and clear.", encoding="utf-8")
        return PersonalExperience(root, root / "data")

    def test_one_question_at_a_time_and_resume(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);experience = self.make(root)
            self.assertIn("What should I call you", experience.begin("telegram:42"))
            self.assertIn("what kind of work", experience.intercept("telegram:42", "Josh").lower())
            # Restart from disk: onboarding must resume where it left off.
            resumed = PersonalExperience(root, root / "data")
            self.assertIn("what kind of work", resumed.begin("telegram:42").lower())
            self.assertIn("main thing", resumed.intercept("telegram:42", "Business owner").lower())
            self.assertIn("communicate", resumed.intercept("telegram:42", "Grow AIBA").lower())
            self.assertIn("what should we tackle", resumed.intercept("telegram:42", "Friendly").lower())

    def test_profiles_are_separate_and_private(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);experience = self.make(root)
            experience.begin("telegram:1");experience.begin("telegram:2")
            experience.intercept("telegram:1", "Josh")
            experience.intercept("telegram:2", "Sam")
            files = list((root / "data" / "profiles").glob("*.json"))
            self.assertEqual(len(files), 2)
            # No raw user id leaks into filenames (colon is made filesystem-safe).
            for f in files:
                self.assertNotIn("telegram:", f.name)
            # Private profile files are owner-read/write only.
            for f in files:
                self.assertEqual(f.stat().st_mode & 0o777, 0o600)

    def test_memory_controls_and_prompt_context(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);experience = self.make(root)
            experience.begin("telegram:42");experience.intercept("telegram:42", "Josh")
            self.assertIn("paused", experience.intercept("telegram:42", "/memory pause").lower())
            self.assertFalse(experience.load("telegram:42")["memory_active"])
            context = experience.prompt_context("telegram:42")
            self.assertIn("AIBA is playful", context);self.assertIn("Josh", context)
            # Re-enable memory.
            self.assertIn("resumed", experience.intercept("telegram:42", "/memory resume").lower())
            self.assertTrue(experience.load("telegram:42")["memory_active"])

    def test_skip_and_profile_commands(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);experience = self.make(root)
            self.assertIn("skip", experience.intercept("whatsapp:1", "/skip").lower())
            self.assertIsNone(experience.intercept("whatsapp:1", "Do a task"))
            self.assertIn("what i know", experience.intercept("whatsapp:1", "/profile").lower())

    def test_context_never_exposes_chain_of_thought(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);experience = self.make(root)
            experience.intercept("telegram:9", "Priya")
            context = experience.prompt_context("telegram:9")
            # Context is plain user facts + soul: no private deliberation markers.
            for forbidden in ("chain-of-thought", "thinking", "reasoning", "secret prompt", "credentials"):
                self.assertNotIn(forbidden, context.lower())

    def test_anonymous_prompt_context_is_empty(self):
        with TemporaryDirectory() as tmp:
            experience = self.make(Path(tmp))
            self.assertEqual(experience.prompt_context(None), "")

    def test_finished_user_routes_tasks_to_agent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);experience = self.make(root)
            experience.intercept("telegram:33", "Milo")
            for _ in range(3):
                experience.intercept("telegram:33", "something")
            # After onboarding finishes, normal messages are not intercepted.
            self.assertIsNone(experience.intercept("telegram:33", "Please summarize this file"))


if __name__ == "__main__":
    unittest.main()
