from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from connectors.ux.render import TYPING_INTERVAL_SECONDS, InlineKeyboard, InlineKey, TypingSender, prepare_message


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
        self._typing_threads: dict[int, threading.Thread] = {}
        self._last_hb: dict[int, float] = {}
        self._hb_lock = threading.Lock()

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
        rendered = prepare_message(text)
        for i, chunk in enumerate(rendered.sends):
            data = {"chat_id": chat_id, "text": chunk}
            if i == 0 and rendered.reply_markup is not None:
                data["reply_markup"] = json.dumps(rendered.reply_markup)
            self.transport("sendMessage", data)

    def send_keyboard(self, chat_id: int, text: str, keyboard: InlineKeyboard) -> None:
        """Send text with an inline keyboard attached to the first chunk."""
        rendered = prepare_message(text, keyboard=keyboard)
        self.send_payload(chat_id, rendered)

    def send_payload(self, chat_id: int, rendered) -> None:
        for i, chunk in enumerate(rendered.sends):
            data = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if i == 0 and rendered.reply_markup is not None:
                data["reply_markup"] = json.dumps(rendered.reply_markup)
            self.transport("sendMessage", data)

    def _start_typing(self, chat_id: int) -> None:
        """Begin a typing heartbeat for a chat. Starts a single daemon thread
        per chat that refreshes sendChatAction until the task completes."""
        with self._hb_lock:
            if chat_id in self._typing_threads:
                return
            sender = TypingSender(self.transport, chat_id)
            stop = threading.Event()
            self._typing_stops = getattr(self, "_typing_stops", {})
            self._typing_stops[chat_id] = stop

            def beat():
                try:
                    while not stop.is_set():
                        sender.heartbeat()
                        time.sleep(TYPING_INTERVAL_SECONDS)
                except Exception:
                    pass
                finally:
                    with self._hb_lock:
                        self._typing_threads.pop(chat_id, None)

            t = threading.Thread(target=beat, name=f"aiba-typing-{chat_id}", daemon=True)
            self._typing_threads[chat_id] = t
            t.start()

    def _stop_typing(self, chat_id: int) -> None:
        with self._hb_lock:
            stop = getattr(self, "_typing_stops", {}).pop(chat_id, None)
            self._typing_threads.pop(chat_id, None)
        if stop:
            stop.set()

    def handle_update(self, update: dict) -> bool:
        if "callback_query" in update:
            self.handle_callback(update["callback_query"])
            return True
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
            self._start_typing(chat_id)
            answer = self.agent.handle(text.strip(), user_id=f"telegram:{sender['id']}", onboard=True)
        except Exception as exc:
            crash_id = self.agent.crashes.capture(exc, {"connector": "telegram"})
            answer = f"AIBA could not complete that request. Crash ID: {crash_id}"
        finally:
            self._stop_typing(chat_id)
        self.send(chat_id, answer)
        return True

    def poll_once(self) -> int:
        body = self.transport("getUpdates", {"timeout": 30, "offset": self.offset, "allowed_updates": json.dumps(["message", "callback_query"])})
        processed = 0
        for update in body.get("result", []):
            self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            processed += int(self.handle_update(update))
        return processed

    def handle_callback(self, callback_query: dict) -> str | None:
        """Handle an inline-button callback. ``callback_query`` carries
        ``data`` and the ``message``/``from`` that produced it.

        The default implementation formats the press back to the owner so the
        connector is a safe, observable place to wire real workflows. Subclass
        or monkeypatch ``on_callback`` to make buttons do real work.
        """
        data = callback_query.get("data") or ""
        user = (callback_query.get("from") or {}).get("id")
        chat_id = ((callback_query.get("message") or {}).get("chat") or {}).get("id")
        if user not in self.allowed_users or not chat_id:
            return None
        answer = self.on_callback(int(chat_id), data)
        if answer is not None:
            try:
                self.transport("answerCallbackQuery", {"callback_query_id": callback_query.get("id", ""), "text": answer})
            except Exception:
                pass
        else:
            try:
                self.transport("answerCallbackQuery", {"callback_query_id": callback_query.get("id", "")})
            except Exception:
                pass
        return data

    def on_callback(self, chat_id: int, data: str) -> str | None:
        """Extensible callback handler. Recognises ``clar:<qid>:<choice>`` and,
        when it matches a pending clarify question, records the choice on the
        agent so a blocked/in-flight task can resume. Returns a toast string for
        answerCallbackQuery, or None to just accept the press."""
        if data.startswith("clar:") and getattr(self.agent, "clarify", None) is not None:
            parts = data.split(":", 2)
            if len(parts) == 3:
                _, qid, choice = parts
                try:
                    if self.agent.clarify.answer(qid, choice):
                        return "Got it."
                except Exception:
                    return None
        return f"AIBA noted: {data[:80]}"

    def _render_clarify(self, chat_id: int, question_id: str, question: str, options: list) -> None:
        """Render a pending clarify question as an inline keyboard. Each option
        becomes a button carrying ``clar:<qid>:<choice>`` callback data."""
        from connectors.ux.render import InlineKey, InlineKeyboard

        qid = question_id or ""
        keys = []
        for opt in options or []:
            oid = opt.get("id") if isinstance(opt, dict) else str(opt)
            text = opt.get("text") if isinstance(opt, dict) else str(opt)
            if not oid:
                continue
            keys.append([InlineKey(text=str(text), callback_data=f"clar:{qid}:{oid}")])
        if not keys:
            return
        kb = InlineKeyboard(keys)
        try:
            self.send_keyboard(chat_id, question, kb)
        except Exception:
            pass

    def connect_clarify(self) -> None:
        """Subscribe the connector to the agent's ``clarify.pending`` bus events
        so inline questions are rendered as buttons in this chat (if the owner's
        chat is known). Cheap and safe: only listeners, never sends unless a
        question is actually pending."""
        events = getattr(self.agent, "events", None)
        if events is None:
            return

        def handler(event):
            if not event:
                return
            owner_id = next(iter(self.allowed_users), None)
            if owner_id is None:
                return
            self._render_clarify(
                int(owner_id),
                event.get("question_id", ""),
                event.get("question", ""),
                event.get("options", []),
            )

        try:
            events.subscribe("clarify.pending", handler)
        except Exception:
            pass

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
        self.connect_clarify()
        self.thread = threading.Thread(target=self.run, name="aiba-telegram", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
