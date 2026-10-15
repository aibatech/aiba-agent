"""Resumable offline erasure of identity-attributed runtime records.

Cannot erase unknown-owner legacy files or external copies. Reports those limits
explicitly. The erasure ledger survives restore to prevent database resurrection.
"""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from pathlib import Path
from sqlite_utils import connect

LEDGER = 'privacy-erasure.json'
# Static identifiers only: caller data is always bound as a SQL parameter.
SCOPES = {
    'conversation_messages': 'user_key', 'conversations': 'user_key',
    'sessions': 'user_key', 'tasks': 'owner', 'memories': 'owner',
    'memory_facts': 'owner', 'approval_challenges': 'principal',
}


class OwnerErasure:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()

    def _databases(self):
        for path in sorted(self.root.glob('*.db')):
            if path.is_symlink(): raise ValueError('Database symlinks cannot be erased')
            yield path

    def _ledger(self):
        path = self.root / LEDGER
        if path.is_symlink(): raise ValueError('Erasure ledger symlinks are forbidden')
        return json.loads(path.read_text()) if path.exists() else {'owners': []}

    def preview(self, owner):
        if not isinstance(owner, str) or not owner.strip(): raise ValueError('Exact owner identity required')
        rows = []; legacy = 0
        for path in self._databases():
            with connect(path) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table, column in SCOPES.items():
                    if table not in tables: continue
                    columns = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                    if column not in columns:
                        legacy += db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                        continue
                    count = db.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?', (owner,)).fetchone()[0]
                    rows.append({'database': path.name, 'table': table, 'count': count})
                    legacy += db.execute(f'SELECT COUNT(*) FROM {table} WHERE {column} IS NULL').fetchone()[0]
                for table in ('jobs', 'schedules'):
                    if table in tables:
                        count = db.execute(f"SELECT COUNT(*) FROM {table} WHERE json_extract(payload, '$.user_id')=?", (owner,)).fetchone()[0]
                        rows.append({'database':path.name,'table':table,'count':count})
        plan = {'owner': owner, 'rows': rows, 'unattributed_rows': legacy,
                'limits': ['Offline operation: stop every profile writer first.',
                           'Unattributed legacy files, logs, source documents, installed skills, backups and external copies are retained.',
                           'This erases active identity-attributed database records; it is not complete account or forensic erasure.']}
        plan['confirmation'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        return plan

    def erase(self, owner, confirmation):
        plan = self.preview(owner)
        if confirmation != plan['confirmation']: raise ValueError('Review and confirm the current erasure preview')
        ledger = self._ledger()
        if owner not in ledger['owners']:
            ledger['owners'].append(owner)
            fd, temporary = tempfile.mkstemp(prefix='.privacy-', dir=self.root)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(ledger, stream); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, self.root / LEDGER)
            finally:
                Path(temporary).unlink(missing_ok=True)
        # Ledger first: interrupted erasures can safely be resumed.
        self._erase_records(owner)
        return {'active_records_erased': True, 'complete_account_erasure': False,
                'remaining': self.preview(owner), 'restore_protection': True}

    def _erase_records(self, owner):
        for path in self._databases():
            with connect(path) as db:
                db.execute('PRAGMA secure_delete=ON')
                db.execute('BEGIN IMMEDIATE')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'memories' in tables:
                    columns = {r[1] for r in db.execute('PRAGMA table_info(memories)')}
                    if 'owner' in columns:
                        if 'memory_source_overrides' in tables:
                            db.execute('INSERT OR IGNORE INTO memory_source_overrides SELECT source_path FROM memories WHERE owner=? AND source_path IS NOT NULL', (owner,))
                        if 'memory_supersessions' in tables:
                            db.execute('DELETE FROM memory_supersessions WHERE old_id IN (SELECT id FROM memories WHERE owner=?) OR new_id IN (SELECT id FROM memories WHERE owner=?)', (owner, owner))
                for table, column in SCOPES.items():
                    if table in tables and column in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
                        db.execute(f'DELETE FROM {table} WHERE {column}=?', (owner,))
                for table in ('jobs', 'schedules'):
                    if table in tables:
                        db.execute(f"DELETE FROM {table} WHERE json_extract(payload, '$.user_id')=?", (owner,))

    def enforce_after_restore(self):
        for owner in self._ledger()['owners']:
            self._erase_records(owner)
