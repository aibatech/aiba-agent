from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class ConversationReviewer:
    """Safe post-turn self-improvement review.

    Reviews completed turns without exposing private chain-of-thought or
    rewriting production source. Durable user facts remain the AutoLearner's
    responsibility; this reviewer records operational lessons and skill
    improvement signals for later inspection/promotion.
    """

    def __init__(self, review_dir: Path):
        self.review_dir = Path(review_dir)
        self.review_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _signals(user_text: str, answer: str, tools: list[str]) -> list[str]:
        low = (user_text or "").lower()
        signals: list[str] = []
        correction_cues = ("no,", "no ", "actually", "instead", "i meant", "that's wrong", "thats wrong", "don't ", "do not ")
        if any(cue in low for cue in correction_cues):
            signals.append("user_correction")
        if tools:
            signals.append("tool_work")
        if "failed" in (answer or "").lower() or "error" in (answer or "").lower():
            signals.append("execution_problem")
        return signals

    def review(self, task_id: str, conversation_id: str, user_text: str,
               answer: str, tools: list[str], status: str = "complete") -> dict:
        signals = self._signals(user_text, answer, tools)
        record = {
            "task_id": task_id,
            "conversation_id": conversation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "signals": signals,
            "tools": list(tools),
            "needs_review": bool(signals),
            "policy": {
                "source_rewrite_allowed": False,
                "private_chain_of_thought_stored": False,
                "user_memory_owned_by_auto_learner": True,
            },
        }
        day = record["created_at"][:10]
        path = self.review_dir / f"{day}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
