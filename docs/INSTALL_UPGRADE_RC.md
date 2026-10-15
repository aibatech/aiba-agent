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

Stop the API, workers and schedulers before migration or restore. Preserve the exact old code revision and environment dependency inventory. Make and verify a database backup using the existing BackupManager/operations API; separately copy the entire private data directory and installed skills to owner-controlled encrypted storage. The built-in backup is database-focused and is not a complete workspace/skills/vault backup. Preserve the encryption master key separately; losing it makes encrypted credentials unrecoverable.

Run `python main.py --migrate` and the certification scripts in a staging copy first. Memory source-override schema creation is additive and idempotent. Corrected/deleted markdown memories are suppressed from automatic re-import; source files remain on disk. Do not downgrade to old code that ignores these overrides after privacy-sensitive corrections/deletions.

For rollback, stop all processes, restore the previous code/environment plus matching verified data snapshot, then test readiness and a non-sensitive task before restarting service. Restoring invalidates all approval challenges. Do not restore `approvals.db` from an external snapshot: remove its grants while offline. Never run old and new workers against a restored database concurrently. A full signed-artifact upgrade/rollback drill remains a release blocker.

## Client integration boundary

`aibatech/aiba_app_full` is accessible as a separate client repository. This change does not certify its UI or implement microphone capture, STT/TTS, interruption, accessibility, or physical-device synchronization. Voice and text use the same runtime bridge envelope; that does not establish voice feature parity. Client owners must integrate opaque confirmations and honor failed task status before live certification.
