# AIBA Agent mission acceptance register

The current requirement-by-requirement status and rubric are in **BENCHMARK_SCORECARD.md**. The historical baseline below is retained for traceability and is superseded where the scorecard records tested repairs.

This register describes release evidence, not a claim of certification. **No benchmark is 10/10 without passing evidence for every acceptance criterion.** The six areas are tracked independently.

| Benchmark | Required acceptance evidence | Current result |
|---|---|---|
| Memory | Persist/retrieve user goals and preferences after restart; correct/delete; two-user isolation; web/mobile synchronization | NOT CERTIFIED: end-to-end and cross-device evidence missing |
| Autonomous execution | Deterministic multi-step workflow; permission checks; retries and idempotency; task status; verified outcomes; scheduling | NOT CERTIFIED: live end-to-end and recovery evidence missing |
| Self-improvement | Feedback retained; repeated-task baseline vs improved results; reviewed skill proposals; safe rollback | NOT CERTIFIED: outcome-driven learning benchmark missing |
| Privacy and control | Authenticated principal; exact, expiring, one-use grants; secret-safe logs; filesystem adversarial tests; restore | NOT CERTIFIED: principal and expiration checks missing |
| Human experience | First-run onboarding, voice interruption, Telegram, web/mobile parity and comprehensible errors | NOT CERTIFIED: device and integration evidence missing |
| Reliability | Unit, OS matrix, container, providers, load, soak, database upgrade, backup/restore, security, signed installers | NOT CERTIFIED: see PRODUCTION_GATE.md |

## Current branch changes

- Exact-argument host/secret approvals and single-use grants within a request.
- No blanket auto-approval bypass for exact sensitive actions.
- Secret migration uses exclusive temporary files and atomic replacement and retains unrelated .env entries.
- Host-file contents and executable payloads are redacted in audit surfaces.
- Learned skill proposals are non-executable until explicit review and valid steps.

## Known remaining issues

1. Approval fingerprints currently lack an authenticated principal, expiration, and persistent replay tracking across requests.
2. Filesystem operations need symlink-race and path-authorization threat testing.
3. Secret migration needs full parser coverage, cross-platform file permission tests, and destination safety checks.
4. Memory isolation and cross-device sync need product-level E2E tests.
5. Task execution needs verified outcomes, retry/idempotency, recovery and scheduling benchmarks.
6. Self-improvement needs outcome-based evaluation, not tool-name inference.
7. Voice-first web/mobile, AIBA Core, Telegram and installers need integration/physical tests.
8. Live providers, OS certification, soak, backup restore, security scans, and signed release evidence are still mandatory.

## Release rule

Do not merge or deploy on the basis of CI alone. Record the exact commit, CI runs, OS targets, evidence artifacts, approver and rollback results. Until all mandatory gates are satisfied, use **development / release candidate**, not production certified.
