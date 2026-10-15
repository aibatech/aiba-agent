from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterable
import hashlib
import json
import time
import math
import threading


class ApprovalManager:
    """Central approval gate for interactive CLI and trusted product requests."""

    def __init__(self, interactive: bool = True, auto_approve: bool = False,
                 input_fn: Callable[[str], str] = input):
        self.interactive = interactive
        self.auto_approve = auto_approve
        self.input_fn = input_fn
        self._grants: ContextVar[frozenset[str]] = ContextVar(
            "aiba_approval_grants", default=frozenset()
        )
        self._consumed: ContextVar[set[str] | None] = ContextVar("aiba_consumed", default=None)
        self._consume_lock = threading.Lock()
        self._principal = ContextVar("approval_principal", default=None)
        self._store = ContextVar("approval_store", default=None)
        self._deadline: ContextVar[float | None] = ContextVar('aiba_approval_deadline', default=None)
        self._requested: ContextVar[tuple[dict[str, str], ...]] = ContextVar(
            "aiba_approval_requests", default=()
        )

    @contextmanager
    def request_scope(self, approved_tools: Iterable[str] | None = None, *, ttl_seconds: float | None = None, principal: str | None = None, store=None):
        grants = frozenset(
            str(name).strip() for name in (approved_tools or ()) if str(name).strip()
        )
        if ttl_seconds is not None and (not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            raise ValueError('Approval TTL must be positive')
        grant_token = self._grants.set(grants)
        deadline_token = self._deadline.set(time.monotonic() + ttl_seconds if ttl_seconds is not None else None)
        request_token = self._requested.set(())
        consumed_token = self._consumed.set(set())
        principal_token = self._principal.set(principal)
        store_token = self._store.set(store)
        try:
            yield self
        finally:
            self._store.reset(store_token)
            self._principal.reset(principal_token)
            self._consumed.reset(consumed_token)
            self._requested.reset(request_token)
            self._deadline.reset(deadline_token)
            self._grants.reset(grant_token)

    @staticmethod
    def action_fingerprint(action: str, arguments: dict) -> str:
        canonical = json.dumps({"tool": action, "arguments": arguments}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def approve_exact(self, action: str, arguments: dict, reason: str = "") -> bool:
        fingerprint = self.action_fingerprint(action, arguments)
        # Existing tool-only grants remain supported for backward compatibility,
        # but sensitive callers can require the exact fingerprint grant.
        deadline = self._deadline.get()
        unexpired = deadline is None or time.monotonic() < deadline
        store = self._store.get()
        principal = self._principal.get()
        if store is not None and principal:
            if unexpired and any(store.consume(token, principal, fingerprint) for token in self._grants.get()):
                return True
        elif unexpired:
            # Context copies share the consumption set: parallel child tasks
            # cannot each spend the same request-local grant.
            with self._consume_lock:
                consumed = self._consumed.get()
                if consumed is not None and fingerprint in self._grants.get() and fingerprint not in consumed:
                    consumed.add(fingerprint)
                    return True
        if not self.interactive or principal:
            current = list(self._requested.get())
            item = {"tool": action, "fingerprint": fingerprint, "reason": reason}
            if item not in current:
                current.append(item)
                self._requested.set(tuple(current))
            return False
        return self.input_fn(f"Approve exact {action} ({reason})? [y/N] ").strip().lower() in {"y", "yes"}

    def pending_requests(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._requested.get()]

    def approve(self, action: str, reason: str = "") -> bool:
        if self._principal.get():
            return self.approve_exact(action, {"reason": reason}, reason)
        if self.auto_approve:
            return True
        if action in self._grants.get():
            return True
        if not self.interactive:
            current = list(self._requested.get())
            item = {"tool": str(action), "reason": str(reason or "")}
            if item not in current:
                current.append(item)
                self._requested.set(tuple(current))
            return False
        detail = f" ({reason})" if reason else ""
        return self.input_fn(f"Approve {action}{detail}? [y/N] ").strip().lower() in {"y", "yes"}
