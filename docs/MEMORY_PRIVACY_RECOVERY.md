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
| Markdown sources, workspace exports and ordinary files | Not reliably attributed | Retained; source overrides suppress deleted derived memories, but do not wipe originals |
| Diagnostic logs, custom storage roots, external accounts/copies | Mixed or external | Retained for explicit operator review; no complete-account/forensic-erasure claim |
| Retained backups | Mixed-owner private snapshots | Retained; must be access-controlled and expired/purged by owner policy; erasure is enforced on supported local restore, not arbitrary external extraction |
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

Current environment: sentence-transformers package absent; no AIBA_MEMORY_EMBEDDING_MODEL directory configured. `docs/certification/memory-evaluation-v1.json` records BLOCKED, passed=false. Supply a reviewed local SentenceTransformer model directory with configuration/tokenizer/weights and install the semantic extra to close this dependency.

## Reproducible recovery evidence

`python -m unittest discover -s tests -p test_memory_maintenance.py` exercises cross-process locks, runtime/skill-root exclusion, clean-profile restore, database integrity, owner deletion ledger transfer, correction persistence, individual deletion/ID reuse, corruption rejection, process death during replacement, explicit legacy attribution, mixed-owner journal erasure and serialized context bounds. Existing full-profile rollback and migration tests remain in the full suite.
