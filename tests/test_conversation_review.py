from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.conversation_review import ConversationReviewer


class ConversationReviewerTests(unittest.TestCase):
    def test_records_correction_without_chain_of_thought(self):
        with tempfile.TemporaryDirectory() as tmp:
            reviewer = ConversationReviewer(Path(tmp))
            result = reviewer.review(
                "task-1", "conv-1",
                "Actually, don't email them. Draft it instead.",
                "Draft prepared.", ["write_file"], "complete",
            )
            self.assertTrue(result["needs_review"])
            self.assertIn("user_correction", result["signals"])
            self.assertFalse(result["policy"]["source_rewrite_allowed"])
            self.assertFalse(result["policy"]["private_chain_of_thought_stored"])
            files = list(Path(tmp).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            stored = json.loads(files[0].read_text(encoding="utf-8").strip())
            self.assertNotIn("user_text", stored)
            self.assertNotIn("answer", stored)

    def test_quiet_turn_does_not_claim_improvement(self):
        with tempfile.TemporaryDirectory() as tmp:
            reviewer = ConversationReviewer(Path(tmp))
            result = reviewer.review("task-2", "conv-2", "Thanks", "You're welcome.", [], "complete")
            self.assertFalse(result["needs_review"])
            self.assertEqual(result["signals"], [])


if __name__ == "__main__":
    unittest.main()
