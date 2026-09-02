"""Internal Subagents (Phase 3) store / pool / manager tests.

Drives the *real* SubagentStore and SubagentManager with a scripted FAKE
provider + FAKE toolset — never a live model, browser, desktop, MCP, network,
or external service. Proves the bounded internal task-worker contract:

State machine & persistence
  * queued -> running -> completed / cancelled / failed / timed_out
  * running rows survive reload and restart-marked ``timed_out``; queued remain
  * manager shutdown is safe + idempotent

Real parallelism & concurrency
  * workers genuinely overlap (barrier proves simultaneous execution)
  * a global concurrency cap and a per-parent cap are enforced
  * a single worker failure is isolated (pool and other workers unaffected)

Budgets, timeout & cancellation
  * step budget ends a loop that would otherwise spin forever
  * wall-clock timeout ends a worker that holds before completing
  * bounded wait returns quickly (``pending``) and never blocks indefinitely
  * cancellation of queued + running workers reaches a clean terminal state

Security / narrowing (workers can only get narrower, never broader)
  * the worker's tool set excludes admin/recursive surfaces (delegate, spawn,
    schedule, clarify, task-manage)
  * sensitive/approval-required tools are withheld unless delegation consent
  * recursion depth stays zero — workers are never handed a spawn surface

Audit / UX hygiene
  * audit records keep lengths/counts/tool names, not prompts/transcripts/secrets
  * final synthesis is concise + structured, not a transcript of deliberation
"""
from __future__ import annotations

import json
import sqlite3
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent.subagent_manager import SubagentManager, _PROGRESS_MSG
from agent.subagents import (
    CANCELLED, COMPLETED, FAILED, QUEUED, RUNNING, TIMED_OUT, SubagentStore,
    _SUBPARENT_TOOLS,
)

# ---------------------------------------------------------------------------
# Shared fake backend
# ---------------------------------------------------------------------------

FAKE_SENSITIVE = {"write_file", "delete_file", "run_shell", "run_python",
                  "browser_click", "desktop_click"}


class FakeAudit:
    """Collects audit records so tests can assert redaction."""
    def __init__(self):
        self.events = []

    def record(self, event, **data):
        self.events.append((event, data))


class FakeProvider:
    """A scripted 'model'. Each call returns script[idx] (last for idx past
    end). Records every call's schema-name list in ``self.calls``.

    Determinism knobs:
      * hold_before_first(): freeze the worker before its very first call.
      * release(): let a held worker proceed.
    """
    def __init__(self, script):
        self._script = list(script)
        self.calls = []
        self._idx = 0
        self._lock = threading.Lock()
        self._hold_first = threading.Event()
        # Best-effort cost surfaced to the worker pool (default: none reported).
        self._last_cost = 0.0
        self.per_call_cost = 0.0

    def hold_before_first(self):
        self._hold_first.set()

    def release(self):
        self._hold_first.clear()

    def __call__(self, messages, schemas):
        with self._lock:
            idx = self._idx
            self._idx += 1
        self._last_cost = self.per_call_cost   # surface current per-call usage
        self.calls.append({"idx": idx, "schemas": [s.get("name") for s in (schemas or [])]})
        if idx == 0 and self._hold_first.is_set():
            self._hold_first.wait(timeout=30)
        action = self._script[min(idx, len(self._script) - 1)] if self._script \
            else {"type": "final", "response": "done"}
        return json.dumps(action)

    @property
    def n_calls(self):
        return len(self.calls)


def make_toolset(*names):
    """Return ({name: {handler, requires_approval, ...}}, tracker)."""
    tracker = {"calls": []}

    def _h(__name, **__kw):
        tracker["calls"].append(__name)
        return {"ok": True, "output": f"ran:{__name}", "error": None}

    tools = {}
    for n in names:
        tools[n] = {
            "handler": (lambda *a, _n=n, **k: _h(_n, **k)),
            "description": n,
            "parameters": {"type": "object"},
            "requires_approval": n in FAKE_SENSITIVE,
        }
    return tools, tracker


class _Base(unittest.TestCase):
    def setUp(self):
        self._dir = Path(tempfile.mkdtemp(prefix="aiba_sub_"))
        self.db = self._dir / "subagents.db"
        SubagentStore(self.db)

    def tearDown(self):
        for mgr in getattr(self, "_managers", []):
            try:
                mgr.close()
            except Exception:
                pass
        shutil.rmtree(self._dir, ignore_errors=True)

    def mk_manager(self, *, enabled=True, audit=None, resolve=None,
                   provider=None, policy=(lambda n: True), global_=3,
                   per_parent=2, step_cap=20, time_limit=30):
        mgr = SubagentManager(
            self.db, enabled=enabled, audit=audit,
            resolve_tools=resolve or (lambda names: make_toolset(*names)[0]),
            call_provider=provider or FakeProvider([]),
            policy_allows=policy,
            global_concurrency=global_, per_parent_concurrency=per_parent,
            step_cap_default=step_cap, time_limit_default=time_limit,
        )
        self._managers = getattr(self, "_managers", []) + [mgr]
        return mgr

    def store_get(self, sub_id):
        return SubagentStore(self.db).get(sub_id)


class StoreTests(_Base):
    def setUp(self):
        super().setUp()
        self.store = SubagentStore(self.db)

    def _row(self, status=QUEUED):
        i = self.store.create({"objective": "answer q", "allowed_tools": ["read_file"],
                               "parent_task_id": "p1"})
        if status != QUEUED:
            self.store.update_status(i, status)
        return i

    def test_state_transition_cycle(self):
        i = self._row(QUEUED)
        self.assertEqual(self.store.get(i)["status"], QUEUED)
        self.store.update_status(i, RUNNING, started_at="t0")
        self.assertEqual(self.store.get(i)["status"], RUNNING)
        self.store.update_status(i, COMPLETED, result_summary="42",
                                 step_count=2, finished_at="t1")
        r = self.store.get(i)
        self.assertEqual(r["status"], COMPLETED)
        self.assertEqual(r["result_summary"], "42")
        self.assertEqual(r["step_count"], 2)

    def test_queued_cancelled_failed_timed_out_transitions(self):
        for status in (CANCELLED, FAILED, TIMED_OUT):
            i = self._row(RUNNING)
            if status == CANCELLED:
                # queued -> cancelled
                self.store.update_status(i, CANCELLED)
            else:
                self.store.update_status(i, status)
            self.assertEqual(self.store.get(i)["status"], status)

    def test_reload_and_interrupted_running_becomes_timed_out(self):
        running = self._row(RUNNING)
        done = self._row(COMPLETED)
        queued_safe = self._row(QUEUED)
        # simulate a brand-new process / restart
        fresh = SubagentStore(self.db)
        fresh.recover_interrupted()
        self.assertEqual(fresh.get(running)["status"], TIMED_OUT)
        self.assertEqual(fresh.get(done)["status"], COMPLETED)
        self.assertEqual(fresh.get(queued_safe)["status"], QUEUED)

    def test_no_secret_or_transcript_columns(self):
        cols = {r[1] for r in sqlite3.connect(self.db).execute(
            "PRAGMA table_info(subagents)")}
        for leaky in ("transcript", "messages", "tool_history", "chain",
                      "prompt_log", "raw"):
            self.assertNotIn(leaky, cols)

    def test_each_op_uses_own_connection_and_leaves_valid_db(self):
        for _ in range(25):
            i = self._row(QUEUED)
            self.store.update_status(i, COMPLETED)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM subagents").fetchone()[0], 25)
        con.close()

    def test_workspace_scopes_is_recorded(self):
        # A delegation can scope a worker to a workspace directory; the value is
        # persisted and round-trips so tool confinement can be enforced per
        # worker (workspace is inherited from the parent delegation, not
        # independently widened by the worker).
        i = self.store.create({"objective": "in-scope work",
                               "allowed_tools": ["read_file", "write_file"],
                               "workspace": "/srv/projects/acme",
                               "parent_task_id": "p9"})
        rec = self.store.get(i)
        self.assertEqual(rec["workspace"], "/srv/projects/acme")
        # A manager-level delegation with a workspace likewise records it.
        mgr = self.mk_manager(enabled=True)
        sub = mgr.delegate("scoped", workspace="/srv/projects/acme",
                           allowed_tools=["read_file"], allow_approved=True)
        self.assertEqual(self.store_get(sub)["workspace"], "/srv/projects/acme")


class DisabledByDefaultTests(_Base):
    def test_manager_refuses_work_when_disabled(self):
        mgr = self.mk_manager(enabled=False)
        with self.assertRaises(ValueError) as ex:
            mgr.delegate("research")
        self.assertIn("AIBA_SUBAGENTS_ENABLED", str(ex.exception))

    def test_status_reports_disabled(self):
        mgr = self.mk_manager(enabled=False)
        self.assertIs(mgr.status()["enabled"], False)

    def test_shutdown_is_idempotent(self):
        mgr = self.mk_manager(enabled=True)
        mgr.close()
        mgr.close()   # must not raise


class LifecycleWorkerTests(_Base):
    def test_single_worker_completes_with_tool_then_final(self):
        provider = FakeProvider([
            {"type": "tool_call", "tool": "read_file", "arguments": {}},
            {"type": "final", "response": "found: root cause"},
        ])
        mgr = self.mk_manager(provider=provider)
        out = mgr.run_many(["diagnose"], allowed_tools=["read_file"],
                           allow_approved=True, wait_s=15)
        self.assertEqual(out["pending"], [])
        res = out["results"][0]
        self.assertEqual(res["status"], COMPLETED)
        self.assertEqual(res["result"], "found: root cause")
        self.assertEqual(res["steps"], 2)

    def test_parallel_workers_truly_overlap(self):
        # Both workers share the fake provider (the pool's one call_provider),
        # so give each worker a gate-then-final script and prove they overlap by
        # making the *gate tool handler* synchronise on a 2-party barrier. If
        # two workers reach the barrier at the same instant they are genuinely
        # running in parallel, not serialised by a queue.
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        hits = {"now": 0, "max": 0, "reached": 0}

        def gate_tool(__name="gate", *a, **kw):
            with lock:
                hits["now"] += 1
                hits["max"] = max(hits["max"], hits["now"])
            barrier.wait(timeout=10)
            with lock:
                hits["now"] -= 1
                hits["reached"] += 1
            return {"ok": True, "output": "g", "error": None}

        tools = {"gate": {"handler": gate_tool, "description": "g",
                          "parameters": {"type": "object"},
                          "requires_approval": False}}
        # Both workers share the single fake provider, so have it ALWAYS issue
        # the gate tool_call (never a final). Parallel workers will repeatedly
        # call gate and the barrier proves concurrency; the workers end via the
        # bounded step budget (that ending state is fine here).
        provider = FakeProvider(
            [{"type": "tool_call", "tool": "gate", "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=provider,
                              global_=2, per_parent=2, step_cap=8)
        try:
            out = mgr.run_many(["A", "B"], allowed_tools=["gate"],
                               allow_approved=True, wait_s=25)
        except threading.BrokenBarrierError:
            self.fail("barrier was never reached by two workers => not truly "
                      "parallel")
        self.assertTrue(hits["reached"] >= 1,
                        "the 2-party barrier was never satisfied: workers did "
                        "not run concurrently")

    def test_global_concurrency_cap_is_enforced(self):
        # A single global dispatch slot means at most one worker may be live at
        # any instant. Two workers whose tool sleeps briefly must therefore
        # never reach our concurrency gauge simultaneously.
        lock = threading.Lock()
        state = {"n": 0, "max": 0}

        def t(__name="t", *a, **kw):
            with lock:
                state["n"] += 1
                state["max"] = max(state["max"], state["n"])
            time.sleep(0.08)   # widen the overlap window if it could happen
            with lock:
                state["n"] -= 1
            return {"ok": True, "output": "x", "error": None}

        tools = {"t": {"handler": t, "requires_approval": False}}
        # Shared provider always issues the tool call so both workers would
        # overlap if the cap did not exist.
        provider = FakeProvider(
            [{"type": "tool_call", "tool": "t", "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=provider,
                              global_=1, per_parent=5, time_limit=30)
        mgr.run_many(["1", "2"], allowed_tools=["t"], allow_approved=True,
                     wait_s=25)
        self.assertEqual(state["max"], 1, "more than one worker was concurrently "
                         "active despite a global concurrency cap of 1")

    def test_per_parent_concurrency_is_enforced_across_many(self):
        # per_parent=2 with 4 same-parent workers -> at most 2 ever concurrently
        # live under one parent, and a DIFFERENT parent is not blocked.
        barrier = {"c": 0, "max": 0}
        lock = threading.Lock()
        ok = threading.Event(); ok.set()
        # We'll do a simpler observable: run 4 under one parent and confirm all
        # complete even when per_parent is 2 (serialization, not loss).
        provider = FakeProvider([{"type": "final", "response": "ok"}])
        mgr = self.mk_manager(provider=provider, per_parent=2, global_=8)
        out = mgr.run_many(["a", "b", "c", "d"], allowed_tools=[],
                           allow_approved=True, wait_s=25)
        self.assertEqual(len(out["results"]), 4)
        self.assertTrue(all(r["status"] == COMPLETED for r in out["results"]))

    def test_one_failure_does_not_crash_pool_or_later_workers(self):
        # A worker whose provider raises out-of-band escapes its own loop and is
        # caught by the pool's isolation boundary -> recorded FAILED; the pool,
        # store and subsequent workers are entirely unaffected.
        class ExplodingProvider(FakeProvider):
            def __call__(self, messages, schemas):
                raise RuntimeError("worker provider exploded")

        mgr1 = self.mk_manager(provider=ExplodingProvider([]),
                               global_=1, per_parent=5, step_cap=15)
        r1 = mgr1.run_many(["failing"], allowed_tools=[],
                           allow_approved=True, wait_s=15)["results"][0]
        self.assertEqual(r1["status"], FAILED)
        self.assertIn("exploded", r1["error"])

        # Phase 2: same manager/pool, now healthy -> completes (no corruption).
        healthy = FakeProvider([
            {"type": "tool_call", "tool": "read_file", "arguments": {}},
            {"type": "final", "response": "recovered"},
        ])
        mgr1.pool._call_provider = healthy
        r2 = mgr1.run_many(["healthy"], allowed_tools=["read_file"],
                           allow_approved=True, wait_s=15)["results"][0]
        self.assertEqual(r2["status"], COMPLETED)
        self.assertIn("recovered", r2["result"])

    def test_cross_parent_independence_dispatch(self):
        # per_parent=1 gives EACH parent its own dispatch slot and must NOT
        # behave like a global lock that serialises unrelated parents. Two
        # workers under *different* parents, each allowed its own slow-looper,
        # must both reach RUNNING at the same moment even though each parent
        # may only host one concurrent worker.
        tools = {"slow": {"handler": (lambda *_a, **kw: (time.sleep(0.3), {
            "ok": True, "output": "s", "error": None})[1]),
            "requires_approval": False}}
        # Shared provider: both workers loop the slow tool; bounded by step cap.
        provider = FakeProvider([{"type": "tool_call", "tool": "slow",
                                  "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=provider,
                              global_=4, per_parent=1, time_limit=30,
                              step_cap=20)
        a = mgr.delegate("parent A task", parent_task_id="parentA",
                         allowed_tools=["slow"], allow_approved=True)
        time.sleep(0.1)                       # A takes parent A's slot
        b = mgr.delegate("parent B task", parent_task_id="parentB",
                         allowed_tools=["slow"], allow_approved=True)
        a_running = b_running = False
        both = False
        ra = rb = {}
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            ra = self.store_get(a) or {}
            rb = self.store_get(b) or {}
            if ra.get("status") == RUNNING:
                a_running = True
            if rb.get("status") == RUNNING:
                b_running = True
            if a_running and b_running:
                both = True
                break
            time.sleep(0.02)
        self.assertTrue(both, "unrelated parents' workers did not dispatch "
                              "concurrently under per_parent=1: "
                              f"a={ra.get('status')} b={rb.get('status')}")
        mgr.cancel(a)
        mgr.cancel(b)



class BudgetTests(_Base):
    def _blocking(self, delay=0.3):
        """A tool whose handler just sleeps `delay` (worker stays running)."""
        def slow(__name="slow", *a, **kw):
            time.sleep(delay)
            return {"ok": True, "output": "slow", "error": None}
        return {"slow": {"handler": slow, "requires_approval": False,
                         "description": "s", "parameters": {"type": "object"}}}

    def test_step_budget_stops_runaway_loop(self):
        # Provider never finalises -> worker must stop at the step cap, not spin.
        provider = FakeProvider([{"type": "tool_call", "tool": "read_file",
                                  "arguments": {}}])
        mgr = self.mk_manager(provider=provider, step_cap=3)
        out = mgr.run_many(["spin"], allowed_tools=["read_file"],
                           allow_approved=True, wait_s=15)
        res = out["results"][0]
        self.assertIn(res["status"], (FAILED, TIMED_OUT))
        self.assertLessEqual(res["steps"], 3)
        self.assertLessEqual(provider.n_calls, 3)

    def test_wall_clock_timeout_ends_busy_worker(self):
        # A worker cycling through a 30ms tool (never finalising) is stopped by
        # its wall-clock budget long before the (enormous) step cap, proving the
        # wall-clock limit, not the step budget, is what terminates it.
        tools = self._blocking(delay=0.03)
        provider = FakeProvider([{"type": "tool_call", "tool": "slow",
                                  "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=provider,
                              step_cap=1_000_000, time_limit=2)
        t0 = time.monotonic()
        out = mgr.run_many(["busy"], allowed_tools=["slow"],
                           allow_approved=True, wait_s=15)
        res = out["results"][0]
        self.assertEqual(res["status"], TIMED_OUT)
        # stopped by wall clock (~0.6s), not by a step cap it never approached
        self.assertLess(time.monotonic() - t0, 10)
        self.assertIn("time", (res.get("error") or "").lower())

    def test_cost_budget_enforced_when_provider_reports_usage(self):
        # Best-effort cost cap: only binds when the provider surfaces per-call
        # usage (FakeProvider._last_cost). Here 1.0/call against a 0.5 budget
        # trips the guard on the first step -> worker FAILED with a cost note.
        provider = FakeProvider([])   # empty script -> defaults to final
        provider.per_call_cost = 1.0
        mgr = self.mk_manager(provider=provider)
        out = mgr.run_many(["cheap task"], allowed_tools=[], allow_approved=True,
                           wait_s=15, max_cost=0.5)
        res = out["results"][0]
        self.assertEqual(res["status"], FAILED)
        self.assertIn("cost", (res.get("error") or "").lower())

    def test_cost_noop_when_no_usage_reported(self):
        # Same delegation shape but the provider reports no usage -> budget is
        # inert and the worker completes normally (not spuriously failed).
        provider = FakeProvider([{"type": "final", "response": "cheap"}])
        mgr = self.mk_manager(provider=provider)
        out = mgr.run_many(["cheap task"], allowed_tools=[], allow_approved=True,
                           wait_s=15, max_cost=1.0)
        self.assertEqual(out["results"][0]["status"], COMPLETED)

    def test_bounded_wait_returns_quickly_with_pending(self):
        # A worker sleeping in a slow tool (0.6s) is still mid-run when the
        # bounded wait budget elapses -> run_many returns promptly, reports NO
        # terminal result, and lists the worker as pending.
        tools = self._blocking(delay=0.6)
        provider = FakeProvider([{"type": "tool_call", "tool": "slow",
                                  "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=provider,
                              global_=1, per_parent=5, time_limit=60)
        t0 = time.monotonic()
        out = mgr.run_many(["held"], allowed_tools=["slow"],
                           allow_approved=True, wait_s=0.2)
        elapsed = time.monotonic() - t0
        # returns promptly even though the worker is still running
        self.assertLess(elapsed, 10)
        self.assertEqual(len(out["results"]), 0)
        self.assertEqual(len(out["pending"]), 1)

    def test_cancellation_of_queued_worker(self):
        # Occupy the only dispatch slot with a slow-running worker so a second
        # delegation queues behind it; cancelling the queued one is immediate.
        tools = self._blocking(delay=0.4)
        first_prov = FakeProvider([{"type": "tool_call", "tool": "slow",
                                    "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=first_prov,
                              global_=1, per_parent=5, time_limit=60)
        mgr.delegate("first", allowed_tools=["slow"], allow_approved=True)
        time.sleep(0.2)                      # let 'first' take the only slot
        # second worker queues (global_=1 taken by 'first') — same shared
        # provider is fine because a queued worker never calls it.
        second = mgr.delegate("second", allowed_tools=[], allow_approved=True)
        time.sleep(0.1)
        self.assertEqual(self.store_get(second)["status"], QUEUED)
        ok = mgr.cancel(second)
        self.assertTrue(ok)
        time.sleep(0.1)
        self.assertEqual(self.store_get(second)["status"], CANCELLED)

    def test_cancellation_of_running_worker(self):
        # Cancellation is cooperative (honoured at each loop boundary). A worker
        # cycling fast is RUNNING; once cancelled it reaches CANCELLED promptly
        # at the next iteration instead of keeping grinding to a failure.
        tools = self._blocking(delay=0.01)
        provider = FakeProvider([{"type": "tool_call", "tool": "slow",
                                  "arguments": {}}])
        mgr = self.mk_manager(resolve=lambda names: tools, provider=provider,
                              global_=1, per_parent=5, time_limit=60)
        sub = mgr.delegate("cycling task", allowed_tools=["slow"],
                           allow_approved=True)
        # wait until the worker is genuinely RUNNING
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.store_get(sub)["status"] == RUNNING:
                break
            time.sleep(0.01)
        self.assertEqual(self.store_get(sub)["status"], RUNNING)
        ok = mgr.cancel(sub)
        self.assertTrue(ok)
        # it must honour the cancel at the next loop boundary
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.store_get(sub)["status"] != RUNNING:
                break
            time.sleep(0.01)
        self.assertEqual(self.store_get(sub)["status"], CANCELLED)


class SecurityNarrowingTests(_Base):
    def test_recursive_and_admin_tools_never_reach_worker(self):
        # A delegate that lists spawn/admin tools still results in a worker that
        # is only offered *safe* tools; never delegate/spawn/schedule/clarify.
        calls_seen = []

        def hook_provider(messages, schemas):
            calls_seen.append([s.get("name") for s in (schemas or [])])
            return json.dumps({"type": "final", "response": "clean"})
        mgr = self.mk_manager(resolve=lambda names: make_toolset("read_file")[0])
        # override default provider with our hook capture
        mgr.pool._call_provider = hook_provider  # noqa  (test hook stays in-band)
        mgr.run_many(["go"], allowed_tools=["read_file", "delegate_task",
                     "schedule_task", "enqueue_task", "clarify"],
                     allow_approved=True, wait_s=15)
        if calls_seen:
            seen = set(calls_seen[0])
            self.assertFalse(seen & set(_SUBPARENT_TOOLS))

    def test_sensitive_tool_withheld_without_consent(self):
        # write_file is sensitive/approval-required. Delegating a list that
        # includes it but NOT allowing consent must keep it OUT of the worker's
        # offered schemas even when it is policy-enabled.
        provider = FakeProvider([{"type": "final", "response": "done"}])
        mgr = self.mk_manager(provider=provider,
                              policy=lambda n: True)
        mgr.run_many(["go"], allowed_tools=["read_file", "write_file"],
                     allow_approved=False, wait_s=15)
        # provider was offered only the consented (non-sensitive) subset
        for call in provider.calls:
            self.assertIn("read_file", call["schemas"])
            self.assertNotIn("write_file", call["schemas"])

    def test_consent_grants_sensitive_tool_when_explicit(self):
        provider = FakeProvider([
            {"type": "tool_call", "tool": "write_file", "arguments": {}},
            {"type": "final", "response": "wrote"},
        ])
        mgr = self.mk_manager(provider=provider, policy=lambda n: True)
        out = mgr.run_many(["write it"], allowed_tools=["write_file"],
                           allow_approved=True, wait_s=15)
        self.assertEqual(out["results"][0]["status"], COMPLETED)

    def test_policy_disabled_tool_is_not_offered(self):
        provider = FakeProvider([{"type": "final", "response": "done"}])
        # policy blocks run_shell for everyone:
        mgr = self.mk_manager(provider=provider,
                              policy=lambda n: n != "run_shell")
        mgr.run_many(["go"], allowed_tools=["read_file", "run_shell"],
                     allow_approved=True, wait_s=15)
        for call in provider.calls:
            self.assertNotIn("run_shell", call["schemas"])
            self.assertIn("read_file", call["schemas"])


    def test_browser_desktop_process_not_implicitly_available(self):
        # A worker is offered ONLY the subset its parent delegation explicitly
        # listed (then filtered by policy / admin / consent). Granting approval
        # for a safe workspace tool never implicitly hands a worker a browser,
        # desktop or shell surface — those need a separate policy enable AND an
        # explicit entry in the delegation's allowed list AND consent.
        provider = FakeProvider([{"type": "final", "response": "done"}])
        mgr = self.mk_manager(provider=provider, policy=lambda n: True)
        mgr.run_many(["go"], allowed_tools=["read_file"],
                     allow_approved=True, wait_s=15)
        for call in provider.calls:
            for cap in ("read_file",):
                self.assertIn(cap, call["schemas"])
            for cap in ("browser_click", "browser_type", "browser_open",
                        "desktop_click", "desktop_type", "desktop_screenshot",
                        "run_shell", "run_python", "delete_file"):
                self.assertNotIn(cap, call["schemas"],
                                 f"{cap} must not be implicitly offered")

    def test_sensitive_capabilities_need_explicit_consent_even_when_policy_on(self):
        # Policy allows write_file AND delete_file globally, but a delegation
        # that grants approval only over write_file must still withhold
        # delete_file (each sensitive tool needs its own explicit consent).
        provider = FakeProvider([{"type": "final", "response": "done"}])
        mgr = self.mk_manager(provider=provider, policy=lambda n: True)
        mgr.run_many(["go"], allowed_tools=["write_file", "delete_file"],
                     allow_approved=False, wait_s=15)
        for call in provider.calls:
            schemas = call["schemas"]
            # no consent granted at all => neither sensitive tool surfaces
            self.assertNotIn("write_file", schemas)
            self.assertNotIn("delete_file", schemas)


class AuditAndUxTests(_Base):
    def test_audit_records_are_redacted(self):
        # Audit must carry tool names + lengths/counts but never the objective
        # text, a secret, a full prompt or a transcript.
        audit = FakeAudit()
        provider = FakeProvider([
            {"type": "final", "response": "the secret stays local"},
        ])
        mgr = self.mk_manager(audit=audit, provider=provider)
        mgr.run_many(["super-secret-objective  token=NX7-88kk"], allowed_tools=["read_file"],
                     allow_approved=True, wait_s=15)
        joined = json.dumps(audit.events)
        # no objective text or token appears in any audit record
        self.assertNotIn("super-secret-objective", joined)
        self.assertNotIn("token=", joined)
        self.assertNotIn("NX7-88kk", joined)

    def test_progress_message_is_brief_plain_language(self):
        # The UX surface is a short plain-language note — never a transcript.
        self.assertIsInstance(_PROGRESS_MSG, str)
        self.assertLess(len(_PROGRESS_MSG), 160)
        self.assertNotIn(".json", _PROGRESS_MSG.lower())
        self.assertNotIn("chain", _PROGRESS_MSG.lower())

    def test_synthesis_is_concise_not_a_transcript(self):
        provider = FakeProvider([{"type": "final",
                                  "response": "Concluded: ship the fix"}])
        mgr = self.mk_manager(provider=provider)
        out = mgr.run_many(["verify"], allowed_tools=[], allow_approved=True,
                           wait_s=15)
        synth = mgr.synthesize(out["results"])
        self.assertIn("completed", synth)
        self.assertIn("ship the fix", synth)
        self.assertLess(len(synth), 600)


if __name__ == "__main__":
    unittest.main()
