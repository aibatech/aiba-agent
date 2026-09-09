from __future__ import annotations

import re
from typing import Iterable


class AutoLearner:
    """Conservative automatic durable-memory learner.

    AIBA should improve from repeated use without stuffing every turn into the
    durable vault. This learner stores only high-signal user-authored facts,
    preferences, goals, decisions, and standing instructions. Conversation
    continuity itself lives in ConversationStore.
    """

    _CUES: tuple[tuple[str, str, float], ...] = (
        (r"\b(?:i prefer|i like|i love|i hate|i don't like|i do not like)\b", "preference", 0.82),
        (r"\b(?:my goal is|my main goal is|i want to|i'm trying to|i am trying to)\b", "goal", 0.80),
        (r"\b(?:remember that|remember this|keep in mind)\b", "explicit", 0.92),
        (r"\b(?:from now on|always |never |don't ever|do not ever)\b", "instruction", 0.90),
        (r"\b(?:we decided|we agreed|let's use|lets use|we're going with|we are going with)\b", "decision", 0.86),
        (r"\b(?:my business|my company|i run|i own|i work at|i work for)\b", "context", 0.76),
    )

    def __init__(self, vault):
        self.vault = vault

    @staticmethod
    def _sentences(text: str) -> Iterable[str]:
        for raw in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
            sentence = re.sub(r"\s+", " ", raw).strip()
            if 8 <= len(sentence) <= 700:
                yield sentence

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\W+", " ", text.lower()).strip()

    def _already_known(self, content: str, as_user=None) -> bool:
        words = [w for w in re.findall(r"[A-Za-z0-9_-]+", content) if len(w) > 2]
        if not words:
            return False
        query = " ".join(words[:12])
        try:
            rows = self.vault.search(query, limit=8, as_user=as_user)
        except Exception:
            return False
        target = self._normalize(content)
        for row in rows:
            existing = self._normalize(str(row.get("content", "")))
            if existing == target:
                return True
            # Strong near-duplicate guard for repeated standing facts.
            a, b = set(target.split()), set(existing.split())
            if a and b and len(a & b) / max(1, min(len(a), len(b))) >= 0.85:
                return True
        return False

    def learn(self, user_text: str, owner: str, as_user=None,
              source: str = "conversation") -> list[int]:
        learned: list[int] = []
        for sentence in self._sentences(user_text):
            low = sentence.lower()
            match = next(((cat, importance) for pattern, cat, importance in self._CUES
                          if re.search(pattern, low)), None)
            if not match:
                continue
            category, importance = match
            if self._already_known(sentence, as_user=as_user):
                continue
            try:
                mid = self.vault.add(
                    sentence,
                    category=f"learned/{category}",
                    importance=importance,
                    metadata={"auto_learned": True, "source": source},
                    owner=owner,
                )
                learned.append(int(mid))
            except Exception:
                # Learning is best-effort and must never break the user's turn.
                continue
        return learned
