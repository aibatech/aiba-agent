"""Durable, principal-bound one-use approval challenges for trusted bridges."""
from __future__ import annotations

import hashlib
import math
import secrets
import time
from pathlib import Path
from sqlite_utils import connect


class ApprovalStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with connect(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS approval_challenges (
                token_hash TEXT PRIMARY KEY, principal TEXT NOT NULL,
                fingerprint TEXT NOT NULL, expires REAL NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0)''')

    def issue(self, principal: str, fingerprint: str, ttl: float = 300) -> str:
        if not principal or not math.isfinite(ttl) or not 0 < ttl <= 3600:
            raise ValueError('A principal and finite approval lifetime are required')
        token = secrets.token_urlsafe(32)
        with connect(self.path) as db:
            db.execute('DELETE FROM approval_challenges WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO approval_challenges VALUES (?, ?, ?, ?, 0)',
                       (hashlib.sha256(token.encode()).hexdigest(), principal, fingerprint, time.time() + ttl))
        return token

    def consume(self, token: str, principal: str, fingerprint: str) -> bool:
        with connect(self.path) as db:
            result = db.execute('''UPDATE approval_challenges SET consumed=1
                WHERE token_hash=? AND principal=? AND fingerprint=?
                AND expires>? AND consumed=0''',
                (hashlib.sha256(token.encode()).hexdigest(), principal, fingerprint, time.time()))
            return result.rowcount == 1
