"""Phase 2 — Visible reasoning protocol.

A typed, versioned observability protocol for the agent loop. AIBA's own
chain-of-thought is never exposed; instead each step of a task emits a
**sanitised**, human-readable event describing what happened and why, not the
model's private deliberation. Consumers (dashboard, Telegram panel, tests) can
subscribe and render a live, honest view of the agent as it works.

Event envelope::

    {
      "protocol": "aiba.reasoning",
      "version": 1,
      "task_id": "...",
      "timestamp": 1234.56,
      "event": {
        "kind": "plan" | "tool" | "result" | "final" | "error",
        ...
      }
    }

A publisher wraps any callable that accepts ``(event_type, **payload)`` (the
existing ``EventBus.publish``, a log sink, or a fake in tests), so the protocol
plugs into whatever transport the runtime already provides.
"""
from __future__ import annotations

import time
from typing import Any, Callable

PROTOCOL = "aiba.reasoning"
PROTOCOL_VERSION = 1

# Kinds of reasoning events. Deliberately coarser than the model's true
# chain-of-thought: enough for a user to see progress, never the raw tokens.
K_PLAN = "plan"
K_TOOL = "tool"
K_RESULT = "result"
K_FINAL = "final"
K_ERROR = "error"
ALL_KINDS = {K_PLAN, K_TOOL, K_RESULT, K_FINAL, K_ERROR}


class VisibleReasoning:
    """Emits sanitised reasoning events to an underlying sink.

    ``publish`` is a callable with the ``EventBus.publish`` signature:
    ``(event_type, **payload)``. ``task_id`` links every event in one task.
    """

    def __init__(self, publish: Callable[..., None], task_id: str):
        self._publish = publish
        self.task_id = task_id

    def _emit(self, kind: str, **payload: Any) -> None:
        event = {
            "protocol": PROTOCOL,
            "version": PROTOCOL_VERSION,
            "task_id": self.task_id,
            "timestamp": round(time.time(), 3),
            "event": {"kind": kind, **payload},
        }
        # Name the bus event after the kind so subscriptions can filter cheaply,
        # and fan out to the all-events wildcard as well.
        sink = self._publish
        try:
            sink(f"reasoning.{kind}", **event)
            sink("reasoning.*", **event)
        except Exception:
            # Observability must never break the task it observes.
            pass

    def plan(self, summary: str, steps: int | None = None, **extra: Any) -> None:
        """The agent settled on an approach (public summary of intent)."""
        data = {"summary": summary}
        if steps is not None:
            data["steps"] = steps
        data.update(extra)
        self._emit(K_PLAN, **data)

    def tool(self, name: str, arguments: dict | None = None, tool_index: int | None = None, **extra: Any) -> None:
        """A tool call is about to run (sanitised: no secrets in arguments)."""
        data: dict[str, Any] = {"tool": name}
        if arguments is not None:
            data["arguments"] = _sanitise(arguments)
        if tool_index is not None:
            data["tool_index"] = tool_index
        data.update(extra)
        self._emit(K_TOOL, **data)

    def result(self, tool: str, ok: bool, output_preview: str | None = None, **extra: Any) -> None:
        """A tool returned (never the full raw output; a short, safe preview)."""
        data = {"tool": tool, "ok": ok}
        if output_preview is not None:
            data["output_preview"] = _clip(output_preview, 200)
        data.update(extra)
        self._emit(K_RESULT, **data)

    def final(self, response_preview: str | None = None, tool_count: int | None = None, **extra: Any) -> None:
        """The task finished with a final answer."""
        data: dict[str, Any] = {}
        if response_preview is not None:
            data["response_preview"] = _clip(response_preview, 200)
        if tool_count is not None:
            data["tool_count"] = tool_count
        data.update(extra)
        self._emit(K_FINAL, **data)

    def error(self, detail: str, **extra: Any) -> None:
        """The task failed (public, sanitised reason only)."""
        data = {"detail": _clip(detail, 200)}
        data.update(extra)
        self._emit(K_ERROR, **data)


_SECRET_KEYS = ("key", "secret", "password", "authorization", "api_key", "apikey", "cookie", "passwd", "token")


def _sanitise(arguments: dict) -> dict:
    """Return a copy of tool arguments with secret-looking keys redacted and
    long blobs truncated, so protocol events never leak credentials."""
    out: dict[str, Any] = {}
    for k, v in arguments.items():
        low = str(k).lower()
        if any(s in low for s in _SECRET_KEYS):
            out[k] = "[redacted]"
        elif isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "..."
        elif isinstance(v, dict):
            out[k] = _sanitise(v)
        else:
            out[k] = v
    return out


def _clip(value: str, n: int) -> str:
    value = str(value)
    return value if len(value) <= n else value[:n] + "..."
