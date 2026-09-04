"""Telegram UX: rendering, inline keyboards, and chunk-aware senders.

Kept dependency-free (stdlib only) so it can be unit-tested without the
Telegram network. The connector passes its own ``transport`` callable in,
so these helpers stay pure and verifiable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable

# Real message limit for Telegram sendMessage/editMessageText is 4096.
MAX_MESSAGE_LENGTH = 4000
# sendChatAction notifications last about 5 seconds, so refresh every ~4s.
TYPING_INTERVAL_SECONDS = 4.0


@dataclass(frozen=True)
class InlineKey:
    """A single button rendered as an inline keyboard row/button."""

    text: str
    callback_data: str
    url: str | None = None

    def build(self) -> dict:
        if self.url:
            return {"text": self.text, "url": self.url}
        return {"text": self.text, "callback_data": self.callback_data}


class InlineKeyboard:
    """Builds an ``InlineKeyboardMarkup`` from a list of rows of keys."""

    def __init__(self, rows: list[list[InlineKey]]):
        self.rows = rows

    def markup(self) -> dict:
        return {
            "inline_keyboard": [[k.build() for k in row] for row in self.rows],
        }


def _chunks(text: str) -> list[str]:
    """Split a message into <=MAX_MESSAGE_LENGTH chunks on paragraph/newline
    boundaries so Telegram never rejects an over-long message."""
    text = str(text)
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in text.split("\n"):
        block_len = len(block) + 1
        if current and current_len + block_len > MAX_MESSAGE_LENGTH:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        # A single block longer than the cap must still be delivered.
        while block_len > MAX_MESSAGE_LENGTH:
            chunks.append(block[:MAX_MESSAGE_LENGTH])
            block = block[MAX_MESSAGE_LENGTH:]
            block_len = len(block) + 1
        current.append(block)
        current_len += block_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def render_markdown(text: str) -> tuple[str, str]:
    """Render AIBA plain text as Telegram *Markdown* markup.

    Returns ``(parse_mode, markup)``. A conservative renderer: only wraps
    explicit markdown the server already trusts (bold, italic, code) and
    escapes the rest so a single stray ``_`` cannot corrupt the whole message.
    """
    if not text:
        return "HTML", ""
    import re

    safe = (
        re.sub(r"&", "&amp;", text)
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # Bold **, italic *, inline code `. Keep it minimal and idempotent.
    markup = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    markup = re.sub(r"`([^`]+)`", r"<code>\1</code>", markup)
    return "HTML", markup


@dataclass
class Rendered:
    """A fully prepared Telegram send.

    ``sends`` are the (possibly several) message chunks ready to send.
    ``reply_markup`` is keyboard JSON for the first chunk, or None.
    """

    sends: list[str] = field(default_factory=list)
    reply_markup: dict | None = None


def prepare_message(
    text: str,
    keyboard: InlineKeyboard | None = None,
    force_chunk: bool = True,
) -> Rendered:
    """Turn text + optional keyboard into a Rendered message plan."""
    _, markup = render_markdown(text)
    sends = _chunks(markup) if force_chunk else [markup]
    if not sends:
        sends = [""]
    r = Rendered(sends=sends)
    if keyboard is not None:
        r.reply_markup = keyboard.markup()
    return r


def stable_callback(namespace: str, payload: str, max_len: int = 60) -> str:
    """Deterministic, length-capped callback_data so inline buttons round-trip
    through Telegram's 64-byte callback limit."""
    digest = hashlib.sha256(f"{namespace}:{payload}".encode()).hexdigest()[:16]
    token = (payload or "")[: max_len - 16]
    return f"{token}{digest}"


@dataclass
class TypingSender:
    """Wraps a connector transport and emits a ``sendChatAction`` typing
    heartbeat while a long task runs, if the transport supports it.

    ``heartbeat()`` is a no-op safe to call every few seconds; it self-limits
    to one request per TYPING_INTERVAL_SECONDS and swallows transport errors
    so a chat-action failure never aborts the actual task.
    """

    transport: Callable[[str, dict], dict]
    chat_id: int
    _last_sent: float = 0.0

    def heartbeat(self, action: str = "typing") -> None:
        import time

        now = time.monotonic()
        if now - self._last_sent < TYPING_INTERVAL_SECONDS:
            return
        try:
            self.transport("sendChatAction", {"chat_id": self.chat_id, "action": action})
            self._last_sent = now
        except Exception:
            # A chat-action failure must never surface to the owner as a task
            # error. The real message send below reports the real outcome.
            pass

    def send_markup(self, rendered: Rendered) -> None:
        """Send the prepared chunks; first chunk carries reply_markup."""
        for i, chunk in enumerate(rendered.sends):
            data = {"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML"}
            if i == 0 and rendered.reply_markup is not None:
                data["reply_markup"] = json.dumps(rendered.reply_markup)
            self.transport("sendMessage", data)
