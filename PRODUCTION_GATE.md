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
