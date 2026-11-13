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


## November 4 real memory and web evidence

Real semantic evaluation [41808473216](https://github.com/aibatech/aiba-agent/actions/runs/41808473216) passed on fec18e3a6579f5ddd75c3b341be5656e175ee779. Model: sentence-transformers/all-MiniLM-L6-v2, upstream revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41; sentence-transformers 5.7.0; local artifact fingerprint 50e8343fc190e2d36a0d27eb5e4067337d456554a47f43a0a2b9cca2476f5981. Existing corpus aiba-memory-v1 and original thresholds were unchanged: recall@3 1.0 (minimum 0.8), MRR@3 1.0 (minimum 0.7), zero owner leaks/stale hits/budget violations. Full seven-query report and file hashes: `docs/certification/semantic-memory-v1-real.json`. This is scoped retrieval evidence, not general model intelligence.

Actual public-page retrieval [41195846751](https://github.com/aibatech/aiba-agent/actions/runs/41195846751) passed on ab72b07: HTTP 200, nonempty text containing aiba-agent, actual transport without mocks. Search/research quality remains open. ab72b07 also passed Production Gate 41195850136 and MCP 41195850137. New transport pins validated public IPs and preserves original-host TLS validation; metric labels and product validation no longer duplicate arbitrary private inputs.

Current verified lower bounds: **Memory 9/10, Execution 6/10, Learning 7/10, Security 4/10, UX 5/10, Reliability 8/10**. Memory M3/M4 and M10 now meet their documented acceptance criteria; M7 full deletion contract remains incomplete. Other blockers remain in the requirement tracker. The model-preparation optional-import fix requires replacement candidate CI; semantic evaluation itself passed. Release is **not fully certified**. No merge/deployment/public release.

## November 4 implementation and certification checkpoint

Implementation commit: 269464fce3d0852cb390bf3d3dd468956e82e1d0, PR #34, branch hardening/mission-acceptance-gates. Local full suite: 534 tests run, zero failures/errors, 12 optional/platform skips. Secret scan, capability consistency and diff checks pass. Candidate [Production Gate](https://github.com/aibatech/aiba-agent/actions/runs/41809813717) and [MCP integration](https://github.com/aibatech/aiba-agent/actions/runs/41809813889) identify this implementation; final workflow outcomes must be checked directly.

Repairs include public HTTP destination pinning with original-host TLS verification, redirect/body bounds, closed metrics labels, generic product validation errors, and explicit audit metadata with hashed identifiers. Audit EventBus envelopes no longer collide with the positional event name and silently disappear. Audit consumer migration is documented; historical logs are retained unchanged.

Real semantic memory evaluation passed on the pinned all-MiniLM-L6-v2 model: recall@3=1.0, MRR@3=1.0, zero owner leaks/stale hits/budget violations on the unchanged seven-query v1 corpus. Original evidence: CI 41808473216, retained docs/certification/semantic-memory-v1-real.json; repeat CI 41809094413 passed. Actual public-page extraction CI 41195846751 passed; general research quality remains unverified. d9c6d77's capability failure (missing optional import) was fixed by declaring huggingface-hub in semantic/dev extras and installing dev in the type-check environment; replacement capability job 126504817892 passed, with no type-check suppression.

Verified lower bounds: Memory 9/10, Execution 6/10, Learning 7/10, Security 4/10, UX 5/10, Reliability 8/10. No other points added for partial repairs. Release remains NOT FULLY CERTIFIED. No merge, release or deployment performed.

Exact continuation: check candidate workflow outcomes; fix any failure first. Then address M7 owner-attributable source/legacy/backup deletion, S5/S7 Windows ACL and host path-race guarantees, S6/S8/S9 remaining diagnostic surfaces and hostile-content model evaluation, E1/E3/E8/E10 live planning/search and external adapter reconciliation/postconditions, L1/L3/L10 broader outcome-learning and host-security boundaries, and remaining client/device/voice, VPS/soak, live-provider and signed-release evidence. These include implementation gaps as well as unavailable certification; they are not all credential blockers. Preserve the original rubric and criterion rows.

## November 7 diagnostic continuation

Reverified PR34 open/draft at b59e72632cc9c9704bcd2fab2e139804cdccea0a, default baseline e8c01f43. Its Production Gate 41809927003 and MCP integration 41809927156 both passed. The preceding audit implementation gate 41809813717 also passed.

Further S6/S9 repairs: reasoning events discard arbitrary extension metadata, use a fixed public plan summary, validate numeric progress fields, and prevent extras from replacing sanitized fields or event kinds. Crash reports hash source/function names and bucket unknown exception types so dynamically generated names cannot leak private text. Adversarial tests execute a synthetic dynamically named function/exception and exercise every visible reasoning event kind. Task/tool identifiers in owner-visible reasoning remain application metadata; third-party diagnostics, host log permissions/retention and live model injection remain separate unverified scopes. Scores stay 9/6/7/4/5/8; not fully certified.

The November 7 full suite additionally exposed MCP result-status incompatibility in the locally installed SDK 1.29.0: its `isError` field was ignored by the SDK-2-oriented `is_error` reader, falsely reporting a declared failure as success. Both transports now use a shared fail-closed parser: boolean aliases are supported, any true alias means failure, and absent/nonboolean status is an error. The actual stdio fixture exercises success and declared failure; adversarial alias tests cover malformed/conflicting fields. This does not broaden advertised SDK support (the declared extra remains MCP >=2.1,<3); the supported SDK integration gate must also pass.

## November 8 privacy and workspace remediation

Baseline e647e03: Production Gate 42423350781 and MCP 42423350772 passed. M7/S3/S10: erasure confirmation now binds the canonical profile, typed row contents and dependent plans/vectors/supersessions, rather than counts alone; previews take the maintenance lease. Shared identities and malformed erasure ledgers are rejected. Explicit file/journal identity takes precedence over task inference; conflicting or malformed attribution is retained for review. Malformed legacy job payloads remain untouched without blocking correctly attributed deletion. Embeddings are explicitly erased even when older schemas lack cleanup triggers. Regression tests preserve other owners and reject stale content/plan/profile approvals.

S7/E4: workspace writes atomically replace entries rather than modifying shared inodes; reads/patches reject hard-linked files. POSIX read/write/patch/delete use no-follow pinned parent descriptors to reject post-validation symlink swaps. Replacement failures preserve the original and remove the temporary. Windows gets hard-link-safe atomic replacement but no new junction/ACL/parent-race guarantee. Archive/extraction/listing, arbitrary approved command execution, host tools and noncooperating filesystem writers still require their own review. These changes do not certify the whole filesystem boundary.

Scores remain Memory 9, Execution 6, Learning 7, Security 4, UX 5, Reliability 8. Complete owner-erasure scope and other original gaps remain in the requirement rows. No customer data modified; tests use disposable profiles. Candidate CI evidence must be checked after push; no merge/release/deployment.

November 8 execution follow-up (E10): actual AgentLoop host_write_file/host_delete_file registrations now carry trusted outcome verifiers. Writes require exact UTF-8 bytes through a bounded read-back; deletes require observed absence, with symlink entries not accepted as deleted. POSIX verification uses pinned parent descriptors. Host writes now use binary output to prevent Windows newline translation from violating exact-content checks. The integrated runtime/registry/approval test executes real host file actions in a disposable profile and rejects no-op success handlers. This does not certify other external action adapters or close Windows host path races.


## November 13 — resumable privacy and backup lifecycle

Implemented explicit content-bound source/export ownership review, attributed diagnostic JSONL deletion, retained-file inventory, owner-scoped retained-backup redaction, and interruption journals that block runtime/restore until recovery. Local format-2 snapshots are verified before and after redaction; other owners and shared skills remain. Unknown legacy/mixed files are never guessed. Independent attribution/deletion catalogs survive restore. Tests include actual child-process death and corrupt replacement rejection, not only mocked interruptions.

Evidence: `tests/test_privacy_backup_lifecycle.py` (9 tests); full suite: 557 tests, zero failures, one Windows-only skip; capability manifest, secret scan and diff checks passed. Local pyright was unavailable; required CI type checking remains mandatory. Scope/CLI/recovery: `docs/MEMORY_PRIVACY_RECOVERY.md`. Baseline remote commit `0f7a65a32e6e664540cb3c0f85a0c24f9a950063`, PR #34 open/draft; baseline Production Gate 42462812478 and MCP 42462812544 passed. New candidate CI is required; baseline green is not candidate certification.

Scores remain Memory 9, Execution 6, Learning 7, Security 4, UX 5, Reliability 8. M7/S10 now have implemented standard-profile sources/logs/local backup controls, but custom roots/external copies, retained unattributed data review and complete recovery scope still prevent full-account certification. No public release, merge or deployment. Next: verify candidate cross-platform CI, retain run links, then complete adapter-specific uncertain-outcome recovery and intent-aware learning cohorts; live provider/client/device/VPS/signing certification remains separately required. Release NOT FULLY CERTIFIED.


### November 13 implementation evidence and next candidate
Privacy implementation `e410b43c77d07d1565445b618ef87df31318291c` passed Production Gate [43346393311](https://github.com/aibatech/aiba-agent/actions/runs/43346393311) and MCP [43346393373](https://github.com/aibatech/aiba-agent/actions/runs/43346393373). Local tree matched the pushed tree.

Next implementation adds persistent authenticated owner feedback, explicit workflow intent cohorts, rejection-aware evidence selection and stale-evidence rejection at review/install after restart. Versioned learning corpus v1 passes locally: 9 verified outcomes, 3 exact cohorts, 0 cross-intent matches, 0 executable auto-proposals. Scripted provider boundary is explicit. Five new regression tests cover feedback, negatives, isolation, restart, erasure and real runtime corpus. L3 is a candidate for closure after required CI; L1 general adaptive performance and L10 host-boundary certification remain open. No score increase before candidate CI.

Learning candidate local verification: 562 tests, zero failures, one Windows-only skip. Capability manifest, secret scan and diff checks passed. Candidate cross-platform/type/security/container/MCP gates remain mandatory.
