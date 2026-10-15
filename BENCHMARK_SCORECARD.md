# AIBA benchmark scorecard

## Objective rubric

Each benchmark has the ten requirements from the owner specification, worth one point each. PASS requires an implemented path and passing reproducible tests for the entire stated scope. GAP (including partial implementation, missing evidence, skipped required tests, or an external blocker) earns zero. No fractional or inferred credit. Mocked integration evidence certifies only the documented mock boundary, never live accounts or physical devices. These are verified lower bounds, not estimates of product quality.

Target for every benchmark: **10/10**. Release status: **NOT FULLY CERTIFIED**.

| Benchmark | Target | Verified score | Evidence | Remaining gaps |
|---|---|---|---|---|
| Memory | 10/10 | 6/10 | Requirement register below | 4 requirements |
| Autonomous Execution | 10/10 | 6/10 | Requirement register below | 4 requirements |
| Self-Improvement | 10/10 | 6/10 | Requirement register below | 4 requirements |
| Privacy & Security | 10/10 | 4/10 | Requirement register below | 6 requirements |
| Human-Centered UX | 10/10 | 5/10 | Requirement register below | 5 requirements |
| Production Reliability | 10/10 | 7/10 | Requirement register below | 3 requirements |

## Memory

Test filenames refer to `tests/` unless a different path is shown.

| # | Requirement | Status | Evidence | Scope / gap |
|---|---|---|---|---|
| 1 | Persistent conversations | PASS | test_conversation_learning.py; test_mission_e2e.py | Restart and scoped history |
| 2 | Durable goals/preferences/projects | PASS | test_conversation_learning.py; test_mission_e2e.py | Conservative learner; not all dialogue is durable |
| 3 | Semantic retrieval | GAP | memory/retrieval.py | Opt-in local embedding and hybrid retrieval implemented (test_memory_semantics.py); real model quality gate outstanding |
| 4 | Context selection/prioritization | GAP | memory/vault.py | Hybrid relevance, importance and character budget tested; real contextual relevance corpus missing |
| 5 | Updates/corrections | PASS | test_memory_edit.py; test_memory_recovery_acceptance.py | Corrections survive source resync and restart |
| 6 | Duplicate/conflicting memories | PASS | test_memory_semantics.py; test_memory_recovery_acceptance.py | Owner-scoped dedupe and explicit fact-key supersession, persistent auditable history and deletion |
| 7 | Deletion/privacy controls | GAP | test_memory_recovery_acceptance.py | Search deletion persists; source files, reflections and historical backups need unified erasure policy |
| 8 | User isolation | PASS | test_memory_user_isolation.py; test_memory_ownership.py | Trusted backend must bind header identity to signed-in user |
| 9 | Persistence after restart | PASS | test_mission_e2e.py | Real runtime restart with scripted provider |
| 10 | Backup/restore/migration | GAP | test_v13.py; test_memory_recovery_acceptance.py | Full-profile restore and injected-failure rollback tested (test_full_profile_backup.py); external disaster drill and cross-process consistency outstanding |

## Autonomous Execution

Test filenames refer to `tests/` unless a different path is shown.

| # | Requirement | Status | Evidence | Scope / gap |
|---|---|---|---|---|
| 1 | Multi-step planning | GAP | test_mission_e2e.py | Tool sequences work; planner quality and plan recovery benchmark missing |
| 2 | Tool discovery/execution | PASS | test_capability_integration.py; test_mission_e2e.py | Policy and feature flags enforced |
| 3 | Web research | GAP | test_web.py | Mock coverage; live retrieval certification outstanding |
| 4 | File/workspace operations | PASS | test_sandbox.py; test_mission_e2e.py | Actual write and read-back |
| 5 | Command/code execution | PASS | test_terminal_backends.py; test_sandbox.py | Supported local test paths; remote host certification separate |
| 6 | Background/scheduled work | PASS | test_scheduling_intent.py; test_v02.py; test_scheduler_reliability.py | Concurrent ticks and crash after enqueue deduplicated; stale worker completion fenced |
| 7 | Progress/status | PASS | test_protocol.py; test_execution_recovery_acceptance.py | Events and persistent task/job state |
| 8 | Retry/timeout/cancellation/recovery | GAP | test_execution_recovery_acceptance.py | Queue retries/cancel/recovery tested; in-flight external cancellation and safe replay remain |
| 9 | Sensitive authorization | PASS | test_exact_owner_approvals.py; test_approval_replay.py | Exact operation approval through registry |
| 10 | Verified completion claims | GAP | test_mission_e2e.py | Provider failures now fail; model-authored success still needs outcome verifier |

## Self-Improvement

Test filenames refer to `tests/` unless a different path is shown.

| # | Requirement | Status | Evidence | Scope / gap |
|---|---|---|---|---|
| 1 | Learning from outcomes | GAP | agent/conversation_review.py | Outcome review signals exist; adaptive policy not demonstrated |
| 2 | Explicit owner feedback | PASS | test_skill_lifecycle.py; test_conversation_review.py | Feedback retained in reviewed proposal |
| 3 | Reusable successful workflows | GAP | skills/improver.py | Tool names are observations, not a reconstructed executable workflow |
| 4 | Skill proposals | PASS | test_skill_proposal_safety.py | Advisory, non-executable by default |
| 5 | Review/validation | PASS | test_skill_lifecycle.py | Known available tools and schema-valid arguments required |
| 6 | Owner approval before installation | PASS | test_skill_lifecycle.py | Authenticated operator API plus exact review digest; no model tool for approval |
| 7 | Permission-enforced execution | PASS | test_skill_lifecycle.py | Installation grants no execution privileges |
| 8 | Versioning/rollback | PASS | test_skill_versioning.py; test_skill_lifecycle.py | Prior version restored; traversal rejected |
| 9 | Measured improvement | GAP | No retained comparative benchmark | Need fixed task corpus, baseline and learned runs, success/cost/latency deltas |
| 10 | Unsafe self-modification prevention | GAP | test_agent_skills_guard.py | Registry gates retained; filesystem race and host execution boundaries not fully certified |

## Privacy & Security

Test filenames refer to `tests/` unless a different path is shown.

| # | Requirement | Status | Evidence | Scope / gap |
|---|---|---|---|---|
| 1 | Authentication/authorization | PASS | test_product_bridge.py; api_smoke.py | Internal bridge bearer token and required user identity; not end-user authentication |
| 2 | Least privilege | PASS | test_security_policy_contract.py; test_capability_manifest.py | Disabled/unlisted capabilities denied |
| 3 | Exact operation approval | PASS | test_exact_owner_approvals.py; test_skill_lifecycle.py | All policy-gated tools now use argument fingerprints |
| 4 | One-use expiring grants | PASS | test_approval_replay.py; test_product_bridge.py | Durable product challenges; concurrent/restart/user/replay tests |
| 5 | Secret handling | GAP | test_secret_admin.py | Windows handle defect fixed; complete dotenv grammar and Windows ACL certification outstanding |
| 6 | Sensitive redaction | GAP | test_registry_redaction.py | Raw audit errors and reasoning output/response previews withheld; nested-list secrets tested; remaining diagnostic surfaces need leakage corpus |
| 7 | Host filesystem/command safeguards | GAP | test_host_files.py; test_skill_lifecycle.py | Path checks exist; adversarial TOCTOU race certification outstanding |
| 8 | Prompt injection defense | GAP | reasoning/engine.py | Untrusted-data instruction and policy gates; no adversarial model corpus certification |
| 9 | Confidential audit trail | GAP | test_registry_redaction.py | Tool/task argument redaction tested; all diagnostic surfaces not certified |
| 10 | Recovery/owner deletion | GAP | test_memory_recovery_acceptance.py | Approval invalidation on restore; full-data erasure and recovery still incomplete |

## Human-Centered UX

Test filenames refer to `tests/` unless a different path is shown.

| # | Requirement | Status | Evidence | Scope / gap |
|---|---|---|---|---|
| 1 | First-time onboarding | PASS | test_ux.py | Automated setup tests |
| 2 | Provider/model setup | PASS | test_provider_onboarding.py | Atomic provider connection and recovery paths |
| 3 | Natural conversation | GAP | test_mission_e2e.py | Continuity tested; real model/user quality evaluation missing |
| 4 | Consistent personality | PASS | test_personality.py | Existing personality tests retained |
| 5 | Voice | GAP | test_product_bridge.py | Voice-originated text envelope only; microphone/STT/TTS/interruption external |
| 6 | Accessible web/mobile | GAP | aibatech/aiba_app_full | Separate client repository located; accessibility/device tests not run |
| 7 | Messaging integrations | GAP | test_messaging_adapters.py | Mocks pass; live Telegram/WhatsApp certification missing |
| 8 | Task progress | PASS | test_protocol.py | Sanitized event protocol retained |
| 9 | Understandable permissions | GAP | test_product_bridge.py | Challenge contract implemented; client confirmation UX integration outstanding |
| 10 | Friendly error recovery | PASS | test_provider_onboarding.py; test_mission_e2e.py | Provider failures surfaced; HTTP rate limiting returns actionable 429 |

## Production Reliability

Test filenames refer to `tests/` unless a different path is shown.

| # | Requirement | Status | Evidence | Scope / gap |
|---|---|---|---|---|
| 1 | Windows | PASS | docs/certification/ci-summary.json | Python 3.11–3.13 at implementation SHA 42fcc78 |
| 2 | macOS | PASS | docs/certification/ci-summary.json | Python 3.11–3.13 at implementation SHA 42fcc78 |
| 3 | Linux | PASS | scripts/certify_install.py; docs/certification/linux-x86_64.json | Local compile, suite, clean-profile doctor |
| 4 | Cloud/VPS | GAP | Container CI is separate from deployed VPS | Live ready/restore drill not run |
| 5 | Automated tests | PASS | scripts/certify_install.py | Unit/integration/security suite |
| 6 | End-to-end acceptance | PASS | test_mission_e2e.py; test_skill_lifecycle.py | Deterministic real runtime, scripted provider; live cases remain scoped separately |
| 7 | Provider failure/recovery | PASS | test_mission_e2e.py; test_provider_onboarding.py | Failure status and background propagation; mocked provider |
| 8 | Database integrity/migration/restore | PASS | test_v13.py; test_memory_recovery_acceptance.py | Database-only scope; restore requires stopped service |
| 9 | Performance/concurrency/soak | GAP | docs/certification/runtime-load.json | 30-second HTTP load is not the required one-hour leak-monitored soak |
| 10 | Install/upgrade/rollback/release | GAP | PRODUCTION_GATE.md | Signing identities, final artifact hashes and release rollback drill outstanding |
