# Backup and restore

Create a consistent SQLite backup with `python main.py --backup`. Verify it with `python main.py --verify-backup BACKUP_ID`.

Stop API and worker processes before a production restore. Restore requires the identifier twice:

```bash
python main.py --restore-backup BACKUP_ID --confirm-restore BACKUP_ID
```

AIBA verifies every SHA-256 and SQLite integrity check, then creates a safety backup of current state before replacing files. Test restoration on a separate installation before using it during an incident. Keep off-machine encrypted copies according to the operator’s retention policy; the Community Runtime does not silently upload user data.
