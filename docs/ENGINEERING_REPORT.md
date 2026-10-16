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
