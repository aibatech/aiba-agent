"""Tests for Phase 2 visible-reasoning protocol."""
from __future__ import annotations

import unittest

from reasoning.protocol import (
    PROTOCOL,
    PROTOCOL_VERSION,
    K_TOOL,
    K_RESULT,
    K_FINAL,
    K_PLAN,
    VisibleReasoning,
    _sanitise,
    _clip,
)
from reasoning.engine import ReasoningEngine


class _Bus:
    """Captures every published event like EventBus.publish."""

    def __init__(self):
        self.events = []

    def publish(self, event_type, **payload):
        self.events.append((event_type, payload))


class _Retrieval:
    def retrieve(self, q, n):
        return []


class _Tasks:
    def __init__(self):
        self.events = []

    def event(self, task_id, payload):
        self.events.append(payload)


class _Provider:
    def __init__(self, actions):
        self._actions = actions
        self.last_route = None

    def complete(self, messages, schemas, **kw):
        return self._actions.pop(0) if self._actions else {"type": "final", "response": "done"}


class _Registry:
    def __init__(self):
        self.executed = []
        self._schemas = [{"name": "run_shell", "description": "d", "parameters": {}}]

    def schemas(self, blocked=None):
        return self._schemas

    def execute(self, name, args, blocked=None):
        self.executed.append((name, args))
        return type("R", (), {"ok": True, "output": {"ok": "fine"}, "error": None})


class VisibleReasoningTests(unittest.TestCase):
    def setUp(self):
        self.bus = _Bus()
        self.vr = VisibleReasoning(self.bus.publish, "task-1")

    def test_envelope_shape(self):
        self.vr.plan("do things")
        _, payload = self.bus.events[0]
        self.assertEqual(payload["protocol"], PROTOCOL)
        self.assertEqual(payload["version"], PROTOCOL_VERSION)
        self.assertEqual(payload["task_id"], "task-1")
        self.assertIn("timestamp", payload)
        self.assertEqual(payload["event"]["kind"], K_PLAN)
        self.assertEqual(payload["event"]["summary"], "do things")

    def test_fans_out_to_specific_and_wildcard(self):
        self.vr.tool("read_file")
        types = [t for t, _ in self.bus.events]
        self.assertIn("reasoning.tool", types)
        self.assertIn("reasoning.*", types)

    def test_tool_sanitises_secrets(self):
        self.vr.tool("http", {"url": "https://x", "api_key": "sk-live-secret", "cookie": "sid=1"})
        _, payload = self.bus.events[0]
        args = payload["event"]["arguments"]
        self.assertEqual(args["api_key"], "[redacted]")
        self.assertEqual(args["cookie"], "[redacted]")
        self.assertEqual(args["url"], "https://x")

    def test_result_clips_long_output(self):
        self.vr.result("run_shell", True, output_preview="y" * 500)
        _, payload = self.bus.events[0]
        preview = payload["event"]["output_preview"]
        self.assertTrue(preview.endswith("..."))
        self.assertLess(len(preview), 220)

    def test_all_event_kinds_accepted(self):
        for meth, kw in [
            ("plan", {"summary": "s"}),
            ("tool", {"name": "t", "arguments": {}}),
            ("result", {"tool": "t", "ok": True, "output_preview": "x"}),
            ("final", {"response_preview": "d", "tool_count": 1}),
            ("error", {"detail": "bad"}),
        ]:
            getattr(self.vr, meth)(**kw)
        # Collapse fan-out: each emit appears once on the wildcard channel and
        # once on the kind channel; take kinds from either.
        kinds = sorted(set(p["event"]["kind"] for _, p in self.bus.events if _ == "reasoning.*"))
        self.assertEqual(kinds, ["error", "final", "plan", "result", "tool"])

    def test_publish_failure_does_not_raise(self):
        def broken(_, **kw):
            raise RuntimeError("sink down")
        vr = VisibleReasoning(broken, "t")
        vr.plan("must not raise")  # no exception

    def test_sanitise_redacts_recursively(self):
        d = {"a": {"token": "x", "keep": "ok"}}
        s = _sanitise(d)
        self.assertEqual(s["a"]["token"], "[redacted]")
        self.assertEqual(s["a"]["keep"], "ok")

    def test_clip(self):
        self.assertEqual(_clip("abc", 5), "abc")
        self.assertEqual(_clip("abcdefgh", 5), "abcde...")


class EngineProtocolTests(unittest.TestCase):
    def test_engine_emits_plan_tool_result_final(self):
        bus = _Bus()
        vr = VisibleReasoning(bus.publish, "task-9")
        provider = _Provider([
            {"type": "tool_call", "tool": "run_shell", "arguments": {"command": "ls"}},
            {"type": "final", "response": "done"},
        ])
        registry = _Registry()
        engine = ReasoningEngine(provider, registry, _Retrieval(), _Tasks(), reasoning=vr)
        answer, used = engine.run("task-9", "list files")
        self.assertEqual(answer, "done")
        self.assertEqual(used, ["run_shell"])
        kinds = sorted(set(p["event"]["kind"] for _, p in bus.events if _ == "reasoning.*"))
        self.assertEqual(kinds, [K_FINAL, K_PLAN, K_RESULT, K_TOOL])

    def test_engine_emits_error_when_max_steps_exhausted(self):
        bus = _Bus()
        vr = VisibleReasoning(bus.publish, "task-9")
        # Provider that always returns a tool_call -> never final -> max reached.
        provider = _Provider([
            {"type": "tool_call", "tool": "run_shell", "arguments": {"command": "ls"}},
            {"type": "tool_call", "tool": "run_shell", "arguments": {"command": "ls"}},
        ])
        reg = _Registry()
        engine = ReasoningEngine(provider, reg, _Retrieval(), _Tasks(), max_steps=1, reasoning=vr)
        with self.assertRaises(RuntimeError):
            engine.run("task-9", "list files")
        kinds = [p["event"]["kind"] for _, p in bus.events]
        self.assertIn("error", kinds)


if __name__ == "__main__":
    unittest.main()
