# Engineering report — 2026-10-15

## Outcome

Substantial implementation and regression remediation completed on `hardening/mission-acceptance-gates`, PR #34. Not fully production certified. The sixty-requirement scorecard explicitly distinguishes passed criteria from partially implemented or untested criteria. Default branch and production deployments were not changed.

## Implemented repairs

- Durable product approval challenges bind to principal and exact operation, expire, and consume atomically once across requests/restarts. Copied contexts cannot double-spend local grants. All policy-gated registry tools require exact arguments.
- Nested secret arguments and opaque host/code payloads are redacted; task action logging and visible tool events reuse the scrubber. Comprehensive output/error secrecy remains a blocker.
- Learned skills now have schema/tool validation, retained owner feedback, digest-bound review/install through authenticated operator endpoints, and permission-enforced execution. Proposal traversal, skill-directory symlinks and rollback-version traversal are rejected.
- Markdown memory corrections/deletions survive re-import and restart. Changed numeric facts are no longer silently discarded by an overly broad near-duplicate heuristic. Conflicting facts still require an explicit resolution policy.
- Backup manifests reject unsafe paths/symlinks, restore staging uses exclusive temporary files, and restores invalidate approval grants. Full-data backup and atomic multi-database restoration remain unverified.
- Windows secret transfer closes handles when permission setup fails; platforms without `fchmod` no longer crash on that call.
- Persistent job cancellation cannot be overwritten by a late completion. Restart recovery honors attempt limits.
- Product and synchronous enhanced-runtime APIs report failed provider calls accurately; background failures propagate. Unresolved tool failures produce partial status and cannot be overwritten by a model-authored success message.
- Rate limiting returns actionable HTTP 429 instead of raising an unhandled middleware exception. CLI greeting emphasizes the personal agent.

## Verification and limitations

Initial baseline: 428 tests, 8 skips. Final local run: **442 tests passed, 1 skipped** after optional dependencies were installed. The one skip is the Windows-only personality permission test on Linux; Windows behavior is covered by the passing CI matrix. The retained certification reports and final CI snapshot identify exact subsequent test runs. Pyright, Bandit high-severity checks, dependency audit, secret scan and capability consistency checks were executed. Real HTTP load used a temporary profile and ephemeral generated credentials.

The first pushed implementation fixed Windows 3.11/3.12 failures across the full OS matrix. CI then found a ContextVar type inference error; it was repaired rather than disabling the gate. Full-runtime acceptance tests use a scripted provider to execute an approved write, verify read-back, restart, recover scoped memories and exercise provider failure. Skill lifecycle tests include denial without execution approval and rollback. These tests do not certify live accounts, model planning quality, mobile devices or signed installers.

Important remaining work is recorded requirement-by-requirement in `BENCHMARK_SCORECARD.md`. In particular: FTS is not semantic retrieval, a short HTTP load run is not a soak, advisory skill generation is not measured self-improvement, and a voice-tagged text request is not native voice support. The connected client repository `aibatech/aiba_app_full` was located, but its physical-device/authentication/approval UI flows were not certified here.

## Traceability

Repository: https://github.com/aibatech/aiba-agent

Draft PR: https://github.com/aibatech/aiba-agent/pull/34

Initial implementation: https://github.com/aibatech/aiba-agent/commit/d0d8a94716dbdfd01c7906533aa9a2db564a4470

Follow-up implementation/evidence commit: `42fcc78fb459d939bf914f1084110c428305f25a`. All 12 Production Gate jobs and MCP Integration passed on that SHA. See `docs/certification/ci-summary.json` when present for retained final observed CI status. No merge, deployment, stable tag, or signing operation was performed.

## Final schema regression fix

A real authenticated operator API test found the existing nested-object `additionalProperties: false` check reversed. It required optional properties and allowed unexpected ones when known properties were present. Corrected and covered with positive/negative schema tests plus the complete HTTP review/install/rate-limit path. After environment recreation, the final local suite ran **444 tests with 3 optional/platform skips**, all remaining tests passed; capability and secret scans passed. Earlier full-extras run was 442 tests with one platform skip. See CI on the final branch head for the corresponding OS matrix evidence.

## Additional remediation evidence — 2026-10-15

Local suite: **455 tests, 3 skips, zero failures** (`python -m unittest discover -s tests`). Implemented optional local semantic retrieval/cache, bounded hybrid context, explicit owner-scoped fact supersession/history, full-profile backup with verified staging and caught-failure rollback, durable scheduled-occurrence deduplication, worker heartbeat/claim fencing and periodic stale recovery. Removed raw tool errors from registry audit and raw output/response/error previews from reasoning telemetry; nested lists now receive credential-key redaction.

New regression modules: test_memory_semantics.py, test_full_profile_backup.py, test_scheduler_reliability.py; expanded test_protocol.py and test_registry_redaction.py. The semantic fixture is deterministic, not a real-model quality certification. Backup restores do not erase extra files or provide multi-file power-loss atomicity. External action replay still requires reconciliation. Latest code requires new CI evidence; earlier green runs do not certify these changes. Scores: Memory 6, Execution 6, Learning 6, Security 4, UX 5, Reliability 7. **Not fully certified; not approved for production deployment.**

Follow-up: local suite now **458 tests, 3 skips, zero failures**. Added POSIX descriptor-relative host read/write/delete, bounded reads and atomic replacement writes; adversarial ancestor-swap and hard-link regression tests pass. Windows keeps atomic writes and bounded reads, but equivalent descriptor-relative race guarantees are not certified. Fixed backup failure-injection test to compare canonical paths on macOS and Windows; no test was skipped to bypass the failure.

### Verified CI and discovery correction

Implementation `7d659ab8c88d2b51c080c2553547c6095a688360`: [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/38733650290) passed all 12 jobs (nine OS/Python combinations, security, capabilities/types and container). [MCP SDK integration](https://github.com/aibatech/aiba-agent/actions/runs/38733650315) passed.

Final discovery correction adds eight existing function-style tests to unittest discovery. They previously were not executed by that runner. Their default-permission check exposed enabled host-file defaults; host file tools now require owner opt-in as well as exact approval. The corrected local suite ran **466 tests, zero failures, nine skips** in the base runtime (optional API/MCP dependencies unavailable after environment reset). Earlier 458-test run used API dependencies and skipped three. New CI is required for this final correction; no optional capability is claimed tested merely because its test skipped.

## Continued engineering — October 16 UTC

Published 68dcd8d added workspace postcondition verification, durable execution evidence, privacy erasure ledger and restoration suppression, confidential reflection metadata, inherited skill restrictions, failure propagation, and bounded one-hour soak instrumentation. Production Gate 38792898735, MCP 38792898605 and soak 38792886989 all passed on that commit. Full soak JSON/RSS samples are retained under docs/certification/runtime-soak-68dcd8d.json.

The subsequent batch adds owner-scoped skill performance records and operator API comparisons; a matched three-case real-file workflow test through proposal/review/install/registry showing 3/3 success for both revisions and 3-to-2 tool calls; attributable profile/reflection/proposal deletion; persistent plans with blocked/pending completion gates. Local suite: **477 tests, zero failures, 10 optional/platform skips**. Capability consistency and secret scan pass. These changes require fresh CI; the earlier soak remains tied to 68dcd8d.

Verified rubric scores: Memory 6, Execution 6, Learning 7, Security 4, UX 5, Reliability 8. Remaining implementation and external validation are still open. The separate aiba_app_full client was inspected; its agent service generates Gemini text and does not establish this runtime's approval/execution contract. No client parity, live conversation quality, signed release or full production certification is asserted.

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


## October 31 implementation checkpoint

Current implementation: 755e0e34958600041ae633946932ea3381981d62, following ce6b3c8 (execution/learning), e1d97b8 (adapter postconditions), 46369df (memory-ID validation), and a3d1f87 (resumed progress identity). The Windows newline defect is fixed in the writer, preserving exact UTF-8 bytes rather than relaxing verification. Local full suite: **524 tests, zero failures/errors, 11 optional/platform skips**; targeted execution/learning, owner-isolation and phase-9 suites: 35 tests pass. Capability and secret checks pass.

Required implementation CI: [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/41194842493), [MCP integration](https://github.com/aibatech/aiba-agent/actions/runs/41194842521). Consult these runs for their authoritative final outcomes; links identify this exact implementation. Retained local evidence: `docs/certification/execution-learning-755e0e3.json`. The earlier failure is retained at Production Gate 40782342557, and the passing earlier execution gate at 40781341870; those are not substitutes for the replacement candidate.

Continuation: verify both required candidate workflows and inspect any failures before changing scores. Remaining E1/E3/E8/E10 work is real-model planning quality, live web certification, adapter-specific external idempotency/reconciliation and domain verification beyond the supported local adapters. Remaining L1/L3/L10 work is broader matched intent/outcome evaluation and arbitrary host-execution/security-boundary certification. The actual runtime now feeds verified outcome evidence into advisory proposals; owner review still supplies executable arguments and exact installation approval. No general learning improvement is inferred from the three-case corpus. Benchmark lower bounds stay **6/6/7/4/5/8**. Not fully production certified; no merge, release or deployment performed.
