"""Tests for Phase 10 Clarify tool."""
from __future__ import annotations

import time
import unittest

from tools.clarify import (
    ClarificationRequested,
    Clarify,
    ClarifyToolFactory,
    _normalise_options,
)
from tools.base import ToolResult


class _Policy:
    def check_tool(self, name):
        return type("D", (), {"allowed": True, "requires_approval": False, "reason": ""})()


class _Approvals:
    def approve(self, *a):
        return True


class _Audit:
    def record(self, *a, **k):
        pass


class _Registry:
    def __init__(self):
        from tools.registry import ToolRegistry
        self._r = ToolRegistry(_Audit(), _Approvals(), _Policy())

    def register(self, t):
        self._r.register(t)

    def schemas(self, excluded=None):
        return [s["name"] for s in self._r.schemas(excluded)]

    def execute(self, name, args, blocked=None):
        return self._r.execute(name, args, blocked)


class ClarifyUnitTests(unittest.TestCase):
    def test_answered_via_answer_source(self):
        c = Clarify(answer_source=lambda q: q.options[0]["id"], blocking=True, timeout=2)
        state, qid = c.ask("Which? ", [{"id": "yes", "text": "Yes", "tradeoff": "fast"}])
        self.assertEqual(state, "answered")
        self.assertTrue(c.get(qid).answer == "yes")

    def test_validates_choice_against_options(self):
        c = Clarify(answer_source=lambda q: q.answer_free("custom"), blocking=True, timeout=2)
        state, qid = c.ask("Pick", [{"id": "a", "text": "A"}])
        q = c.get(qid)
        self.assertEqual(state, "answered")
        self.assertEqual(q.answer, "custom")

    def test_async_answer_flow(self):
        c = Clarify(blocking=False)  # never blocks; raises ClarificationRequested
        with self.assertRaises(ClarificationRequested) as ctx:
            c.ask("Q", [{"id": "opt1", "text": "Opt 1"}] )
        qid = ctx.exception.question_id
        # connector renders buttons, user picks:
        self.assertTrue(c.answer(qid, "opt1"))
        self.assertEqual(c.get(qid).answer, "opt1")

    def test_unknown_question_id(self):
        c = Clarify()
        self.assertFalse(c.answer("nope", "x"))

    def test_pending_list(self):
        c = Clarify(blocking=False, timeout=0.0)
        try:
            c.ask("Q", [{"id": "a", "text": "A"}])
        except ClarificationRequested:
            pass
        pending = c.pending_list()
        self.assertEqual(len(pending), 1)
        self.assertFalse(pending[0]["answered"])

    def test_normalise_options_defaults(self):
        opts = _normalise_options([{"id": "1", "text": "One", "tradeoff": "t"}, {"text": "No id"}])
        self.assertEqual(opts[0]["id"], "1")
        self.assertEqual(opts[1]["id"], "No id")
        self.assertIn("No tradeoffs", opts[1]["tradeoff"])


class ClarifyToolTests(unittest.TestCase):
    def setUp(self):
        self.registry = _Registry()

    def _register(self, clarify):
        self.registry.register(ClarifyToolFactory.make(clarify))

    def test_tool_exposed_in_schemas(self):
        self._register(Clarify())
        self.assertIn("clarify", self.registry.schemas())

    def test_tool_returns_answered_choice(self):
        c = Clarify(answer_source=lambda q: q.options[0]["id"], blocking=True, timeout=2)
        self._register(c)
        res = self.registry.execute("clarify", {"question": "Go?", "options": [{"id": "y", "text": "Yes", "tradeoff": "fast"}]})
        self.assertTrue(res.ok)
        self.assertEqual(res.output["state"], "answered")
        self.assertEqual(res.output["answer"], "y")

    def test_tool_returns_pending_with_options_for_connector(self):
        c = Clarify(blocking=False, timeout=0.0)
        self._register(c)
        res = self.registry.execute("clarify", {"question": "Pick", "options": [{"id": "a", "text": "A", "tradeoff": "t"}]})
        self.assertTrue(res.ok)  # handled gracefully, not an error
        self.assertEqual(res.output["state"], "pending")
        self.assertEqual(res.output["options"][0]["id"], "a")


if __name__ == "__main__":
    unittest.main()
