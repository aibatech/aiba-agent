"""High-level SubagentManager that AgentLoop integrates with.

Bridges the low-level :mod:`agent.subagents` store + pool to the main agent:

* constructs the worker pool wired to the main loop's registry (tool metadata
  + handlers) and provider router,
* exposes `delegate` / `run_many` / `status` / `cancel` / `list_for_parent`,
* waits (bounded) for workers to reach terminal states and returns concise,
  redacted per-worker results for the main agent to synthesise,
* emits minimal plain-language UX progress via an injected EventBus sink and
  audits creation/delegation/completion/failure/cancel/synthesis through the
  shared AuditLog.

The manager controls an ``enabled`` flag: when False (the default unless
``subagents_enabled``), no worker may be created — mirroring the capability-
flag posture of browser/desktop so subagents are unavailable until explicitly
enabled.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from agent.subagents import (
    QUEUED,
    RUNNING,
    TERMINAL_STATES,
    SubagentPool,
    SubagentStore,
    _collect_terminated,
)

_PROGRESS_MSG = "I'm checking this from a few angles — give me a moment."


class SubagentManager:
    def __init__(
        self,
        db_path,
        *,
        enabled: bool = False,
        audit: Any | None = None,
        events: Any | None = None,
        resolve_tools: Callable[[list[str]], dict[str, Any]] | None = None,
        call_provider: Callable[..., str] | None = None,
        policy_allows: Callable[[str], bool] | None = None,
        global_concurrency: int = 3,
        per_parent_concurrency: int = 2,
        step_cap_default: int = 10,
        time_limit_default: int = 120,
        max_cost_default: float | None = None,
    ):
        self.enabled = bool(enabled)
        self.events = events
        self._audit = audit
        self._consents: dict[str, set[str]] = {}
        self.store = SubagentStore(db_path)
        self.store.recover_interrupted()
        self.pool = SubagentPool(
            self.store,
            resolve_tools=resolve_tools or (lambda names: {}),
            call_provider=call_provider or (lambda messages, schemas: ""),
            policy_allows=policy_allows or (lambda name: True),
            approval_granted=lambda sub_id, name: self.approval_granted(sub_id, name),
            audit=audit,
            global_concurrency=global_concurrency,
            per_parent_concurrency=per_parent_concurrency,
            step_cap_default=step_cap_default,
            time_limit_default=time_limit_default,
            max_cost_default=max_cost_default,
        )

    # -- audit / ux helpers --------------------------------------------------
    def _audit_record(self, event: str, **data: Any) -> None:
        if self._audit is not None:
            try:
                self._audit.record("subagent_" + event, **data)
            except Exception:
                pass

    def _ux_progress(self, detail: str | None = None) -> None:
        """Brief plain-language progress only — no prompts/CoT/transcripts."""
        if self.events is not None:
            try:
                self.events.publish("subagent.progress",
                                    message=detail or _PROGRESS_MSG)
            except Exception:
                pass

    # -- guard ---------------------------------------------------------------
    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ValueError(
                "Internal subagents are disabled. Set AIBA_SUBAGENTS_ENABLED=true "
                "to enable bounded parallel workers."
            )

    def requires_approval(self, tool: str) -> bool:
        """Whether a tool of the same name would require operator approval on
        the MAIN agent (used to require explicit consent in delegations)."""
        # The policy-level approval requirement is enforced by the worker's
        # permission-narrowing via the pool's approval_granted callback. Here we
        # surface the generic default (delegations opt in per call).
        return False

    # -- worker lifecycle ----------------------------------------------------
    def delegate(
        self,
        objective: str,
        *,
        parent_task_id: str | None = None,
        allowed_tools: list[str] | None = None,
        max_steps: int | None = None,
        time_limit_s: int | None = None,
        max_cost: float | None = None,
        workspace: Any | None = None,
        allow_approved: bool = False,
    ) -> str:
        """Create (and queue) one subagent task. Returns the subagent id.

        ``allow_approved`` opts the delegation into approval-required /
        sensitive-capability tools that the parent explicitly listed; it is the
        explicit-operator-consent channel (never granted by default).
        """
        self._require_enabled()
        objective = (objective or "").strip()
        if not objective:
            raise ValueError("Subagent objective cannot be empty.")
        allowed = list(allowed_tools or [])
        if len(allowed) > 64:
            raise ValueError("Too many allowed tools for a subagent.")
        spec = {
            "parent_task_id": parent_task_id,
            "objective": objective[:20000],
            "allowed_tools": allowed,
            "workspace": workspace,
            "max_steps": int(max_steps or self.pool.step_cap_default),
            "time_limit_s": int(time_limit_s or self.pool.time_limit_default),
            "max_cost": max_cost,
        }
        sub_id = self.store.create(spec)
        # Explicit operator consent (allow_approved) is recorded NOW, at
        # delegation time, so a worker that later gains a concurrency slot still
        # has its consent even though it started queued.
        if allow_approved:
            self._remember_consent(sub_id, {t for t in allowed if t})
        self._audit_record("created", subagent_id=sub_id,
                           parent_task_id=parent_task_id,
                           allowed_tools=sorted(allowed),
                           objective_chars=len(objective),
                           allow_approved=bool(allow_approved))
        self._ux_progress()
        # Dispatch immediately if a slot is free; otherwise it stays queued and
        # run_many's fill-loop (or a later delegate) dispatches it when a slot
        # frees. Consent is already recorded above, so the queued worker is safe.
        self._maybe_dispatch(sub_id)
        return sub_id

    def _maybe_dispatch(self, sub_id: str) -> bool:
        """Dispatch a queued subagent if a global + per-parent slot is free."""
        record = self.store.get(sub_id)
        if not record:
            return False
        if not self.pool.can_dispatch(record.get("parent_task_id")):
            return False
        self.pool.dispatch(sub_id)
        return True

    def _remember_consent(self, sub_id: str, grant: set[str],
                          extra: set[str] | None = None) -> None:
        self._consents[sub_id] = grant | (extra or set())

    def approval_granted(self, sub_id: str | None, name: str) -> bool:
        """Pool callback: is *name* consented for *sub_id*?"""
        if sub_id is None:
            return False
        return name in self._consents.get(sub_id, set())

    def run_many(
        self,
        objectives: list[str],
        *,
        parent_task_id: str | None = None,
        allowed_tools: list[str] | None = None,
        allow_approved: bool = False,
        max_steps: int | None = None,
        time_limit_s: int | None = None,
        max_cost: float | None = None,
        wait_s: float = 120.0,
    ) -> dict[str, Any]:
        """Create and run several subagents in parallel.

        All are queued first (so concurrency is global AND per-parent bounded),
        then a fill-scheduler keeps dispatching queued workers as slots free,
        until the wall-clock wait budget is reached. Returns concise results for
        workers that reached a terminal state plus ids still busy.
        """
        self._require_enabled()
        if not objectives:
            return {"results": [], "pending": []}
        if len(objectives) > 50:
            raise ValueError("Too many subagents in one batch (>50).")
        ids: list[str] = []
        for obj in objectives:
            ids.append(self.delegate(
                obj, parent_task_id=parent_task_id,
                allowed_tools=allowed_tools or [],
                allow_approved=allow_approved,
                max_steps=max_steps, time_limit_s=time_limit_s,
                max_cost=max_cost))
        deadline = time.monotonic() + max(0.5, wait_s)
        # Fill scheduler: repeatedly try to dispatch any queued worker whose
        # task has a free slot; stop when all terminal or deadline passes.
        while time.monotonic() < deadline:
            any_done = True
            for sub_id in ids:
                rec = self.store.get(sub_id)
                if rec and rec["status"] in (QUEUED, RUNNING):
                    any_done = False
                    if rec["status"] == QUEUED:
                        # Respect per-parent concurrency before dispatching.
                        if self.pool.can_dispatch(rec.get("parent_task_id")):
                            self._maybe_dispatch(sub_id)
            if any_done:
                break
            time.sleep(0.02)
        # Wait a little past deadline only if workers are close; then report.
        results = _collect_terminated(self.store, ids)
        pending = [i for i in ids
                   if (self.store.get(i) or {}).get("status") not in TERMINAL_STATES]
        return {"results": results, "pending": pending}

    def status(self) -> dict[str, Any]:
        """Concise live status (counts) — no prompts or transcripts."""
        rows = self.store.list()
        counts = {"queued": 0, "running": 0, "completed": 0,
                  "failed": 0, "cancelled": 0, "timed_out": 0}
        for r in rows:
            st = r.get("status")
            if st in counts:
                counts[st] += 1
        counts["enabled"] = self.enabled
        counts["global_concurrency"] = self.pool.global_limit
        counts["per_parent_concurrency"] = self.pool.per_parent_limit
        return counts

    def status_of(self, sub_id: str) -> dict[str, Any] | None:
        rec = self.store.get(sub_id)
        if not rec:
            return None
        return {
            "id": rec["id"], "status": rec["status"],
            "parent_task_id": rec.get("parent_task_id"),
            "steps": rec.get("step_count", 0),
            "error": (rec.get("error") or "")[:500],
            "result": (rec.get("result_summary") or "")[:2000],
            "created_at": rec.get("created_at"), "updated_at": rec.get("updated_at"),
        }

    def cancel(self, sub_id: str) -> bool:
        self._audit_record("cancel_requested", subagent_id=sub_id)
        return self.pool.cancel(sub_id)

    def list_for_parent(self, parent_task_id: str) -> list[dict[str, Any]]:
        return _collect_terminated(
            self.store, [r["id"] for r in self.store.list(parent_task_id)])

    # -- synthesis ----------------------------------------------------------
    def synthesize(self, results: list[dict[str, Any]]) -> str:
        """Produce a concise structured synthesis the main agent can relay."""
        if not results:
            return "No worker results were returned."
        lines = []
        done = [r for r in results if r.get("status") == "completed"]
        failed = [r for r in results if r.get("status") != "completed"]
        for r in done:
            lines.append(f"- Worker {r.get('id', '?')[:8]} ({r.get('steps', 0)} steps): "
                         f"{r.get('result') or 'no detail'}")
        for r in failed:
            lines.append(f"- Worker {r.get('id', '?')[:8]} [{r.get('status')}]: "
                         f"{r.get('error') or 'no detail'}")
        body = "\n".join(lines)
        if failed:
            return (f"Ran {len(results)} parallel workers: {len(done)} completed, "
                    f"{len(failed)} did not finish cleanly.\n\n{body}")
        return (f"Ran {len(results)} parallel workers; all completed.\n\n{body}")

    def close(self) -> None:
        try:
            self.pool.shutdown(wait=True)
        except Exception:
            pass
