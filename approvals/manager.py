from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterable


class ApprovalManager:
    """Central approval gate used by every mutation-capable tool.

    Interactive CLI installs can still ask on stdin. Server-side product calls
    use ``request_scope`` instead: the first pass records requested actions and
    denies them; after the user approves in the product UI, the trusted product
    backend may retry the turn with a narrowly-scoped grant for only those tool
    names. Grants and pending requests are ContextVar-backed so they cannot leak
    between users, threads, or requests.
    """

    def __init__(self, interactive: bool = True, auto_approve: bool = False,
                 input_fn: Callable[[str], str] = input):
        self.interactive = interactive
        self.auto_approve = auto_approve
        self.input_fn = input_fn
        self._grants: ContextVar[frozenset[str]] = ContextVar(
            "aiba_approval_grants", default=frozenset()
        )
        self._requested: ContextVar[tuple[dict[str, str], ...]] = ContextVar(
            "aiba_approval_requests", default=()
        )

    @contextmanager
    def request_scope(self, approved_tools: Iterable[str] | None = None):
        """Isolate approval state for one trusted product/API request.

        ``approved_tools`` is intentionally only a set of exact tool names.
        It is expected to come from a server-side user approval record, never
        directly from an untrusted browser/mobile client.
        """
        grants = frozenset(
            str(name).strip() for name in (approved_tools or ()) if str(name).strip()
        )
        grant_token = self._grants.set(grants)
        request_token = self._requested.set(())
        try:
            yield self
        finally:
            self._requested.reset(request_token)
            self._grants.reset(grant_token)

    def pending_requests(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._requested.get()]

    def approve(self, action: str, reason: str = "") -> bool:
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
