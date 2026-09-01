from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def _ids(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            result.add(int(item))
    return result


class TelegramConnector:
    """Telegram Bot API connector using long polling (no public port required)."""

    def __init__(self, agent, token: str | None = None, allowed_users: set[int] | None = None, transport=None):
        self.agent = agent
        self.token = (token or os.getenv("AIBA_TELEGRAM_BOT_TOKEN", "")).strip()
        self.allowed_users = allowed_users if allowed_users is not None else _ids(os.getenv("AIBA_TELEGRAM_ALLOWED_USERS", ""))
        if not self.token:
            raise ValueError("AIBA_TELEGRAM_BOT_TOKEN is required")
        if not self.allowed_users:
            raise ValueError("AIBA_TELEGRAM_ALLOWED_USERS must contain at least one numeric owner ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.transport = transport or self._request
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.offset = 0

    @classmethod
    def enabled(cls) -> bool:
        return os.getenv("AIBA_TELEGRAM_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _request(self, method: str, data: dict | None = None) -> dict:
        payload = urllib.parse.urlencode(data or {}).encode()
        request = urllib.request.Request(f"{self.base_url}/{method}", data=payload)
        with urllib.request.urlopen(request, timeout=40) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API rejected {method}")
        return body

    def send(self, chat_id: int, text: str) -> None:
        text = str(text) or "AIBA completed the request without a text response."
        for start in range(0, len(text), 4000):
            self.transport("sendMessage", {"chat_id": chat_id, "text": text[start:start + 4000]})

    def handle_update(self, update: dict) -> bool:
        message = update.get("message") or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        text = message.get("text")
        if not text or chat.get("type") != "private" or sender.get("id") not in self.allowed_users:
            return False
        chat_id = int(chat["id"])
        if text.strip() == "/start":
            answer = self.agent.start_conversation(f"telegram:{sender['id']}")
            self.send(chat_id, answer)
            return True
        try:
            answer = self.agent.handle(text.strip(), user_id=f"telegram:{sender['id']}", onboard=True)
        except Exception as exc:
            crash_id = self.agent.crashes.capture(exc, {"connector": "telegram"})
            answer = f"AIBA could not complete that request. Crash ID: {crash_id}"
        self.send(chat_id, answer)
        return True

    def poll_once(self) -> int:
        body = self.transport("getUpdates", {"timeout": 30, "offset": self.offset, "allowed_updates": json.dumps(["message"])})
        processed = 0
        for update in body.get("result", []):
            self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            processed += int(self.handle_update(update))
        return processed

    def run(self) -> None:
        delay = 1
        while not self.stop_event.is_set():
            try:
                self.poll_once()
                delay = 1
            except (OSError, RuntimeError, ValueError, urllib.error.URLError):
                if self.stop_event.wait(delay):
                    break
                delay = min(delay * 2, 30)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run, name="aiba-telegram", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
