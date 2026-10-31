# Installing and reviewing this development candidate

This is a development candidate for owner review, not a production-certified release.

## Supported implementation targets

Python 3.11–3.13; Linux, macOS and Windows CI targets. Optional API, browser, desktop, media and MCP dependencies remain opt-in. Actual desktop/browser devices, cloud deployments and live providers require certification beyond unit tests.

Use the platform installer documented in README.md. For an isolated source review, check out `hardening/mission-acceptance-gates`, record `git rev-parse HEAD`, create a venv, and run `python -m pip install -e '.[api]'`. On Windows activate the venv through `Scripts`; on Unix use `bin`. Run `python setup_cli.py` to configure credentials locally. Never paste credentials into chat or commit `.env`. Keep the API on loopback or behind an authenticated private service boundary.

Validate with `python scripts/certify_install.py`, `python tests/api_smoke.py`, `python scripts/validate_capabilities.py`, and `python scripts/secret_scan.py`. MCP requires `.[mcp]`; the all-capabilities matrix uses `.[all]`. Do not enable capabilities simply to eliminate skips.

## Approval contract change

Product clients must display `approval_required` items from `/v1/product/execute`, obtain explicit owner confirmation, and resubmit the item's opaque `approval_token` in `approved_tools`. Tool names and caller-computed fingerprints no longer authorize product operations. Tokens last five minutes, bind to authenticated backend-provided `X-AIBA-User-ID` and exact arguments, and are consumed once in SQLite. The service credential and user header must be set by a trusted backend, never accepted directly from a public client. A denied/expired token triggers a fresh confirmation; do not automatically approve the replacement.

All registry operations whose policy requires approval now use exact arguments. `--yes` no longer bypasses those operations. Noninteractive scheduled work requiring a new approval remains blocked. Headless trusted embedding code can use a narrowly scoped fingerprint grant, but must not construct grants from model output without owner approval. Product deployments must use the durable challenge store.

## Reviewed skill workflow

Operator API (operator bearer authentication required):

1. Review a proposal with `POST /v1/skill-proposals/{task_id}/review`: explicit `steps`, optional `feedback`, semver `version`. Each step contains only `tool` and `arguments`. Unavailable tools and invalid arguments fail review.
2. Show the returned complete proposal to the owner. Retain its `review_digest`.
3. On approval, `POST /v1/skill-proposals/{task_id}/install` with that digest. Any changed proposal requires review again. An installed proposal cannot be approved again.
4. Execution still traverses the registry and requests operation approvals. Installation does not grant capabilities.
5. Use `SkillManager.revisions(name)` and `rollback(name, version)` from trusted operator code to restore a previous installed version. No model-accessible approval or arbitrary source-rewrite endpoint is added.

## Upgrade, migration and rollback

Stop the API, workers and schedulers before migration or restore. Preserve the exact old code revision and environment dependency inventory. Make and verify a database backup using the existing BackupManager/operations API; separately copy the entire private data directory and installed skills to owner-controlled encrypted storage. Format-2 built-in backups now include data files and installed skill directories when skills_dir is configured. They exclude old backups, approval grants and SQLite journals. Restore replaces snapshot entries but does not delete newer extra files, so it is not an erasure mechanism. Caught filesystem failures are rolled back; multi-file power-loss atomicity and distributed maintenance locks are not provided. Preserve the encryption master key separately; losing it makes encrypted credentials unrecoverable.

Run `python main.py --migrate` and the certification scripts in a staging copy first. Memory source-override schema creation is additive and idempotent. Corrected/deleted markdown memories are suppressed from automatic re-import; source files remain on disk. Do not downgrade to old code that ignores these overrides after privacy-sensitive corrections/deletions.

For rollback, stop all processes, restore the previous code/environment plus matching verified data snapshot, then test readiness and a non-sensitive task before restarting service. Restoring invalidates all approval challenges. Do not restore `approvals.db` from an external snapshot: remove its grants while offline. Never run old and new workers against a restored database concurrently. A full signed-artifact upgrade/rollback drill remains a release blocker.

## Client integration boundary

`aibatech/aiba_app_full` is accessible as a separate client repository. This change does not certify its UI or implement microphone capture, STT/TTS, interruption, accessibility, or physical-device synchronization. Voice and text use the same runtime bridge envelope; that does not establish voice feature parity. Client owners must integrate opaque confirmations and honor failed task status before live certification.

## Optional semantic memory and additive migrations

Install `python -m pip install -e '.[semantic]'` and provision a reviewed sentence-transformers model directory locally. Set `AIBA_MEMORY_EMBEDDING_MODEL` to it and `AIBA_MEMORY_EMBEDDING_REVISION` to its fingerprint. No automatic model download or remote model code is permitted. Change the revision when weights change. Text is embedded locally after owner filtering; cached vectors are removed on edit/deletion. Unconfigured profiles retain lexical search. A real model quality corpus remains required.

Queue idempotency/claim columns and memory fact tables are additive. Scheduled occurrences use durable idempotency keys; claims have heartbeats and periodic stale recovery. This protects job status, not external side effects: use idempotent provider APIs or reconcile before replay. Stop all workers before downgrade. Supply memory `fact_key` only for deliberate updates to one owner's evolving fact. Superseded records remain in operator history and can be explicitly deleted by their owner.

Host filesystem tools now default to disabled in both the permissions policy and capability manifest. An owner must enable the required named tools in config/permissions.json; reads also require AIBA_DESKTOP_ENABLED. Exact per-operation approvals remain required. This does not affect workspace-confined file tools.

## Scoped erasure and result verification

Stop all processes using the profile before running `python scripts/erase_owner.py --data-dir PATH --owner EXACT_ID`. Review the returned row counts and retention limits, then repeat with `--confirm DIGEST` to authorize that exact preview. This removes identity-attributed memory, conversations, sessions, tasks, approvals, jobs and schedules. The erasure ledger is excluded from backups and reapplied after restore. It deliberately reports `complete_account_erasure: false`: unidentified legacy records, source files, logs, installed skills and external copies still need owner review. Do not delete the ledger when restoring. It protects local restores, not copies restored on another host without that ledger.

Workspace writes/deletes now use trusted backend postconditions and retain verification outcomes in task events. Skill failures propagate to the parent task, inherit user-blocked tools, and cannot recursively execute run_skill. Reflection records now retain only operational outcome metadata rather than raw dialogue or automatically imported markdown. Existing historical reflection files are not silently deleted.

The scoped eraser also previews hashes and removes attributable profile JSON/USER.md, reflection JSON/markdown, and proposal JSON under the standard profile directories. Custom external storage roots are outside this operation. All writers must remain stopped throughout erasure.

Skill outcome summaries are available to authenticated operators through `GET /v1/skills/{name}/outcomes?owner=EXACT_ID`; `POST /v1/skills/{name}/compare` takes owner plus baseline_digest and candidate_digest. This measures observed executions and never automatically installs a new version or broadens permissions. Runtime comparison is descriptive; matched acceptance tasks are required to establish improvement. Task status responses now include persisted plan steps and their actual execution states.

### Secret transfer input compatibility

The owner-approved secret-copy tool accepts uppercase environment keys, optional `export`, whitespace around `=`, and single-line quoted or unquoted values. It preserves the value syntax without expansion. Duplicate source keys, malformed/multiline assignments, invalid UTF-8 and unsupported assignment syntax fail before destination changes. Use a supported single-line representation; never paste secrets into chat. This tool does not certify Windows ACLs or protection against every concurrent filesystem mutation.

### Secret transfer descriptor hardening

Secret reads are limited to 1 MiB and regular files. POSIX source reads and destination read/atomic replacement now use pinned ancestor descriptors and no-follow opens; temporary files remain mode 0600. Regression tests reject replacement source symlinks, keep destination-parent swaps from redirecting secrets, and reject FIFOs without blocking. Windows retains the portable path implementation and does not inherit the POSIX race guarantee. Full suite: 488 tests, zero failures, 10 optional/platform skips; repository secret scan and diff checks pass. Scores remain unchanged pending all acceptance criteria.

## Enforced maintenance and deletion-preserving restore

Online snapshot creation is now refused (HTTP 409) while a runtime holds the profile/skill-root leases. Stop every runtime and use `scripts/profile_maintenance.py` for backup/verify/restore. Preserve and transfer both `privacy-erasure.json` and `privacy-deletions.db` independently of backups. Old backups do not contain later deletion decisions. An interrupted restore blocks startup until a verified offline restore succeeds. See docs/MEMORY_PRIVACY_RECOVERY.md for exact commands, legacy review, model evaluation, retention inventory, limitations and recovery procedure.

Execution recovery upgrade: jobs acquire a `retry_policy` column; existing and newly enqueued jobs default to owner review after uncertain execution. Do not downgrade to an older worker while unresolved jobs exist: older code does not honor this replay contract. Take a maintenance backup before migration; restore and run a compatible version for rollback. See `EXECUTION_LEARNING_RECOVERY.md` for planned-task resume and exact-attempt operator reconciliation. Neither resume nor skill installation grants execution approval.


Workspace text writes now preserve the exact requested UTF-8 bytes on Windows, macOS and Linux, including supplied line endings. Existing files are not rewritten during upgrade. Memory exports use this writer and verify their actual bytes; callers requiring CRLF should supply CRLF explicitly. No database migration is needed for this correction.
