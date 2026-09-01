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
