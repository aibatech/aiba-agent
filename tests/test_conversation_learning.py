from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.conversation_store import ConversationStore, default_conversation_id
from memory.learner import AutoLearner
from memory.vault import MemoryVault


class ConversationStoreTests(unittest.TestCase):
    def test_recent_history_is_persistent_ordered_and_user_scoped(self):
        with tempfile.TemporaryDirectory() as td:
            store = ConversationStore(Path(td) / "conversations.db")
            cid = store.ensure("user:a")
            self.assertEqual(cid, default_conversation_id("user:a"))
            store.append("user:a", cid, "user", "My name is Mike")
            store.append("user:a", cid, "assistant", "Nice to meet you")
            store.append("user:b", store.ensure("user:b"), "user", "private other-user text")
            rows = store.recent("user:a", cid)
            self.assertEqual([r["role"] for r in rows], ["user", "assistant"])
            self.assertEqual(rows[0]["content"], "My name is Mike")
            self.assertFalse(any("other-user" in r["content"] for r in rows))

    def test_new_conversations_do_not_mix(self):
        with tempfile.TemporaryDirectory() as td:
            store = ConversationStore(Path(td) / "conversations.db")
            store.ensure("u", "one")
            store.ensure("u", "two")
            store.append("u", "one", "user", "first chat")
            store.append("u", "two", "user", "second chat")
            self.assertEqual(store.recent("u", "one")[0]["content"], "first chat")
            self.assertEqual(store.recent("u", "two")[0]["content"], "second chat")


class AutoLearnerTests(unittest.TestCase):
    def test_learns_high_signal_preferences_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = MemoryVault(root / "aiba.db", root / "vault")
            learner = AutoLearner(vault)
            text = "I prefer short direct answers. My goal is to grow the business to $20M."
            first = learner.learn(text, owner="u", as_user="u")
            second = learner.learn(text, owner="u", as_user="u")
            self.assertGreaterEqual(len(first), 2)
            self.assertEqual(second, [])
            rows = vault.list(20, as_user="u")
            self.assertTrue(any("short direct answers" in r["content"] for r in rows))
            self.assertTrue(any("$20M" in r["content"] for r in rows))

    def test_ignores_low_signal_smalltalk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = MemoryVault(root / "aiba.db", root / "vault")
            learner = AutoLearner(vault)
            self.assertEqual(learner.learn("What time is it today?", owner="u", as_user="u"), [])


if __name__ == "__main__":
    unittest.main()
