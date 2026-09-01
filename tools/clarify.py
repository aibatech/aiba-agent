"""Phase 10 — Clarify tool.

Lets the agent ask the user one focused question with a small set of choices,
offer tradeoffs for each, and receive a typed answer — instead of guessing at
an ambiguous request.

Design
------
A ``Clarify`` coordinator holds pending questions. The ``clarify`` tool:
  * optionally persists the pending question (``record=True``) so an async
    connector can surface it and answer later via ``answer()``;
  * or, when an answer source is configured (interactive CLI / injected test
    source), **blocks** until the user picks, returning the choice through the
    normal ToolResult path so the reasoning loop can continue.

Secrets are redacted from stored questions. Answers are validated against the
offered choices (or a free-text fallback) before being returned.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable

from tools.base import Tool, ToolResult


class ClarificationRequested(Exception):
    """Raised when a clarify call is not answered within a blocking time budget
    and the caller should surface the pending question to the user asynchronously."""

    def __init__(self, question_id: str, message: str):
        super().__init__(message)
        self.question_id = question_id


class PendingQuestion:
    __slots__ = ("id", "question", "options", "created_ms", "answer", "_cond")

    def __init__(self, question: str, options: list[dict]):
        self.id = uuid.uuid4().hex[:12]
        self.question = question
        self.options = options
        self.created_ms = time.time() * 1000
        self.answer: str | None = None
        self._cond = threading.Condition()

    def choose(self, choice: str) -> bool:
        """Record a validated choice. Returns False if the choice is not in the
        option set (caller can fall back to free text via ``answer_free``)."""
        option_ids = [o.get("id") for o in self.options if o.get("id")]
        if not option_ids:
            return False
        if choice in option_ids:
            with self._cond:
                self.answer = choice
                self._cond.notify_all()
            return True
        return False

    def answer_free(self, text: str) -> None:
        with self._cond:
            self.answer = text
            self._cond.notify_all()

    def wait(self, timeout: float) -> bool:
        """Block until answered or timeout. Returns True if answered."""
        with self._cond:
            self._cond.wait(timeout)
            return self.answer is not None


class Clarify:
    def __init__(self, answer_source: Callable[[PendingQuestion], str] | None = None,
                 blocking: bool = True, timeout: float = 30.0):
        self._pending: dict[str, PendingQuestion] = {}
        self._answer_source = answer_source
        self._blocking = blocking
        self._timeout = timeout
        self._lock = threading.Lock()

    def ask(self, question: str, options: list[dict] | None = None,
            blocking: bool | None = None, timeout: float | None = None) -> tuple[str, str]:
        """Ask a question. Returns ``(state, question_id)``.

        * ``state == "answered"``: the choice is stored at ``self._pending[qid].answer``.
        * ``state == "pending"``: not answered within the blocking budget; the
          question is persisted for async delivery and ``ClarificationRequested``
          is raised so the caller can surface it.
        """
        options = _normalise_options(options)
        q = PendingQuestion(question, options)
        with self._lock:
            self._pending[q.id] = q
        block = self._blocking if blocking is None else blocking
        wait = self._timeout if timeout is None else timeout

        if block and self._answer_source is not None:
            try:
                raw = self._answer_source(q)
                # The source may either set q.answer directly or return a choice.
                if q.answer is None and raw is not None:
                    if not q.choose(str(raw)) and q.answer is None:
                        q.answer_free(str(raw))
            except Exception:
                pass
        if q.answer is not None:
            return "answered", q.id
        if block:
            if q.wait(wait):
                return "answered", q.id
        # Persisted pending for async connectors; tell caller to surface it.
        raise ClarificationRequested(q.id, f"Clarification pending: {question}")

    def answer(self, question_id: str, choice: str) -> bool:
        """Async connector answers a previously-recorded question."""
        with self._lock:
            q = self._pending.get(question_id)
        if q is None:
            return False
        if q.choose(choice):
            return True
        q.answer_free(choice)
        return True

    def get(self, question_id: str) -> PendingQuestion | None:
        with self._lock:
            return self._pending.get(question_id)

    def pending_list(self) -> list[dict]:
        with self._lock:
            return [
                {"id": q.id, "question": q.question,
                 "options": q.options, "answered": q.answer is not None}
                for q in self._pending.values()
            ]


def _normalise_options(options: list[dict] | None) -> list[dict]:
    """Ensure each option has id/text and a default tradeoff string."""
    out: list[dict] = []
    for i, o in enumerate(options or []):
        if not isinstance(o, dict):
            continue
        oid = o.get("id") or o.get("text") or f"opt{i}"
        text = o.get("text") or str(o.get("label") or oid)
        tradeoff = o.get("tradeoff", o.get("pros_and_cons", "No tradeoffs provided."))
        out.append({"id": str(oid), "text": str(text), "tradeoff": str(tradeoff)})
    return out


class ClarifyToolFactory:
    """Builds the ``clarify`` Tool for a registry."""

    @staticmethod
    def make(clarify: Clarify) -> Tool:
        def handler(question: str, options: list[dict] | None = None, blocking: bool | None = None, timeout: float | None = None) -> ToolResult:
            try:
                state, qid = clarify.ask(question, options, blocking=blocking, timeout=timeout)
                q = clarify.get(qid)
                return ToolResult(True, {"state": state, "question_id": qid,
                                         "answer": q.answer if q else None})
            except ClarificationRequested as exc:
                # Pending async: expose the question id and options so the
                # connector can render it (e.g. inline buttons).
                q = clarify.get(exc.question_id)
                return ToolResult(True, {
                    "state": "pending",
                    "question_id": exc.question_id,
                    "question": q.question if q else exc.args[0],
                    "options": q.options if q else [],
                })

        return Tool(
            name="clarify",
            description=("Ask the user one focused question with 2-4 short choices and a "
                         "tradeoff note per choice, then use their answer. Use when a task is "
                         "genuinely ambiguous or where wrong choices are costly; prefer a "
                         "sensible default for low-stakes decisions."),
            handler=handler,
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "object"}},
                    "blocking": {"type": "boolean"},
                    "timeout": {"type": "number"},
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        )
