# Execution and learning acceptance — October 28, 2026

## Recovery contract

Job enqueue defaults to `retry_policy='owner_review'`, including existing rows migrated without a policy. A handler exception or stale claim becomes `needs_review`, never an automatic replay. Trusted application code may explicitly declare a read-only or independently idempotent operation `safe`; only those jobs retry within the attempt limit. The queue's idempotency key deduplicates enqueue occurrences, **not external effects**. No generic external API idempotency guarantee is claimed.

Workers check their claim before/after the handler and the runtime checks cancellation/claim loss before provider calls, after provider returns, and before dispatch (including after approval). Cancellation prevents subsequent dispatches; it cannot undo or interrupt an already-running external request. A stale handler's result cannot complete a newer claim. An uncertain job remains for operator reconciliation; there is no automatic requeue of that job.

Plan steps persist a fingerprint and running state before dispatch. Already attempted steps cannot be dispatched again, including verified steps. Pending steps can resume through `AgentLoop.resume_task(task_id, user_id)` or the authenticated operator `POST /v1/tasks/{id}/resume` with `owner`. The operator bridge must bind owner identity; this is not a public end-user authentication endpoint.

For unresolved steps, inspect the actual destination first. `POST /v1/tasks/{id}/reconcile-step` accepts owner, index, exact fingerprint and resolution `verified` (operator attests outcome) or `retry` (operator attests replay is safe). The decision is saved and cannot be replayed while the step is pending. This does not grant tool permissions: each dispatch still traverses the registry and exact approval checks. Plans without independent postconditions remain executed, not verified. Generic successful dispatch is not certification of arbitrary real-world outcomes.

## Learning contract

`POST /v1/tasks/{id}/propose-workflow` is authenticated operator-only, accepts owner and explicit feedback, and requires three completed owner-matched traces with every recorded tool result verified. It produces an advisory proposal with source task IDs and no executable steps. Matching tool sequences do not prove matched intent or complete arguments. Existing individual-task suggestions remain advisory observations, not learned executable skills.

Review must supply complete schema-valid arguments. Installation binds the exact reviewed digest; it grants no execution privileges. Runtime execution blocks recursive run_skill and installation, approval, or policy-change tool names in addition to inherited owner restrictions. Arbitrary host/command capabilities still require their own gates and are not certified safe merely by being inside a skill.

Matched regression test criteria are fixed before execution: the exact requested file content must exist for each of Atlas, Budget, Notebook; blocked writes must fail. Baseline passes 3/3 positive cases; deliberately regressed candidate passes 0/3 despite successful dispatch. Both refuse blocked writes. Rollback restores baseline steps. This demonstrates regression detection, not general learning improvement. Aggregate skill dispatch statistics are explicitly not task-quality certification.

## Reproduction and limits

`PYTHONPATH=.:tests python -m unittest test_execution_learning_acceptance test_execution_plans test_execution_recovery_acceptance test_scheduler_reliability test_skill_lifecycle test_skill_outcomes test_web`

The acceptance suite uses actual AgentLoop, registry, stores, worker, approvals, and workspace operations. Only model completions and unavailable web transport/DNS are scripted in deterministic tests. It tests crash-equivalent durable claims; it does not claim live external process interruption certification.

Live attempt using actual `WebTools().web_extract(['https://github.com/aibatech/aiba-agent'])` returned `ok=false`, `verified=null`, blocked SSRF target: this environment could not establish an allowed public resolution. No DNS bypass or mocked result counts as live certification. Extraction now fails when any requested page has a non-2xx status or empty readable content; usable pages remain visible as partial evidence.

Remaining gaps: real-model planning quality; live public retrieval; domain verifiers for desktop/messaging/command effects; external idempotency/reconciliation adapters; immediate cancellation of in-flight remote work; broader matched learning evaluation and security of arbitrary host execution. These keep E1/E3/E8/E10 and L1/L3/L10 open under the existing rubric. No score inflation.

Additional adapter postconditions: remember/update_memory read back owner-scoped fields; delete_memory checks absence after a successful deletion; export_memories compares the actual file bytes with the generated scoped export; enqueue_task and schedule_task read back the stored kind, payload, owner and schedule interval. A lying dispatcher or no-op database update fails verification. Queue/schedule verification proves durable registration, not that future work has already executed.

Evidence enrichment reuses an existing advisory proposal produced by the runtime, but never replaces reviewed/installed contents. The acceptance suite exercises three actual runtime write tasks (scripted provider only), then enriches their proposal and verifies review immutability. Resume claims the task status atomically; active tasks cannot be reconciled through the operator endpoint.

## Intent-aware owner feedback (November 13)

The authenticated **operator** API now accepts `POST /v1/tasks/{task_id}/feedback` with `owner`, `workflow_id`, `accepted` (boolean), and optional `note`. A trusted backend must bind the owner to its authenticated user before invoking the operator API. This endpoint is not a model tool. Feedback persists in `task_feedback`, survives restart, and participates in owner erasure/backup redaction. It cannot mark another owner's task accepted or claim success for an incomplete/failed task.

Before requesting `/v1/tasks/{task_id}/propose-workflow`, the operator must label at least three verified successful tasks with the same explicit workflow identity and accepted feedback. Different intents remain separate even if tool sequences are identical. The latest 100 labeled outcomes form the bounded cohort. A rejected, unsuccessful, unverified or divergent outcome blocks that cohort; investigate it rather than discarding it to earn a pass. A genuinely revised workflow uses a separately reviewed identity. Correcting an inaccurate assessment is explicit operator input, not automatic model feedback.

The proposal remains advisory with no reconstructed arguments. Its digest binds the exact evidence rows and feedback. Review and installation revalidate this evidence against the durable task store, including after restart. Later feedback or outcome changes invalidate a pending review; create and review a fresh proposal from current evidence. This does not automatically revoke an already installed skill or grant any execution permission. Existing exact review approval, tool permissions, versioning and rollback apply.

Versioned acceptance corpus: `benchmarks/learning/v1.json`. Thresholds were recorded before execution: nine verified outcomes, three exact cohorts, zero cross-intent matches, zero automatically executable proposals. Project notes, shopping notes (same tool, different intent), and durable preferences run through the actual AgentLoop, registry, stores and file/memory postconditions. Only provider tool selection is scripted. `python -m unittest discover -s tests -p test_learning_feedback.py` also exercises negative feedback, changed evidence, restart, authenticated API, owner isolation, erasure and refusal to install a previously reviewed candidate after rejection. Existing matched baseline/candidate, permission-enforced lifecycle and rollback tests remain required. This establishes owner-labeled reusable workflow identification, not live-model intent inference or general learning improvement.
