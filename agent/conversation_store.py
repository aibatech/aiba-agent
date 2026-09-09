from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Any

from sqlite_utils import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_conversation_id(user_key: str) -> str:
    """Stable private conversation id for CLI/connectors when no chat id is supplied."""
    digest = hashlib.sha256(("aiba-conversation:" + (user_key or "default")).encode("utf-8")).hexdigest()[:24]
    return f"default-{digest}"


class ConversationStore:
    """Durable, user-scoped multi-turn conversation history.

    This store is intentionally separate from SessionStore. SessionStore is an
    audit/search summary of completed turns; ConversationStore contains the
    bounded recent dialogue needed to hold a coherent long conversation.
    """

    def __init__(self, path):
        self.path = path
        self._init()

    def _init(self) -> None:
        with connect(self.path) as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations(
                  id TEXT NOT NULL,
                  user_key TEXT NOT NULL,
                  title TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(id, user_key)
                );
                CREATE TABLE IF NOT EXISTS conversation_messages(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id TEXT NOT NULL,
                  user_key TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                  content TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversation_messages_lookup
                  ON conversation_messages(user_key, conversation_id, id DESC);
                """
            )

    def ensure(self, user_key: str, conversation_id: str | None = None, title: str = "") -> str:
        cid = (conversation_id or default_conversation_id(user_key)).strip()
        if not cid:
            cid = default_conversation_id(user_key)
        now = _now()
        with connect(self.path) as c:
            c.execute(
                "INSERT OR IGNORE INTO conversations(id,user_key,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (cid, user_key, title[:160], now, now),
            )
            c.execute(
                "UPDATE conversations SET updated_at=? WHERE id=? AND user_key=?",
                (now, cid, user_key),
            )
        return cid

    def append(self, user_key: str, conversation_id: str, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Conversation role must be user or assistant")
        text = (content or "").strip()
        if not text:
            return
        now = _now()
        with connect(self.path) as c:
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,user_key,role,content,created_at) VALUES(?,?,?,?,?)",
                (conversation_id, user_key, role, text, now),
            )
            c.execute(
                "UPDATE conversations SET updated_at=? WHERE id=? AND user_key=?",
                (now, conversation_id, user_key),
            )

    def recent(self, user_key: str, conversation_id: str, limit: int = 24,
               char_budget: int = 16000) -> list[dict[str, str]]:
        """Return recent turns oldest->newest, bounded by count and characters."""
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT role,content FROM conversation_messages "
                "WHERE user_key=? AND conversation_id=? ORDER BY id DESC LIMIT ?",
                (user_key, conversation_id, max(1, int(limit))),
            ).fetchall()
        selected: list[dict[str, str]] = []
        used = 0
        for row in rows:
            text = str(row["content"])
            cost = len(text)
            if selected and used + cost > int(char_budget):
                break
            if cost > int(char_budget):
                text = text[-int(char_budget):]
                cost = len(text)
            selected.append({"role": str(row["role"]), "content": text})
            used += cost
        selected.reverse()
        return selected

    def list_by_user(self, user_key: str, limit: int = 50) -> list[dict[str, Any]]:
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM conversations WHERE user_key=? ORDER BY updated_at DESC LIMIT ?",
                (user_key, max(1, int(limit))),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear(self, user_key: str, conversation_id: str) -> bool:
        with connect(self.path) as c:
            c.execute(
                "DELETE FROM conversation_messages WHERE user_key=? AND conversation_id=?",
                (user_key, conversation_id),
            )
            cur = c.execute(
                "DELETE FROM conversations WHERE user_key=? AND id=?",
                (user_key, conversation_id),
            )
            return cur.rowcount > 0
