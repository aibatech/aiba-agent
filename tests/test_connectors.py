from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from connectors import TelegramConnector, WhatsAppConnector


class _Crashes:
    def capture(self, exc, context):
        return "crash-test"


class _Agent:
    def __init__(self):
        self.prompts = []
        self.crashes = _Crashes()

    def handle(self, prompt):
        self.prompts.append(prompt)
        return "answer: " + prompt


class TelegramTests(unittest.TestCase):
    def test_only_private_allowlisted_owner_can_run_agent(self):
        calls = []
        transport = lambda method, data=None: calls.append((method, data)) or {"ok": True, "result": []}
        agent = _Agent(); connector = TelegramConnector(agent, "token", {42}, transport)
        denied = {"message": {"from": {"id": 7}, "chat": {"id": 7, "type": "private"}, "text": "secret"}}
        allowed = {"message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "hello"}}
        self.assertFalse(connector.handle_update(denied));self.assertTrue(connector.handle_update(allowed))
        self.assertEqual(agent.prompts, ["hello"]);self.assertEqual(calls[-1][0], "sendMessage")

    def test_owner_allowlist_is_required(self):
        with self.assertRaises(ValueError):TelegramConnector(_Agent(), "token", set(), lambda *_: {})


class WhatsAppTests(unittest.TestCase):
    def connector(self, calls=None):
        calls = calls if calls is not None else []
        return WhatsAppConnector(_Agent(), "access", "phone-id", "verify", "secret", {"15551234567"}, lambda payload: calls.append(payload) or {})

    def test_webhook_verification_and_signature(self):
        connector = self.connector();body = b'{"object":"whatsapp_business_account"}'
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        self.assertEqual(connector.verify_webhook("subscribe", "verify", "123"), "123")
        self.assertIsNone(connector.verify_webhook("subscribe", "wrong", "123"))
        self.assertTrue(connector.valid_signature(body, signature));self.assertFalse(connector.valid_signature(body, "sha256=bad"))

    def test_allowlist_text_filter_and_duplicate_protection(self):
        connector = self.connector()
        def payload(sender, message_id, body="hello"):
            return {"entry": [{"changes": [{"value": {"messages": [{"from": sender, "id": message_id, "type": "text", "text": {"body": body}}]}}]}]}
        self.assertEqual(connector.extract_messages(payload("15550000000", "a")), [])
        self.assertEqual(connector.extract_messages(payload("15551234567", "b")), [("15551234567", "hello", "b")])
        self.assertEqual(connector.extract_messages(payload("15551234567", "b")), [])

    def test_processing_replies_through_cloud_api(self):
        calls=[];connector=self.connector(calls);connector.process("15551234567", "hello")
        self.assertEqual(calls[0]["to"], "15551234567");self.assertEqual(calls[0]["text"]["body"], "answer: hello")


if __name__ == "__main__":unittest.main()
