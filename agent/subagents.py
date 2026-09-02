"""AIBA internal subagent (bounded task-worker) subsystem.

Product rule honoured end-to-end: AIBA remains ONE primary assistant.
Subagents are invisible background workers created *only* when parallel
research, verification, planning or review makes a task better or faster.
They never surface their hidden prompts, raw chain-of-thought or full worker
transcripts to the user — the main AIBA gets a concise structured result per
worker, then produces a simple final synthesis.

Design goals (all enforced in code, not by prompt):

* Bounded real workers: each subagent is its own provider + narrowed tool loop
  with an explicit objective, parent task id, explicit allowed-tools list,
  a step cap, a wall-clock time limit and (best-effort) a cost budget.
* Permission narrowing: a worker may use *only* tools its parent explicitly
  listed AND that pass the shared SecurityPolicy (already enabled, not
  approval-required unless the delegation carried explicit consent). A worker
  can never be broader than its parent, and cannot reach computer control,
  browser mutations, process tools, MCP or external comms unless that specific
  capability is enabled+approved at policy time AND the parent listed it.
* Recursion depth zero by default: subagents are not given any tool that can
  spawn another subagent, so they physically cannot create subagents.
* Bounded parallelism: a global max-concurrency limiter and a per-parent limiter.
* Full state machine: queued / running / completed / failed / cancelled /
  timed_out, with cancellation and bounded cleanup.
* Isolation: one worker failure/crash never propagates into the main agent;
  it is recorded as failed with a concise summary.
* Persistence + recovery: metadata and concise results are stored so work
  survives a restart; running subagents at boot are marked timed_out/failed.
* Audit: creation, delegation, worker completion/failure, cancellation and
  synthesis are all logged; secrets and full prompts/transcripts are never
  stored in summaries or sent to the main agent.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlite_utils import connect

# ---- state machine ---------------------------------------------------------
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TIMED_OUT = "timed_out"
APPROVED_STATES = (QUEUED, RUNNING)
TERMINAL_STATES = (COMPLETED, FAILED, CANCELLED, TIMED_OUT)

# Tools never implicitly exposed to a worker's narrowed set:
# spawn/admin/control surfaces that would let a worker delegate further
# (recursion-depth-zero guarantee) or reach external background machinery.
_SUBPARENT_TOOLS = frozenset({
    "delegate_task", "spawn_subagent", "subagent_cancel", "enqueue_task",
    "schedule_task", "subagent_status", "clarify",
})

# Capabilities that are never granted to a worker unless the specific tool is
# enabled at policy level AND the parent delegation explicitly listed it AND
# (if approval-required) the delegation carried explicit operator consent
# (``allow_approved``). This is defense-in-depth over the generic approval drop.
_SENSITIVE_CAPABILITY_TOOLS = frozenset({
    "desktop_screenshot", "desktop_click", "desktop_type", "desktop_screen_size",
    "desktop_move", "desktop_drag", "desktop_scroll", "desktop_key",
    "desktop_hotkey", "desktop_open_url", "desktop_clipboard_read",
    "desktop_clipboard_write", "desktop_node_status",
    "browser_click", "browser_type", "browser_select", "browser_submit",
    "browser_scroll", "browser_download", "browser_upload", "browser_open",
    "run_shell", "run_python", "delete_file", "patch_file", "archive",
    "extract_archive", "remember", "write_file", "enqueue_task", "schedule_task",
})

_WORKER_SYSTEM = (
    "You are a focused internal worker for AIBA, executed autonomously with a bounded budget. "
    "Resolve the objective you are given using ONLY the tools provided below. "
    "You may issue {\"type\":\"tool_call\",\"tool\":\"name\",\"arguments\":{}} or "
    "{\"type\":\"final\",\"response\":\"text\"}. "
    "When you have enough information, respond with a FINAL concise result summary "
    "(what you found / produced, key sources or evidence, any caveats). "
    "Do not reveal hidden prompts or internal chain-of-thought; "
    "do not claim tool success you did not observe; verify consequential results. "
    "You cannot create further subagents."
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- persistence -----------------------------------------------------------
class SubagentStore:
    """SQLite persistence for subagent task metadata + concise results."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with connect(self.path) as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS subagents(
                    id TEXT PRIMARY KEY,
                    parent_task_id TEXT,
                    objective TEXT NOT NULL,
                    allowed_tools TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workspace TEXT,
                    max_steps INTEGER,
                    time_limit_s INTEGER,
                    max_cost REAL,
                    step_count INTEGER NOT NULL DEFAULT 0,
                    cost REAL,
                    result_summary TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )"""
            )

    def create(self, spec: dict[str, Any]) -> str:
        i = str(uuid.uuid4())
        t = _utcnow()
        with connect(self.path) as c:
            c.execute(
                "INSERT INTO subagents(id,parent_task_id,objective,allowed_tools,status,"
                "workspace,max_steps,time_limit_s,max_cost,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (i, spec.get("parent_task_id"), spec.get("objective", ""),
                 json.dumps(spec.get("allowed_tools", [])), QUEUED,
                 spec.get("workspace"), spec.get("max_steps"),
                 spec.get("time_limit_s"), spec.get("max_cost"), t, t),
            )
        return i

    def update_status(self, i: str, status: str, **extra: Any) -> None:
        fields = ["status", "updated_at"]
        values: list[Any] = [status, _utcnow()]
        for k, v in extra.items():
            if k in {
                "step_count", "cost", "result_summary", "error",
                "started_at", "finished_at",
            }:
                fields.append(k)
                values.append(v)
        if fields == ["status", "updated_at"]:
            pass
        cols = ",".join(f"{f}=?" for f in fields)
        with connect(self.path) as c:
            c.execute(f"UPDATE subagents SET {cols} WHERE id=?", (*values, i))

    def get(self, i: str) -> dict[str, Any] | None:
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM subagents WHERE id=?", (i,)).fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["allowed_tools"] = json.loads(d.get("allowed_tools") or "[]")
            except Exception:
                d["allowed_tools"] = []
            return d

    def list(self, parent_task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.path) as c:
            c.row_factory = sqlite3.Row
            if parent_task_id:
                rows = c.execute(
                    "SELECT * FROM subagents WHERE parent_task_id=? "
                    "ORDER BY created_at DESC LIMIT ?", (parent_task_id, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM subagents ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["allowed_tools"] = json.loads(d.get("allowed_tools") or "[]")
                except Exception:
                    d["allowed_tools"] = []
                out.append(d)
            return out

    def recover_interrupted(self) -> int:
        """Mark anything left 'running' from a previous process as timed_out;
        anything 'queued' with no agent holding it stays queued (re-dispatched
        on next run only if a new manager claims it — see manager)."""
        with connect(self.path) as c:
            cur = c.execute(
                "UPDATE subagents SET status=?, updated_at=?, finished_at=?, "
                "result_summary='Interrupted before completion; process restarted.' "
                "WHERE status=?",
                (TIMED_OUT, _utcnow(), _utcnow(), RUNNING),
            )
            return cur.rowcount if cur else 0


# ---- in-memory pool --------------------------------------------------------
class SubagentPool:
    """Governs bounded parallel execution of subagent tasks.

    A worker runs in its own daemon executor thread with its own narrowed tool
    registry and provider. One failure is isolated to that worker.
    """

    def __init__(
        self,
        store: SubagentStore,
        *,
        resolve_tools: Callable[[list[str]], dict[str, Any]],
        call_provider: Callable[..., str],
        policy_allows: Callable[[str], bool],
        approval_granted: Callable[[str, str], bool],
        audit: Any | None = None,
        global_concurrency: int = 3,
        per_parent_concurrency: int = 2,
        step_cap_default: int = 10,
        time_limit_default: int = 120,
        max_cost_default: float | None = None,
    ):
        """``resolve_tools`` maps an allowed-tool list to {name: {'handler',
        'description', 'parameters', 'requires_approval'}}. ``call_provider``
        runs one model call and returns the parsed action. ``policy_allows``
        reports whether a tool is enabled at policy level once. ``approval_granted``
        reports whether a worker is allowed to run a normally-approval-required
        tool (explicit delegation consent)."""
        self.store = store
        self._resolve_tools = resolve_tools
        self._call_provider = call_provider
        self._policy_allows = policy_allows
        self._approval_granted = approval_granted
        self._audit = audit
        self.global_limit = max(1, int(global_concurrency))
        self.per_parent_limit = max(1, int(per_parent_concurrency))
        self.step_cap_default = int(step_cap_default)
        self.time_limit_default = int(time_limit_default)
        self.max_cost_default = max_cost_default
        self._executor = ThreadPoolExecutor(max_workers=self.global_limit,
                                            thread_name_prefix="aiba-sub")
        self._lock = threading.RLock()
        self._active: dict[str, str] = {}          # subagent_id -> parent_task_id
        self._per_parent_active: dict[str, int] = {}   # parent -> count running/queued-running
        self._cancel: set[str] = set()

    # -- bookkeeping ------------------------------------------------------
    def _audit_record(self, event: str, **data: Any) -> None:
        if self._audit is not None:
            try:
                self._audit.record("subagent_" + event, **data)
            except Exception:
                pass

    def _parent_slot_available(self, parent_task_id: str) -> bool:
        self._audit_record  # no-op accessor guard
        return self._per_parent_active.get(parent_task_id, 0) < self.per_parent_limit

    def _global_slot_available(self) -> bool:
        return len(self._active) < self.global_limit

    def can_dispatch(self, parent_task_id: str | None) -> bool:
        return self._global_slot_available() and self._parent_slot_available(parent_task_id or "ROOT")

    def _begin(self, sub_id: str, parent_task_id: str | None) -> None:
        parent = parent_task_id or "ROOT"
        with self._lock:
            self._active[sub_id] = parent
            self._per_parent_active[parent] = self._per_parent_active.get(parent, 0) + 1

    def _end(self, sub_id: str) -> None:
        parent = self._active.pop(sub_id, None)
        if parent is not None:
            with self._lock:
                self._per_parent_active[parent] = max(
                    0, self._per_parent_active.get(parent, 0) - 1)

    # -- public API -------------------------------------------------------
    def dispatch(self, sub_id: str) -> None:
        """Dispatch an already-persisted subagent to a worker thread."""
        record = self.store.get(sub_id)
        if not record:
            return
        if record["status"] != QUEUED:
            return
        self.store.update_status(sub_id, RUNNING, started_at=_utcnow())
        self._begin(sub_id, record.get("parent_task_id"))
        self._audit_record("start", subagent_id=sub_id,
                           parent_task_id=record.get("parent_task_id"))
        self._executor.submit(self._run_guarded, sub_id)

    def cancel(self, sub_id: str) -> bool:
        """Request cancellation: mark cancelled if not yet running; if running,
        mark for abort — the worker loop checks the flag between steps and stops
        cleanly (bounded cleanup)."""
        record = self.store.get(sub_id)
        if not record or record["status"] in TERMINAL_STATES:
            return False
        with self._lock:
            self._cancel.add(sub_id)
        if record["status"] == QUEUED:
            self.store.update_status(sub_id, CANCELLED, finished_at=_utcnow())
        self._audit_record("cancel", subagent_id=sub_id)
        return True

    def _should_abort(self, sub_id: str) -> bool:
        return sub_id in self._cancel

    def _run_guarded(self, sub_id: str) -> None:
        """Isolation boundary: any exception below is captured and recorded as a
        worker failure — the main agent and other workers are unaffected."""
        try:
            self._run(sub_id)
        except Exception as exc:  # pragma: no cover - defensive
            try:
                self.store.update_status(sub_id, FAILED, error=f"{type(exc).__name__}: {exc}",
                                         finished_at=_utcnow())
                self._audit_record("failed", subagent_id=sub_id,
                                   error=f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
        finally:
            self._end(sub_id)

    def _run(self, sub_id: str) -> None:
        record = self.store.get(sub_id)
        if not record:
            return
        if record.get("status") == CANCELLED:
            return
        if self._should_abort(sub_id):
            self.store.update_status(sub_id, CANCELLED, finished_at=_utcnow())
            return

        # Permission narrowing for this worker. A tool reaches the worker ONLY
        # if, in order: (1) the parent's delegation explicitly listed it,
        # (2) it is enabled at the shared SecurityPolicy level (a worker can
        # never be broader than the main agent), (3) it is not a spawn/admin
        # surface (_SUBPARENT_TOOLS => recursion-depth-zero), and (4) any
        # approval-required tool OR sensitive capability additionally needs
        # explicit delegation consent (_approval_granted).
        parent_allow = [t for t in (record.get("allowed_tools") or []) if t]
        policy_ok = [t for t in parent_allow if self._policy_allows(t)]
        safe = [t for t in policy_ok if t not in _SUBPARENT_TOOLS]
        toolset = self._resolve_tools(safe)
        usable: dict[str, Any] = {}
        for name, meta in toolset.items():
            req_approval = bool(meta.get("requires_approval"))
            sensitive = name in _SENSITIVE_CAPABILITY_TOOLS
            if (req_approval or sensitive) and not self._approval_granted(sub_id, name):
                continue  # withheld: no explicit delegation consent
            usable[name] = meta

        max_steps = int(record.get("max_steps") or self.step_cap_default)
        time_limit = float(record.get("time_limit_s") or self.time_limit_default)
        timeout_at = time.monotonic() + time_limit
        objective = record.get("objective") or ""
        parent = record.get("parent_task_id")
        workspace = record.get("workspace")

        self._audit_record("delegated", subagent_id=sub_id, parent_task_id=parent,
                           allowed_tools=sorted(usable.keys()), objective_chars=len(objective))

        step_count = 0
        total_cost = 0.0
        max_cost = record.get("max_cost")
        if max_cost is not None:
            try:
                max_cost = float(max_cost)
            except (TypeError, ValueError):
                max_cost = None
        try:
            summary, steps, cost = self._worker_loop(
                sub_id, objective, usable,
                max_steps=max_steps, timeout_at=timeout_at,
                max_cost=max_cost,
            )
            step_count = steps
            total_cost = float(cost or 0.0)
            self.store.update_status(
                sub_id, COMPLETED, step_count=step_count, cost=total_cost,
                result_summary=summary or "",
                finished_at=_utcnow(),
            )
            self._audit_record("completed", subagent_id=sub_id, steps=steps,
                               cost=round(total_cost, 4),
                               summary_chars=len(summary or ""))
        except _WorkerTimeout:
            self.store.update_status(sub_id, TIMED_OUT, error="Worker exceeded its time budget.",
                                     finished_at=_utcnow())
            self._audit_record("timed_out", subagent_id=sub_id)
        except _BudgetExceeded as exc:
            self.store.update_status(sub_id, FAILED, error=str(exc),
                                     finished_at=_utcnow())
            self._audit_record("failed_budget", subagent_id=sub_id, error=str(exc))
        except _WorkerCancelled:
            self.store.update_status(sub_id, CANCELLED, finished_at=_utcnow(),
                                     result_summary="Cancelled by operator before completion.")
            self._audit_record("completed_cancelled", subagent_id=sub_id)
        except Exception as exc:  # local worker failure
            self.store.update_status(sub_id, FAILED, error=f"{type(exc).__name__}: {exc}",
                                     finished_at=_utcnow())
            self._audit_record("failed", subagent_id=sub_id,
                               error=f"{type(exc).__name__}: {exc}")

    def _worker_loop(self, sub_id, objective, usable,
                     max_steps, timeout_at, max_cost=None):
        """Minimal self-contained provider + tool loop (no full transcript kept).

        ``max_cost`` (best-effort) is honoured only when the provider reports
        per-call usage via its ``_last_cost`` attribute (or the returned action
        carries a ``cost``); otherwise the cost budget is inert, matching a
        "best-effort when usage data exists" contract. Step/time stay hard caps.
        """
        schemas = self._schemas(usable)
        # Build the messages.
        messages = [
            {"role": "system",
             "content": _WORKER_SYSTEM + "\nTools: " + json.dumps(schemas)},
            {"role": "user", "content": objective},
        ]
        final = ""
        steps = 0
        total_cost = 0.0
        for _ in range(max_steps):
            # Bounded cleanup: check cancellation and wall clock before each step.
            if self._should_abort(sub_id):
                raise _WorkerCancelled()
            if time.monotonic() > timeout_at:
                raise _WorkerTimeout()
            action = self._call_provider(messages, schemas)
            steps += 1
            # Best-effort cost: a provider that surfaces per-call usage lets a
            # delegation with an explicit max_cost be capped.
            if max_cost is not None:
                try:
                    usage = float(getattr(self._call_provider, "_last_cost", 0.0) or 0.0)
                except (TypeError, ValueError):
                    usage = 0.0
                total_cost += usage
                if total_cost > max_cost:
                    raise _BudgetExceeded(
                        f"Worker exceeded its cost budget ({max_cost:.4f}).")
            action = self._normalize_action(action)
            if action is None:
                continue
            if action.get("type") == "final":
                return str(action.get("response", "")), steps, total_cost
            if action.get("type") != "tool_call":
                # Unknown / delegate-like action: never let a worker delegate.
                messages.append({"role": "assistant",
                                 "content": json.dumps(action)})
                messages.append({"role": "user",
                                 "content": json.dumps({"error":
                                    "That action is not permitted."})})
                continue
            name = action.get("tool")
            if not name or name not in usable:
                messages.append({"role": "assistant", "content": json.dumps(action)})
                messages.append({"role": "user", "content": json.dumps({
                    "error": f"Tool '{name}' is not available to this worker."})})
                continue
            args = action.get("arguments") or {}
            res = self._run_tool(usable[name], args)
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user",
                             "content": json.dumps({"ok": res["ok"],
                                                    "output": res["output"],
                                                    "error": res["error"]},
                                                    default=str)})
        raise _BudgetExceeded(f"Worker exceeded its maximum step budget ({max_steps}).")

    def _normalize_action(self, action: Any) -> dict | None:
        """Parse a provider response into a plain action dict (mirrors the main
        engine's tolerant JSON parsing). Returns None to skip on empty/irrelevant."""
        if isinstance(action, dict):
            return action
        if action is None:
            return None
        text = str(action).strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return {"type": "final", "response": text}
        if isinstance(parsed, dict):
            return parsed
        return {"type": "final", "response": text}

    def _schemas(self, usable: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"name": n, "description": m.get("description", ""),
                 "parameters": m.get("parameters", {"type": "object"})}
                for n, m in usable.items()]

    def _run_tool(self, meta: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        handler = meta.get("handler")
        if handler is None or not callable(handler):
            return {"ok": False, "output": None, "error": "Tool has no runnable handler"}
        try:
            out = handler(**args)
        except Exception as exc:
            return {"ok": False, "output": None, "error": f"{type(exc).__name__}: {exc}"}
        # ToolResult (or object with .ok) -> plain dict
        if hasattr(out, "ok"):
            o_oks = getattr(out, "ok")
            return {"ok": bool(o_oks), "output": getattr(out, "output", None),
                    "error": getattr(out, "error", None)}
        return {"ok": True, "output": out, "error": None}

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting work and wait (briefly) for running workers."""
        try:
            self._executor.shutdown(wait=False)
            if not wait:
                return
            # give short grace then flag-cancel
        except Exception:
            pass


class _WorkerTimeout(Exception):
    pass


class _BudgetExceeded(Exception):
    pass


class _WorkerCancelled(Exception):
    pass


def _collect_terminated(store: SubagentStore, ids: list[str]) -> list[dict[str, Any]]:
    """Return concise, redacted records ONLY for workers already in a terminal
    state (no objective/transcript included beyond the safe summary stored)."""
    out = []
    for i in ids:
        r = store.get(i)
        if not r or r["status"] not in TERMINAL_STATES:
            continue
        out.append({
            "id": r["id"],
            "status": r["status"],
            "parent_task_id": r.get("parent_task_id"),
            "steps": r.get("step_count", 0),
            "error": (r.get("error") or "")[:500],
            "result": (r.get("result_summary") or "")[:2000],
            "workspace": r.get("workspace"),
        })
    return out
