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
