"""Phase 9 — Session history + cross-session search.

A durable, per-user log of AIBA tasks/sessions with full-text search,
mirroring the existing ``memory/vault.py`` / ``agent/tasks.py`` conventions
(SQLite via the local ``sqlite_utils.connect`` transaction helper, ISO-8601
UTC timestamps, idempotent schema init, bounded reads, recover_interrupted).

The store records a row per session so operators can later answer "what did we
do about X / where did we leave Y" without replaying raw transcripts onto the
model surface. Rows carry a user/scope tag plus channel/task ids for isolation
(no cross-user leak) and a concise sanitised summary; secrets are never stored.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlite_utils import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """SQLite persistence + FTS for a per-user session/task history."""

    def __init__(self, path):
        self.path = path
        self._init()

    def _init(self) -> None:
        with connect(self.path) as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions(
                  id TEXT PRIMARY KEY,
                  user_key TEXT NOT NULL,
                  kind TEXT NOT NULL DEFAULT 'session',
                  title TEXT,
                  summary TEXT,
                  task_id TEXT,
                  channel TEXT,
                  status TEXT NOT NULL DEFAULT 'active',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                  title, summary, kind,
                  content=sessions, content_rowid=rowid
                );
                CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
                  INSERT INTO sessions_fts(rowid, title, summary, kind)
                  VALUES (new.rowid, new.title, new.summary, new.kind);
                END;
                CREATE TRIGGER IF NOT EXISTS sessions_ad AFTER DELETE ON sessions BEGIN
                  INSERT INTO sessions_fts(sessions_fts, rowid, title, summary, kind)
                  VALUES ('delete', old.rowid, old.title, old.summary, old.kind);
                END;
                CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
                  INSERT INTO sessions_fts(sessions_fts, rowid, title, summary, kind)
                  VALUES ('delete', old.rowid, old.title, old.summary, old.kind);
                  INSERT INTO sessions_fts(rowid, title, summary, kind)
                  VALUES (new.rowid, new.title, new.summary, new.kind);
                END;
                """
            )

    # -- writes -------------------------------------------------------------
    def open_session(self, user_key: str, title: str = "",
                     kind: str = "session") -> str:
        """Create a session row; returns the session id."""
        sid = str(uuid.uuid4())
        t = _now()
        with connect(self.path) as c:
            c.execute(
                "INSERT INTO sessions(id,user_key,kind,title,summary,status,"
                "created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?)",
                (sid, user_key, kind, title, title, t, t),
            )
        return sid

    def append(self, session_id: str, title: str | None = None,
               summary: str | None = None) -> None:
        """Update a session's title/summary (kept concise) and bump time."""
        t = _now()
        sets, vals = [], []
        if title is not None:
            sets.append("title=?"); vals.append(title)
        if summary is not None:
            sets.append("summary=?"); vals.append(summary)
        if not sets:
            return
        sets.append("updated_at=?"); vals.append(t)
        vals.append(session_id)
        with connect(self.path) as c:
            c.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", vals)

    def touch(self, session_id: str) -> None:
        t = _now()
        with connect(self.path) as c:
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?",
                      (t, session_id))

    def close_session(self, session_id: str) -> None:
        t = _now()
        with connect(self.path) as c:
            c.execute("UPDATE sessions SET status='closed', updated_at=? "
                      "WHERE id=?", (t, session_id))

    def delete(self, session_id: str, user_key: str | None = None) -> bool:
        """Remove a session (optionally requiring the owning user)."""
        with connect(self.path) as c:
            if user_key is not None:
                cur = c.execute("DELETE FROM sessions WHERE id=? AND user_key=?",
                                (session_id, user_key))
            else:
                cur = c.execute("DELETE FROM sessions WHERE id=?",
                                (session_id,))
            return cur.rowcount > 0

    # -- reads --------------------------------------------------------------
    def get(self, session_id: str) -> dict[str, Any] | None:
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM sessions WHERE id=?",
                            (session_id,)).fetchone()
            return dict(row) if row else None

    def list_by_user(self, user_key: str, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent sessions for a user, bounded."""
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM sessions WHERE user_key=? "
                "ORDER BY updated_at DESC LIMIT ?", (user_key, int(limit))
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, user_key: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """FTS5 full-text search scoped to one user (no cross-user leak)."""
        terms = [re.sub(r"[^A-Za-z0-9_-]", "", w) for w in query.split()]
        terms = [t for t in terms if t]
        if not terms:
            return []
        match_expr = " OR ".join(f'"{t}"' for t in terms)
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT s.*, bm25(sessions_fts) AS rank "
                "FROM sessions_fts "
                "JOIN sessions s ON s.rowid = sessions_fts.rowid "
                "WHERE sessions_fts MATCH ? AND s.user_key=? "
                "ORDER BY rank LIMIT ?",
                (match_expr, user_key, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- recovery -----------------------------------------------------------
    def recover_interrupted(self) -> int:
        """Mark sessions left 'active' by a crashed process as 'interrupted'."""
        t = _now()
        with connect(self.path) as c:
            cur = c.execute(
                "UPDATE sessions SET status='interrupted', updated_at=? "
                "WHERE status='active'", (t,))
            return cur.rowcount

    def count(self) -> int:
        with connect(self.path) as c:
            return c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
