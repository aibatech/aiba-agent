"""Tests for the Phase 9 SessionStore (session history + FTS search)."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.sessions import SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="aiba_sess_")
        self.db = Path(self._dir) / "sessions.db"
        self.store = SessionStore(self.db)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_open_append_close_roundtrip(self):
        sid = self.store.open_session("u1", title="debug cold start")
        self.store.append(sid, summary="found DB lock")
        self.store.close_session(sid)
        rec = self.store.get(sid)
        self.assertEqual(rec["user_key"], "u1")
        self.assertEqual(rec["status"], "closed")
        self.assertIn("DB lock", rec["summary"])

    def test_list_by_user_bounded_and_latest_first(self):
        ids = [self.store.open_session("u1", title=f"s{i}") for i in range(3)]
        # verify newest-first ordering by touch
        self.store.touch(ids[0])
        listed = self.store.list_by_user("u1")
        self.assertEqual(len(listed), 3)
        # returns dict per row incl id
        self.assertEqual({r["id"] for r in listed}, set(ids))

    def test_fts_search_scoped_per_user_no_cross_leak(self):
        a = self.store.open_session("user1", title="alpha DB lock investigation")
        self.store.append(a, summary="root cause is the sqlite WAL lock; use WAL")
        b = self.store.open_session("user2", title="private DB lock research")
        # user1 sees only their own row
        hits1 = self.store.search("user1", "WAL lock")
        self.assertEqual([r["id"] for r in hits1], [a])
        # user2 must NOT see user1's session even though text overlaps
        hits2 = self.store.search("user2", "WAL")
        self.assertEqual(hits2, [])

    def test_delete_requires_owner(self):
        sid = self.store.open_session("u1", title="t")
        self.assertFalse(self.store.delete(sid, "someone-else"))
        self.assertTrue(self.store.delete(sid, "u1"))
        self.assertIsNone(self.store.get(sid))

    def test_recover_interrupted_marks_active(self):
        sid = self.store.open_session("u1", title="x")  # stays 'active'
        done = self.store.open_session("u1", title="y")
        self.store.close_session(done)
        n = self.store.recover_interrupted()
        self.assertEqual(n, 1)
        self.assertEqual(self.store.get(sid)["status"], "interrupted")
        self.assertEqual(self.store.get(done)["status"], "closed")

    def test_no_transcript_or_secret_columns(self):
        cols = {r[1] for r in sqlite3.connect(self.db).execute(
            "PRAGMA table_info(sessions)")}
        for leaky in ("messages", "prompt", "transcript", "tool_history", "raw"):
            self.assertNotIn(leaky, cols)

    def test_defaults_empty_store(self):
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.store.list_by_user("u1"), [])
        self.assertEqual(self.store.search("u1", "anything"), [])


if __name__ == "__main__":
    unittest.main()
