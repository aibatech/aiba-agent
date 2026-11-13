# Memory privacy, retention and recovery contract

## Data inventory

| Data class | Attribution | Deletion/recovery behavior |
|---|---|---|
| Conversation rows/messages | user_key + conversation ID | Owner erasure removes rows; conversation context remains separate from durable facts |
| Durable memories and fact history | owner; fact key for deliberate supersession | Scoped edit/remove; source overrides prevent re-import; record deletion tombstones survive old snapshots |
| Embedding vectors | memory ID/model/content hash | Scope filtering before encode/read; content edits and deletion invalidate cached vectors |
| Profiles and USER.md | explicit user_id/owner | Standard-root attributable files erased; no guess for unknown files |
| Tasks and plans | tasks.owner and task ID | Owner rows/plans erased; unidentified legacy task rows retained |
| Session summaries | user_key | Owner rows erased; retention policy remains separate from durable memory |
| Jobs/schedules | payload.user_id | Exact owner matches erased; unattributed payloads retained |
| Reflections/proposals | owner/user_id or owned task ID | Attributable files/companions erased before task attribution rows |
| Conversation review journals | owned task ID per JSONL record | Matching lines removed atomically; other owners and unknown/malformed lines preserved |
| Skill outcome records | owner | Owner rows erased; installed shared skills retained |
| Markdown sources, workspace exports and ordinary files | Explicit whole-file review in privacy-files.json | Reviewed exact content versions erased; unreviewed, changed and mixed-owner files retained or blocked for review |
| Diagnostic JSONL logs | Exact owner, owned task ID/hash or attributed context | Matching records removed; conflicting, malformed and unattributed records preserved |
| Custom storage roots, external accounts/copies | External to the profile | Separate operator inventory and lifecycle required; not automatically erased |
| Retained local format-2 backups | Manifest plus per-record/file attribution | Explicit --include-backups redacts owner data and verifies replacement snapshots; other owners/shared installed skills preserved |
| Owner/record deletion ledgers | Minimal owner/record identifiers | Retained independently; never restored from an older profile snapshot |

`privacy-erasure.json` suppresses restored data for erased identities. `privacy-deletions.db` records database filename, record ID, creation timestamp and owner, preventing deletion of a later record that reuses the same ID. Keep both ledgers independently secured and transfer them to a recovery host **before restore**. An old backup alone cannot know about later deletions. Do not reuse erased account identities for a new account without a separate reviewed policy.

Temporary intentions such as “I want to order lunch today” remain in conversation history unless the owner explicitly requests remembering them. Obvious credential declarations are not automatically learned. This conservative recognizer is not a universal secret detector or a dialogue retention TTL.

## Enforced offline maintenance

A running AgentLoop holds OS-backed shared leases on its data and installed-skill roots. Backup/restore obtains exclusive leases on both roots; owner erasure and legacy attribution obtain the profile's exclusive lease. Competing operations fail closed. Locks release on process exit. Do not delete lock files to bypass the protocol.

All AIBA runtime processes must close before maintenance. External scripts that directly manipulate stores/files must join `ProfileLease`/`ProfileLeases` or remain stopped. This coordination does not constrain arbitrary noncooperating programs, NFS lock semantics, or physical disk failure.

The live backup API returns HTTP 409 with maintenance guidance. It no longer creates a potentially inconsistent online snapshot. Use the offline CLI below. Backup verify/list remain read-only operations.

```
python scripts/profile_maintenance.py --data-dir PROFILE --skills-dir SKILLS backup
python scripts/profile_maintenance.py --data-dir PROFILE --skills-dir SKILLS verify --backup-id ID
python scripts/profile_maintenance.py --data-dir PROFILE --skills-dir SKILLS restore --backup-id ID --confirm ID
```

Restore stages and verifies replacements, saves a pre-restore snapshot, and rolls back caught replacement failures. An interrupted-restore marker blocks runtime startup and new backups until a successful offline restore completes. Re-run restore with a verified snapshot to recover. This provides recoverable interruption handling, not atomic multi-file power-loss transactions. Extra files not in a snapshot remain; restore is not a directory wipe.

## Reviewed legacy ownership migration

```
python scripts/profile_maintenance.py --data-dir PROFILE legacy-preview --database memory.db
python scripts/profile_maintenance.py --data-dir PROFILE legacy-assign --database memory.db --assignments reviewed-mapping.json --confirm DIGEST
```

Use the actual configured memory database filename. Preview contains private record content: review it locally and protect redirected files. The JSON mapping explicitly maps selected record IDs to owner IDs. Confirmation binds the current inventory; changed records require review again. Genuinely shared/unselected records remain shared. Fact-linked legacy rows require explicit conflict resolution and are refused by this simple attribution path. No automatic owner inference or deletion occurs.

## Real semantic evaluation

Corpus: `benchmarks/memory/v1.json`, version `aiba-memory-v1`. Fixed pre-evaluation thresholds: recall@3 >= 0.80, MRR@3 >= 0.70, zero owner leaks, zero stale hits, zero serialized-context budget violations. Corpus includes paraphrases, distractors, corrected facts, deleted memory and separate users. It is a small regression corpus, not broad model-quality certification.

```
python -m pip install -e '.[semantic]'
python scripts/evaluate_memory.py --model REVIEWED_LOCAL_MODEL --output certification/memory-real-model.json
```

The executable uses the actual LocalEmbedder/SentenceTransformer path with local_files_only and trust_remote_code=False. It records package version, corpus hash, all model-file hashes, model identity, metrics and per-query results. No automatic model download is performed. Test-only embeddings verify the harness mechanics and do not produce semantic certification.

The original local attempt in `docs/certification/memory-evaluation-v1.json` remains historical BLOCKED evidence. Real pinned-model CI 41808473216 and repeat 41809094413 subsequently passed; retained results are in `docs/certification/semantic-memory-v1-real.json`. See BENCHMARK_SCORECARD.md for the exact model/corpus scope. Local reproduction still requires the semantic extra and reviewed model artifact.

## Reproducible recovery evidence

`python -m unittest discover -s tests -p test_memory_maintenance.py` exercises cross-process locks, runtime/skill-root exclusion, clean-profile restore, database integrity, owner deletion ledger transfer, correction persistence, individual deletion/ID reuse, corruption rejection, process death during replacement, explicit legacy attribution, mixed-owner journal erasure and serialized context bounds. Existing full-profile rollback and migration tests remain in the full suite.

Erasure review now requires the runtime to be stopped for preview as well as execution. Confirmation includes canonical profile and hashes of exact database contents (including dependent plans/embeddings), plus private-file digests. Editing a row without changing its count invalidates confirmation. Re-run preview after every upgrade or data change. `shared` is not an erasable owner; conflicting or malformed attribution is preserved for operator review. Malformed ledgers stop erasure/restore enforcement until repaired from independently secured records. Legacy job JSON is preserved rather than guessed. This is logical active-record deletion, not forensic media sanitization.


## Reviewed files and retained backup deletion (November 13)

Stop all profile writers. Inventory the `retained_file_inventory` in the erasure preview. This contains private filenames; do not publish previews as CI artifacts. Never assign a shared or mixed-owner file to one owner. For exclusively owned sources/exports, prepare a local JSON mapping such as `{"vault/notes.md":"alice","export.txt":"alice"}`. Paths are relative to the profile; symlinks, hard-linked files, databases and control files are rejected. Existing conflicting JSON provenance is not overridden.

```sh
python scripts/profile_maintenance.py --data-dir PROFILE files-preview --assignments reviewed-files.json --include-backups
python scripts/profile_maintenance.py --data-dir PROFILE files-assign --assignments reviewed-files.json --include-backups --confirm DIGEST
python scripts/erase_owner.py --data-dir PROFILE --owner alice --include-backups
python scripts/erase_owner.py --data-dir PROFILE --owner alice --include-backups --confirm ERASURE_DIGEST
```

The first confirmation binds current file bytes, catalog and the reviewed historical versions. Review **all historical versions**, not only the current file. Changed bytes require a new review. The erasure confirmation separately binds the current profile records and backup manifest inventory. Omitting `--include-backups` leaves snapshots intact with restore-time deletion enforcement. With it, each verified format-2 snapshot is copied privately, redacted, integrity-checked, and replaced before the original snapshot is removed. Other owners and shared installed skills remain. Unmanifested files or corruption stop processing; they are never silently discarded.

A pending privacy journal blocks runtime startup, backup creation and restore. After a crash, retain this journal and its private staging directory, stop all writers, and run:

```sh
python scripts/erase_owner.py --data-dir PROFILE --owner alice --resume
```

Resume accepts only the originally approved owner. Incomplete staging is discarded and rebuilt; a prepared replacement must retain its approved digest and integrity. If corrupted, recover its exact verified bytes from independently secured storage or obtain operator recovery assistance; do not remove the marker to bypass checks. The original snapshot is retained until its replacement passes verification. This is process-interruption recovery, not a guarantee against simultaneous media failure or arbitrary noncooperating writers.

`privacy-files.json`, `privacy-erasure.json`, and `privacy-deletions.db` must be secured independently and transferred **before** restoring on a clean host. They are deliberately excluded from snapshots so old copies cannot undo newer ownership/deletion decisions. Keep their minimal suppression metadata after erasure. Legacy format-1 snapshots require offline review/migration: restore into a disposable isolated profile with the independent ledgers, verify attribution and integrity, then create and verify a format-2 snapshot. Do not remove the original until the migrated copy is verified and retention disposal is explicitly authorized.

Contract limits: logical attributable-data erasure inside the configured standard profile and explicitly reviewed local snapshots. Unattributed/mixed legacy records remain for review; custom roots, exported copies outside the profile, external accounts, filesystem snapshots and forensic media sanitization require separate procedures. `complete_account_erasure` remains false. This work does not certify those boundaries.

Reproduce with `python -m unittest discover -s tests -p test_privacy_backup_lifecycle.py`: nine tests use real SQLite/file stores and disposable profiles, including owner isolation, exact confirmation, historical source/export deletion, restore suppression, staged replacement interruption, actual child-process termination, corrupt prepared snapshots, conflicting provenance and unmanifested backup content. External systems are not used.
