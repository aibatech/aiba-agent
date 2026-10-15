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

Initial baseline: 428 tests, 8 skips. Final local run: **442 tests passed, 1 skipped** after optional dependencies were installed. The optional skip does not earn certification credit. The retained certification reports and final CI snapshot identify exact subsequent test runs. Pyright, Bandit high-severity checks, dependency audit, secret scan and capability consistency checks were executed. Real HTTP load used a temporary profile and ephemeral generated credentials.

The first pushed implementation fixed Windows 3.11/3.12 failures across the full OS matrix. CI then found a ContextVar type inference error; it was repaired rather than disabling the gate. Full-runtime acceptance tests use a scripted provider to execute an approved write, verify read-back, restart, recover scoped memories and exercise provider failure. Skill lifecycle tests include denial without execution approval and rollback. These tests do not certify live accounts, model planning quality, mobile devices or signed installers.

Important remaining work is recorded requirement-by-requirement in `BENCHMARK_SCORECARD.md`. In particular: FTS is not semantic retrieval, a short HTTP load run is not a soak, advisory skill generation is not measured self-improvement, and a voice-tagged text request is not native voice support. The connected client repository `aibatech/aiba_app_full` was located, but its physical-device/authentication/approval UI flows were not certified here.

## Traceability

Repository: https://github.com/aibatech/aiba-agent

Draft PR: https://github.com/aibatech/aiba-agent/pull/34

Initial implementation: https://github.com/aibatech/aiba-agent/commit/d0d8a94716dbdfd01c7906533aa9a2db564a4470

Follow-up implementation/evidence commits remain on the same branch. See `docs/certification/ci-summary.json` when present for retained final observed CI status. No merge, deployment, stable tag, or signing operation was performed.
