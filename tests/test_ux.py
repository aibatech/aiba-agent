"""Tests for Phase 1 Telegram UX: rendering, inline keyboards, typing heartbeat."""
from __future__ import annotations

import json
import threading
import time
import unittest

from connectors.ux.render import (
    MAX_MESSAGE_LENGTH,
    InlineKey,
    InlineKeyboard,
    TypingSender,
    _chunks,
    prepare_message,
    render_markdown,
    stable_callback,
)
from connectors import TelegramConnector


class RendererTests(unittest.TestCase):
    def test_chunks_split_long_messages(self):
        text = "x" * (MAX_MESSAGE_LENGTH * 2 + 50)
        chunks = _chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= MAX_MESSAGE_LENGTH for c in chunks))

    def test_chunks_preserve_paragraph_boundaries(self):
        para = "word " * 100  # ~500 chars
        text = "\n".join([para, para, para])
        chunks = _chunks(text)
        self.assertEqual("\n".join(chunks), text)

    def test_markdown_bold_and_escape(self):
        parse_mode, markup = render_markdown("Use **bold** and `code` plus <raw>&")
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("<b>bold</b>", markup)
        self.assertIn("<code>code</code>", markup)
        self.assertIn("&amp;", markup)

    def test_stable_callback_is_deterministic_and_capped(self):
        a = stable_callback("ns", "payload-here")
        b = stable_callback("ns", "payload-here")
        self.assertEqual(a, b)
        self.assertLessEqual(len(a), 60)

    def test_keyboard_builds_markup(self):
        kb = InlineKeyboard([[InlineKey("Yes", "cb:yes"), InlineKey("No", "cb:no", url="https://e.com")]])
        m = kb.markup()
        self.assertEqual(m["inline_keyboard"][0][0], {"text": "Yes", "callback_data": "cb:yes"})
        self.assertEqual(m["inline_keyboard"][0][1], {"text": "No", "url": "https://e.com"})

    def test_prepare_message_attaches_keyboard_to_first_chunk(self):
        kb = InlineKeyboard([[InlineKey("Run", "run:1")]])
        rendered = prepare_message("Heads up", keyboard=kb)
        self.assertIsNotNone(rendered.reply_markup)
        self.assertGreaterEqual(len(rendered.sends), 1)


class TypingSenderTests(unittest.TestCase):
    def _transport(self, calls):
        def t(method, data=None):
            calls.append((method, data))
            return {"ok": True, "result": []}
        return t

    def test_heartbeat_throttles_to_interval(self):
        calls = []
        sender = TypingSender(self._transport(calls), 42)
        sender.heartbeat()
        sender.heartbeat()
        self.assertEqual(sum(1 for m, _ in calls if m == "sendChatAction"), 1)

    def test_heartbeat_swallows_transport_errors(self):
        calls = []
        def transport(method, data=None):
            calls.append(method)
            raise RuntimeError("network down")
        sender = TypingSender(transport, 42)
        sender.heartbeat()  # must not raise
        self.assertIn("sendChatAction", calls)

    def test_send_markup_first_chunk_carries_keyboard(self):
        calls = []
        kb = InlineKeyboard([[InlineKey("Go", "go")]])
        rendered = prepare_message("hi", keyboard=kb)
        TypingSender(self._transport(calls), 42).send_markup(rendered)
        sent = [d for m, d in calls if m == "sendMessage"]
        self.assertEqual(sent[0]["parse_mode"], "HTML")
        self.assertIn("inline_keyboard", sent[0]["reply_markup"])


class _Crashes:
    def capture(self, exc, context):
        return "crash-test"


class _Personal:
    def intercept(self, user_id, text):
        return None


class _ClarifyStore:
    """Doubles tools.clarify.Clarify with just answer() for connector tests."""
    def __init__(self):
        self.answered = []

    def answer(self, question_id, choice):
        self.answered.append((question_id, choice))
        return True


class _FakeBus:
    """Minimal EventBus-compatible double shared by connector tests."""
    def __init__(self):
        self.handlers = []

    def subscribe(self, t, h):
        self.handlers.append(h)

    def publish(self, t, **kw):
        ev = {"type": t, **kw}
        for h in self.handlers:
            h(ev)


class _Agent:
    def __init__(self, clarify=None):
        self.prompts = []
        self.crashes = _Crashes()
        self.personal = _Personal()
        self.clarify = clarify if clarify is not None else _ClarifyStore()
        self.events = _FakeBus()

    def handle(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "answer: " + prompt

    def start_conversation(self, user_id):
        return f"Hey, I'm AIBA. What should I call you? (starting {user_id})"


class TelegramUxTests(unittest.TestCase):
    def _conn(self, calls):
        transport = lambda m, d=None: calls.append((m, d)) or {"ok": True, "result": []}
        return TelegramConnector(_Agent(), "token", {42}, transport)

    def test_callback_routed_for_owner(self):
        calls = []
        c = self._conn(calls)
        update = {"update_id": 1, "callback_query": {
            "id": "q1", "from": {"id": 42},
            "message": {"chat": {"id": 99, "type": "private"}},
            "data": "do:thing",
        }}
        self.assertTrue(c.handle_update(update))
        self.assertTrue(any(m == "answerCallbackQuery" for m, _ in calls))

    def test_callback_ignored_for_non_owner(self):
        calls = []
        c = self._conn(calls)
        update = {"callback_query": {
            "id": "q1", "from": {"id": 7},
            "message": {"chat": {"id": 99}},
            "data": "do:thing",
        }}
        self.assertTrue(c.handle_update(update))
        self.assertEqual([m for m, _ in calls if m == "answerCallbackQuery"], [])

    def test_typing_heartbeat_starts_and_stops(self):
        calls = []
        c = self._conn(calls)
        original = _Agent.handle
        _Agent.handle = lambda self, prompt, **kw: time.sleep(0.2) or ("answer: " + prompt)
        try:
            update = {"message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "hello"}}
            c.handle_update(update)
        finally:
            _Agent.handle = original
        self.assertTrue(any(m == "sendChatAction" for m, _ in calls))
        self.assertTrue(any(m == "sendMessage" for m, _ in calls))
        self.assertEqual(c._typing_threads, {})  # cleaned up after task

    def test_send_handles_unicode_and_long(self):
        calls = []
        c = self._conn(calls)
        c.send(42, "héllo " + "字" * 9000)
        sent = [d for m, d in calls if m == "sendMessage"]
        self.assertTrue(all(len(d["text"]) <= 4000 for d in sent))
        self.assertGreater(len(sent), 1)

    def test_clarify_callback_answers_pending_question(self):
        calls = []
        store = _ClarifyStore()
        transport = lambda m, d=None: calls.append((m, d)) or {"ok": True, "result": []}
        c = TelegramConnector(_Agent(clarify=store), "token", {42}, transport)
        update = {"callback_query": {
            "id": "q1", "from": {"id": 42},
            "message": {"chat": {"id": 42}},
            "data": "clar:abc123:opt2",
        }}
        self.assertTrue(c.handle_update(update))
        self.assertEqual(store.answered, [("abc123", "opt2")])

    def test_clarify_callback_renders_buttons(self):
        calls = []
        c = self._conn(calls)
        c._render_clarify(42, "qid9", "Which option?", [{"id": "a", "text": "Alpha"}, {"id": "b", "text": "Beta"}])
        sent = [d for m, d in calls if m == "sendMessage"]
        self.assertEqual(len(sent), 1)
        markup = json.loads(sent[0]["reply_markup"])
        rows = markup["inline_keyboard"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0]["callback_data"], "clar:qid9:a")
        self.assertEqual(rows[1][0]["callback_data"], "clar:qid9:b")

    def test_connect_clarify_subscribes_and_renders(self):
        calls = []
        bus = _FakeBus()
        agent = _Agent()
        agent.events = bus
        transport = lambda m, d=None: calls.append((m, d)) or {"ok": True, "result": []}
        c = TelegramConnector(agent, "token", {42}, transport)
        c.connect_clarify()
        bus.publish("clarify.pending", question_id="q1", question="Pick", options=[{"id": "x", "text": "X"}])
        sent = [d for m, d in calls if m == "sendMessage"]
        self.assertEqual(len(sent), 1)
        self.assertIn("inline_keyboard", sent[0]["reply_markup"])


if __name__ == "__main__":
    unittest.main()
