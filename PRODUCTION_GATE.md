# AIBA Agent production gate

No item may be marked passed without retained machine-readable evidence. “Automated” means the gate exists; it does not mean an unexecuted external test passed.

| Gate | Command or evidence | Release requirement |
|---|---|---|
| Unit and concurrency | `python -m unittest discover -s tests` | All pass |
| Clean OS installation | `python scripts/certify_install.py` on Windows 11 x86-64, macOS Apple silicon, Ubuntu LTS x86-64 | Certification JSON from every target |
| Docker/VPS | CI container job and deployed `/ready` | Pass |
| Live providers | Manually authorized `live-providers.yml` | Every advertised provider passes; API spend approved |
| Load | `python tests/load_test.py --requests 1000 --concurrency 25` | Zero errors, p95 at most 500 ms on `/health` |
| Soak | `python tests/load_test.py --duration 3600 --concurrency 10` | Zero errors or leaks |
| Security | dependency audit, Bandit, secret scan, container scan | No unresolved high or critical finding |
| Database upgrade | migration tests and `python main.py --migrate` | Target versions and integrity pass |
| Backup/restore | v1.3 round-trip tests plus deployment restore drill | Verified restore and safety backup |
| Observability | `/ready`, authenticated `/metrics`, crash ID drill | Metrics scraped and alert receiver tested |
| Signed release | tagged-release workflow | Valid Windows/macOS signatures, provenance, SHA-256 |
| Skills/adapters | Individual compatibility certification | Only certified formats/adapters advertised |

## External evidence still required

Clean Windows/macOS computers or hosted runners must execute the certification workflow. Live API tests require owner-authorized provider secrets and incur provider usage. Authenticode and Apple Developer Installer identities must be supplied by AIBA Technologies. These gates cannot be honestly completed in a Linux development container.

## Release decision

A stable tag is permitted only when every required job passes and `certification/RELEASE_CANDIDATE.json` names the exact commit, artifact SHA-256, target environments, provider test results, open security findings, rollback result, and approver. Missing evidence means Beta or Release Candidate—not Production Certified.

## 2026-10-15 engineering remediation evidence

The inspected PR #34 head was `4f1ea2222dc45682041c711d4ad0d63531349829`; no newer commits existed at inspection. Default branch was `e8c01f43b39adddd4b590ac8328fb3ecb546474e`. PR remains draft and must not be merged or deployed without owner approval.

- Baseline: 428 unit tests, 8 optional-dependency skips on Linux.
- Baseline [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38680119058): Windows 3.11/3.12 failed secret-copy cleanup; the unsupported `fchmod` path left a descriptor open. Fixed with platform-aware permission handling inside the closing file context.
- First implementation commit: `d0d8a94716dbdfd01c7906533aa9a2db564a4470`. [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38681108541): all nine OS/Python jobs, security and container passed. Capability Pyright failed on a new ContextVar annotation; the follow-up explicitly types the outcome context. Earlier green jobs do not certify a later SHA.
- Local Pyright 1.1.411: zero errors. Bandit high-severity scan: passed. `pip-audit --strict -r requirements.txt`: no known vulnerabilities. Capability validator and secret scanner passed.
- Retained local reports: `docs/certification/`. Short real HTTP load: 12,350 successful requests, zero errors, 25 concurrent clients, p95 77.96 ms. **Not** the required one-hour soak or a model/task latency benchmark.
- New deterministic integrated scenarios: `tests/test_mission_e2e.py`, `test_skill_lifecycle.py`, `test_memory_recovery_acceptance.py`, `test_approval_replay.py`, `test_execution_recovery_acceptance.py`. Scripted providers/mocked accounts are labeled; no live-provider certification claimed.

See `BENCHMARK_SCORECARD.md` for all sixty requirements and the scoring rubric; `docs/INSTALL_UPGRADE_RC.md` for installation, the breaking approval contract, migration and rollback. Remaining implementation gaps include semantic retrieval, conflict resolution, full owner erasure, outcome-based learning measurement, scheduler crash/idempotency guarantees, filesystem race protection, and comprehensive log/injection threat tests. External gates include client/voice/accessibility/messaging devices, live providers, deployed VPS restoration, a one-hour leak-monitored soak and signed artifacts.

**Decision: NOT FULLY CERTIFIED.** This work is an engineering candidate, not authorization for a stable release. Do not interpret a local JSON `certified: true` as six-benchmark certification.

## Final observed implementation CI

Implementation `42fcc78fb459d939bf914f1084110c428305f25a`: [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38681728084) **passed all 12 jobs**, including nine OS/Python matrix jobs, security, container and capability checks. [MCP Integration](https://github.com/aibatech/aiba-agent/actions/runs/38681728190) **passed**. Retained job identifiers are in `docs/certification/ci-summary.json`. Local optional-dependency run: 442 tests, one platform-specific skip (`test_windows_permissions_not_faked`, intentionally off-POSIX only). No missing dependency was silently counted as live certification. These results do not close the remaining code and external gates.

Final schema follow-up: nested object optional/unknown-property regression and authenticated skill review/install/rate-limit tests pass. Final local run: 444 tests, 3 optional/platform skips. The retained CI snapshot names its exact implementation SHA; it must not be silently interpreted as a later commit result.

## Additional remediation evidence — 2026-10-15

Local suite: **455 tests, 3 skips, zero failures** (`python -m unittest discover -s tests`). Implemented optional local semantic retrieval/cache, bounded hybrid context, explicit owner-scoped fact supersession/history, full-profile backup with verified staging and caught-failure rollback, durable scheduled-occurrence deduplication, worker heartbeat/claim fencing and periodic stale recovery. Removed raw tool errors from registry audit and raw output/response/error previews from reasoning telemetry; nested lists now receive credential-key redaction.

New regression modules: test_memory_semantics.py, test_full_profile_backup.py, test_scheduler_reliability.py; expanded test_protocol.py and test_registry_redaction.py. The semantic fixture is deterministic, not a real-model quality certification. Backup restores do not erase extra files or provide multi-file power-loss atomicity. External action replay still requires reconciliation. Latest code requires new CI evidence; earlier green runs do not certify these changes. Scores: Memory 6, Execution 6, Learning 6, Security 4, UX 5, Reliability 7. **Not fully certified; not approved for production deployment.**

Follow-up: local suite now **458 tests, 3 skips, zero failures**. Added POSIX descriptor-relative host read/write/delete, bounded reads and atomic replacement writes; adversarial ancestor-swap and hard-link regression tests pass. Windows keeps atomic writes and bounded reads, but equivalent descriptor-relative race guarantees are not certified. Fixed backup failure-injection test to compare canonical paths on macOS and Windows; no test was skipped to bypass the failure.

### Verified CI and discovery correction

Implementation `7d659ab8c88d2b51c080c2553547c6095a688360`: [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38733650290) passed all 12 jobs (nine OS/Python combinations, security, capabilities/types and container). [MCP SDK integration](https://github.com/aibatech/aiba-agent/actions/runs/38733650315) passed.

Final discovery correction adds eight existing function-style tests to unittest discovery. They previously were not executed by that runner. Their default-permission check exposed enabled host-file defaults; host file tools now require owner opt-in as well as exact approval. The corrected local suite ran **466 tests, zero failures, nine skips** in the base runtime (optional API/MCP dependencies unavailable after environment reset). Earlier 458-test run used API dependencies and skipped three. New CI is required for this final correction; no optional capability is claimed tested merely because its test skipped.

## Continued implementation (post-e034db8)

472 local tests, zero failures, nine optional/platform skips. New tests cover false-positive write claims, read-back/absence postconditions, scoped erasure with restore suppression, confirmation mismatch, confidential reflection retention, skill failure propagation and inherited blocked tools. Earlier final e034db8 CI passed: [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38788437418), [MCP](https://github.com/aibatech/aiba-agent/actions/runs/38788437357). New code requires its own CI.

Isolated Runtime Soak workflow now executes 3600 seconds of HTTP load with Linux process RSS sampling and a 64 MiB post-warmup growth budget. Passing it supports only the health-endpoint workload, not live model tasks or a universal absence-of-leaks claim. No result is asserted until the workflow completes.

## Retained one-hour soak and continued learning/privacy work

Commit 68dcd8d passed [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38792898735), [MCP](https://github.com/aibatech/aiba-agent/actions/runs/38792898605), and [Isolated Runtime Soak](https://github.com/aibatech/aiba-agent/actions/runs/38792886989). Retained full RSS samples: docs/certification/runtime-soak-68dcd8d.json. Results: 3600.06 seconds; 4,223,100 successes; zero errors; p95 30 ms; 884,736-byte post-warmup RSS growth. Artifact SHA-256: 63321abeee4e1c59d7bfe585ae3c91071079f05079b44a5a9f1e26eb4644776d. This is an HTTP health-workload gate, not a model throughput claim.

Further implementation adds owner-scoped skill outcome history/comparison and authenticated reporting; real matched-file workflow regression (3/3 baseline and candidate outcomes, tool calls reduced from 3 to 2); attributed profile/reflection/proposal deletion with restored-copy suppression; persisted step plans with incomplete-work gating. No automatic skill promotion or claim of general learning quality. Remaining criteria stay explicitly open in the scorecard.

## Diagnostic privacy, secret transfer and planned delegation

Verified parent c39eff6 passed [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38850441114) and [MCP SDK integration](https://github.com/aibatech/aiba-agent/actions/runs/38850441123).

Further repairs withhold raw exception messages, source lines, request paths, free-form audit payload fields and unsupported object representations. Audit records retain action fingerprints. Secret transfer recognizes export/whitespace assignments, preserves quoted single-line values, refuses duplicate source assignments, multiline/malformed values and invalid UTF-8 before writing, and omits exception contents from errors. Planned legacy delegation now validates its plan index before dispatch and records progress/results through the same durable plan interface.

Validation: `python -m unittest discover -s tests`: 484 tests, zero failures, 10 optional/platform skips. Capability consistency and repository secret scan passed. Regression coverage includes tests/test_diagnostic_privacy.py, test_secret_admin.py and test_execution_plans.py. Tests use synthetic secrets and a headless screenshot fixture, not physical device certification. New implementation requires its own CI. Benchmark scores remain 6/6/7/4/5/8; arbitrary strings in unknown audit fields, external logs, full dotenv grammar, Windows ACL/race protection, live providers and client/hardware certification remain outside this evidence. No merge or deployment performed.

### Secret transfer descriptor hardening

Secret reads are limited to 1 MiB and regular files. POSIX source reads and destination read/atomic replacement now use pinned ancestor descriptors and no-follow opens; temporary files remain mode 0600. Regression tests reject replacement source symlinks, keep destination-parent swaps from redirecting secrets, and reject FIFOs without blocking. Windows retains the portable path implementation and does not inherit the POSIX race guarantee. Full suite: 488 tests, zero failures, 10 optional/platform skips; repository secret scan and diff checks pass. Scores remain unchanged pending all acceptance criteria.

### Windows CI remediation and installer log privacy

Run 38875036187 caught CRLF double translation in secret-copy output on Windows. The implementation now normalizes input newlines before platform text writes; a byte-level CRLF regression runs on every OS. Headless/redirected setup also withholds the authentication URL instead of copying its bearer token into installer/CI logs; interactive local setup retains the sign-in link. Local suite: 490 tests, zero failures, 10 skips. This supersedes the failed 863c19a Windows result; replacement CI must pass before certification.

## October 26 security implementation pass

Baseline d638b5c was reverified live, PR #34 still open/unmerged, with Production Gate 38875615684 and MCP 38875615644 passing. Implemented incomplete principal/store fail-closed approval handling, immutable operation snapshots, background approval isolation, metadata-only model action events, argument-free registry/visible telemetry and non-echoing HTTP validation. Added tests/test_security_boundaries.py and the full 60-criterion docs/COMPLETION_TRACKER.md; dispatch and diagnostic scope inventory is docs/SECURITY_BOUNDARY_REVIEW.md.

Local validation: 498 tests, zero failures, 11 optional/platform skips; capability consistency, secret scan and diff checks pass. API validation regression requires API dependencies installed by CI; scripted hostile-source tests establish deterministic permission enforcement, not live-model injection resistance. Candidate CI must be verified after push. No scores increased; 6/6/7/4/5/8 remain historical verified lower bounds. NOT FULLY CERTIFIED. Windows native filesystem/ACL parity, broader event/metric schemas and private-history retention remain open implementation work.

Follow-up revocation fix: recheck capability availability and newly required approval immediately before tool dispatch. Regression test revokes the tool during the approval prompt and verifies zero handler calls. Local suite now 499 tests, zero failures, 11 skips. Initial security commit: 0cb28653996b2dcac815ca5cc827e181d1963bf6; initial candidate CI https://github.com/aibatech/aiba-agent/actions/runs/40309758527 (observe status; not presumed passed). Follow-up requires its own CI.

## October 26 memory and recovery implementation

Implemented runtime/profile/skill-root maintenance leases; offline backup/restore/erasure; interrupted-restore startup blocking and recovery; independent individual-memory deletion tombstones; explicit reviewed legacy attribution; full serialized-context budgets; conservative transient/credential retention; attributable conversation-review journal erasure. Added a versioned real-model evaluation corpus/harness. The real-model result is BLOCKED (semantic package and reviewed local model absent), not a synthetic pass.

Local full suite: 511 tests, zero failures, 11 optional/platform skips. Capability, secret-scan and diff checks pass. Recovery rehearsal uses disposable profiles, actual SQLite/files and a child process killed during restore; no customer data or deployment touched. Detailed contract and inventory: docs/MEMORY_PRIVACY_RECOVERY.md. Candidate CI must pass after push.

Memory follow-up: preserve suppression of superseded facts when a deleted current fact is removed from an older restored snapshot. The added regression proves obsolete facts do not become active again and unrelated reused IDs survive. macOS CI 40376069520 exposed a noncanonical test-path comparison that prevented the simulated process crash; the child now resolves its root before comparison. No test was skipped to bypass this failure. Local full suite: 512 tests, zero failures, 11 skips; dedicated memory maintenance suite: 13 tests, zero failures/skips. Initial implementation 87ee5f33c0fc8a11c37f21098ec943263905e06d; replacement candidate requires its own CI.

Windows CI remediation: runtime reader leases now use native LockFileEx shared locks; maintenance uses exclusive locks. The previous CRT lock rejected simultaneous runtime readers. A new cross-platform regression verifies shared reader coexistence and exclusion until the last reader closes. Certification failure output retains 20,000 characters so earlier failures are not hidden. Local full suite: 513 tests, zero failures, 11 skips; dedicated recovery suite: 14 tests, zero failures/skips. Candidate Windows evidence must be verified after push.

### October 28 execution/learning candidate

Implemented conservative job retry and stale-claim review, cooperative cancellation, persisted plan dispatch fencing, owner-bound resume/reconciliation, evidence-linked advisory workflow proposals, and failed-page retrieval handling. Added integrated runtime/registry/store/worker acceptance and matched wrong-content skill regression plus rollback. See `docs/EXECUTION_LEARNING_RECOVERY.md` and `docs/COMPLETION_TRACKER.md`. Verified benchmark lower bounds remain Memory 6, Execution 6, Learning 7, Security 4, UX 5, Reliability 8 out of 10. Live web/model/action-adapter and broader learning certification remain incomplete; release not fully certified.

Local execution/learning suite: `python -m unittest discover -s tests`, 521 tests, zero failures, 11 optional/platform skips. Eight integrated execution/learning acceptance tests pass. Capability consistency and secret scan pass. Candidate CI remains required; local evidence does not certify unavailable API dependencies or remote platforms.

Follow-up adapter/evidence candidate: 523 local tests, zero failures, 11 skips; ten integrated acceptance tests pass. Includes actual persisted adapter postconditions and runtime-generated proposal enrichment. Latest candidate CI must be checked separately from the passing memory prerequisite (Production Gate 40780456627, MCP 40780456617).


## October 31 implementation checkpoint

Current implementation: 755e0e34958600041ae633946932ea3381981d62, following ce6b3c8 (execution/learning), e1d97b8 (adapter postconditions), 46369df (memory-ID validation), and a3d1f87 (resumed progress identity). The Windows newline defect is fixed in the writer, preserving exact UTF-8 bytes rather than relaxing verification. Local full suite: **524 tests, zero failures/errors, 11 optional/platform skips**; targeted execution/learning, owner-isolation and phase-9 suites: 35 tests pass. Capability and secret checks pass.

Required implementation CI: [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/41194842493), [MCP integration](https://github.com/aibatech/aiba-agent/actions/runs/41194842521). Consult these runs for their authoritative final outcomes; links identify this exact implementation. Retained local evidence: `docs/certification/execution-learning-755e0e3.json`. The earlier failure is retained at Production Gate 40782342557, and the passing earlier execution gate at 40781341870; those are not substitutes for the replacement candidate.

Continuation: verify both required candidate workflows and inspect any failures before changing scores. Remaining E1/E3/E8/E10 work is real-model planning quality, live web certification, adapter-specific external idempotency/reconciliation and domain verification beyond the supported local adapters. Remaining L1/L3/L10 work is broader matched intent/outcome evaluation and arbitrary host-execution/security-boundary certification. The actual runtime now feeds verified outcome evidence into advisory proposals; owner review still supplies executable arguments and exact installation approval. No general learning improvement is inferred from the three-case corpus. Benchmark lower bounds stay **6/6/7/4/5/8**. Not fully production certified; no merge, release or deployment performed.
