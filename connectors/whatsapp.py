from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import urllib.request
from collections import deque


def _phones(value: str) -> set[str]:
    return {re.sub(r"\D", "", item) for item in value.split(",") if re.sub(r"\D", "", item)}


class WhatsAppConnector:
    """Meta WhatsApp Cloud API webhook and outbound message adapter."""

    def __init__(self, agent, access_token: str | None = None, phone_number_id: str | None = None,
                 verify_token: str | None = None, app_secret: str | None = None,
                 allowed_numbers: set[str] | None = None, transport=None):
        self.agent = agent
        self.access_token = (access_token or os.getenv("AIBA_WHATSAPP_ACCESS_TOKEN", "")).strip()
        self.phone_number_id = (phone_number_id or os.getenv("AIBA_WHATSAPP_PHONE_NUMBER_ID", "")).strip()
        self.verify_token = (verify_token or os.getenv("AIBA_WHATSAPP_VERIFY_TOKEN", "")).strip()
        self.app_secret = (app_secret or os.getenv("AIBA_WHATSAPP_APP_SECRET", "")).strip()
        self.allowed_numbers = allowed_numbers if allowed_numbers is not None else _phones(os.getenv("AIBA_WHATSAPP_ALLOWED_NUMBERS", ""))
        self.graph_version = os.getenv("AIBA_WHATSAPP_GRAPH_VERSION", "v23.0").strip()
        missing = [name for name, value in {
            "AIBA_WHATSAPP_ACCESS_TOKEN": self.access_token,
            "AIBA_WHATSAPP_PHONE_NUMBER_ID": self.phone_number_id,
            "AIBA_WHATSAPP_VERIFY_TOKEN": self.verify_token,
            "AIBA_WHATSAPP_APP_SECRET": self.app_secret,
            "AIBA_WHATSAPP_ALLOWED_NUMBERS": self.allowed_numbers,
        }.items() if not value]
        if missing:
            raise ValueError("Missing WhatsApp configuration: " + ", ".join(missing))
        self.transport = transport or self._request
        self._seen = set()
        self._seen_order: deque[str] = deque()
        self._seen_lock = threading.Lock()

    @classmethod
    def enabled(cls) -> bool:
        return os.getenv("AIBA_WHATSAPP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        if mode == "subscribe" and hmac.compare_digest(token or "", self.verify_token):
            return challenge
        return None

    def valid_signature(self, body: bytes, signature: str | None) -> bool:
        if not signature or not signature.startswith("sha256="):
            return False
        expected = hmac.new(self.app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], expected)

    def _request(self, payload: dict) -> dict:
        url = f"https://graph.facebook.com/{self.graph_version}/{self.phone_number_id}/messages"
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
            "Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def send(self, recipient: str, text: str) -> None:
        text = str(text) or "AIBA completed the request without a text response."
        for start in range(0, len(text), 4000):
            self.transport({"messaging_product": "whatsapp", "to": recipient, "type": "text",
                            "text": {"preview_url": False, "body": text[start:start + 4000]}})

    def _new_message(self, message_id: str) -> bool:
        with self._seen_lock:
            if message_id in self._seen:
                return False
            self._seen.add(message_id); self._seen_order.append(message_id)
            while len(self._seen_order) > 1000:
                self._seen.discard(self._seen_order.popleft())
            return True

    def extract_messages(self, payload: dict) -> list[tuple[str, str, str]]:
        found = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    sender = re.sub(r"\D", "", str(message.get("from", "")))
                    text = (message.get("text") or {}).get("body")
                    message_id = str(message.get("id", ""))
                    if sender in self.allowed_numbers and text and message_id and self._new_message(message_id):
                        found.append((sender, text.strip(), message_id))
        return found

    def process(self, sender: str, text: str) -> None:
        try:
            answer = self.agent.handle(text, user_id=f"whatsapp:{sender}", onboard=True)
        except Exception as exc:
            crash_id = self.agent.crashes.capture(exc, {"connector": "whatsapp"})
            answer = f"AIBA could not complete that request. Crash ID: {crash_id}"
        self.send(sender, answer)
