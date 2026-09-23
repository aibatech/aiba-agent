from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperatorRuntime:
    """Durable control plane for long-running AIBA work.

    This store is deliberately model-independent. It records task lifecycle,
    safe high-level activity, steering messages, checkpoints, verification and
    cancellation so UI/voice/connectors can observe and control work without
    exposing private chain-of-thought.
    """

    TERMINAL = {"complete", "failed", "cancelled"}

    def __init__(self, path: Path, events=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events
        self._init()

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS operator_tasks(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, instruction TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              result TEXT, last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS operator_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              kind TEXT NOT NULL, message TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_operator_events_task ON operator_events(task_id,id);
            CREATE TABLE IF NOT EXISTS operator_inbox(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              message TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operator_verifications(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              claim TEXT NOT NULL, evidence TEXT NOT NULL, passed INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            """)

    def create(self, instruction: str, owner: str = "default") -> str:
        task_id = str(uuid.uuid4()); t = _now()
        with self._connect() as c:
            c.execute("INSERT INTO operator_tasks VALUES(?,?,?,?,?,?,?,?)",
                      (task_id, owner, instruction, "queued", t, t, None, None))
        self.activity(task_id, "queued", "Task queued")
        return task_id

    def activity(self, task_id: str, kind: str, message: str, **data: Any) -> None:
        safe = str(message or "")[:500]
        with self._connect() as c:
            c.execute("INSERT INTO operator_events(task_id,kind,message,data,created_at) VALUES(?,?,?,?,?)",
                      (task_id, str(kind)[:80], safe, json.dumps(data, default=str)[:4000], _now()))
        if self.events:
            try:
                self.events.publish("operator.activity", task_id=task_id, kind=kind, message=safe, data=data)
            except Exception:
                pass

    def set_status(self, task_id: str, status: str, result: str | None = None,
                   error: str | None = None) -> None:
        if status not in {"queued","running","waiting_approval","paused","complete","failed","cancelled"}:
            raise ValueError("invalid operator task status")
        with self._connect() as c:
            cur = c.execute("SELECT status FROM operator_tasks WHERE id=?", (task_id,)).fetchone()
            if not cur:
                raise KeyError(task_id)
            if cur["status"] in self.TERMINAL and status != cur["status"]:
                raise ValueError("terminal task cannot transition")
            c.execute("UPDATE operator_tasks SET status=?,result=?,last_error=?,updated_at=? WHERE id=?",
                      (status, result, error, _now(), task_id))
        self.activity(task_id, "status", status)

    def steer(self, task_id: str, message: str) -> int:
        if not str(message).strip():
            raise ValueError("steering message cannot be empty")
        with self._connect() as c:
            row = c.execute("SELECT status FROM operator_tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["status"] in self.TERMINAL:
                raise ValueError("task is not active")
            cur = c.execute("INSERT INTO operator_inbox(task_id,message,created_at) VALUES(?,?,?)",
                            (task_id, str(message).strip()[:10000], _now()))
            ident = int(cur.lastrowid)
        self.activity(task_id, "steer", "New user direction received")
        return ident

    def consume_steering(self, task_id: str) -> list[str]:
        with self._connect() as c:
            rows = c.execute("SELECT id,message FROM operator_inbox WHERE task_id=? AND consumed=0 ORDER BY id",
                             (task_id,)).fetchall()
            if rows:
                c.executemany("UPDATE operator_inbox SET consumed=1 WHERE id=?", [(r["id"],) for r in rows])
        return [str(r["message"]) for r in rows]

    def cancel(self, task_id: str) -> None:
        self.set_status(task_id, "cancelled")

    def verify(self, task_id: str, claim: str, evidence: str, passed: bool) -> dict:
        if not claim.strip() or not evidence.strip():
            raise ValueError("verification requires claim and evidence")
        with self._connect() as c:
            c.execute("INSERT INTO operator_verifications(task_id,claim,evidence,passed,created_at) VALUES(?,?,?,?,?)",
                      (task_id, claim[:1000], evidence[:4000], int(bool(passed)), _now()))
        self.activity(task_id, "verification", "Verification passed" if passed else "Verification failed",
                      claim=claim[:300], passed=bool(passed))
        return {"claim": claim, "evidence": evidence, "passed": bool(passed)}

    def status(self, task_id: str, owner: str | None = None) -> dict:
        with self._connect() as c:
            if owner is None:
                row = c.execute("SELECT * FROM operator_tasks WHERE id=?", (task_id,)).fetchone()
            else:
                row = c.execute("SELECT * FROM operator_tasks WHERE id=? AND owner=?", (task_id, owner)).fetchone()
            if not row:
                raise KeyError(task_id)
            events = c.execute("SELECT kind,message,data,created_at FROM operator_events WHERE task_id=? ORDER BY id DESC LIMIT 50",
                               (task_id,)).fetchall()
            checks = c.execute("SELECT claim,evidence,passed,created_at FROM operator_verifications WHERE task_id=? ORDER BY id",
                               (task_id,)).fetchall()
        out = dict(row)
        out["events"] = [dict(x) for x in reversed(events)]
        out["verifications"] = [{**dict(x), "passed": bool(x["passed"])} for x in checks]
        return out
