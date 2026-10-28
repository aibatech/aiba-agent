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
