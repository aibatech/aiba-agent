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
