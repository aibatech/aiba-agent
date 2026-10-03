import threading
import unittest

from connectors.telegram import TelegramConnector
from tools.clarify import Clarify


class _Crashes:
    def capture(self, exc, context):
        return "test-crash"


class _Agent:
    def __init__(self):
        self.clarify = Clarify(blocking=False)
        self.crashes = _Crashes()
        self.calls = []
        try:
            self.clarify.ask("Pick one", [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}], blocking=False)
        except Exception:
            pass
        self.qid = self.clarify.pending_list()[0]["id"]

    def handle(self, text, **kwargs):
        self.calls.append(text)
        return "continued"


class TelegramClarifyCallbackTests(unittest.TestCase):
    def test_callback_is_acknowledged_keyboard_removed_and_choice_runs_once(self):
        agent = _Agent()
        calls = []
        def transport(method, data=None):
            calls.append((method, data or {}))
            return {"ok": True}
        connector = TelegramConnector(agent, token="token", allowed_users={7}, transport=transport)
        update = {"id": "cb1", "from": {"id": 7}, "message": {"message_id": 99, "chat": {"id": 7}}, "data": f"clar:{agent.qid}:a"}
        connector.handle_callback(update)
        connector.handle_callback({**update, "id": "cb2"})
        self.assertEqual(agent.calls, ["A"])
        self.assertEqual(calls[0][0], "answerCallbackQuery")
        self.assertTrue(any(method == "editMessageReplyMarkup" for method, _ in calls))

if __name__ == "__main__":
    unittest.main()
