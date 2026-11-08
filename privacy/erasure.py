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
    'skill_runs': 'owner',
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
        ledger = json.loads(path.read_text()) if path.exists() else {'owners': []}
        if not isinstance(ledger, dict) or not isinstance(ledger.get('owners'), list):
            raise ValueError('Invalid erasure ledger; operator recovery required')
        for owner in ledger['owners']:
            self._validate_owner(owner)
        return ledger

    @staticmethod
    def _validate_owner(owner):
        if not isinstance(owner, str) or not owner.strip() or owner == 'shared':
            raise ValueError('Exact non-shared owner identity required')

    @staticmethod
    def _snapshot(db, table, where, parameters):
        # SQL identifiers/predicates are internal constants; identities are parameters.
        cursor = db.execute(f'SELECT * FROM {table} WHERE {where}', parameters)
        columns = [item[0] for item in cursor.description]
        def encode(value):
            if isinstance(value, bytes):return {'bytes_hex': value.hex()}
            return value
        records = sorted(json.dumps([encode(v) for v in row], ensure_ascii=True,
                                    separators=(',', ':')) for row in cursor)
        digest = hashlib.sha256(json.dumps([columns, records], separators=(',', ':')).encode()).hexdigest()
        return {'table': table, 'count': len(records), 'sha256': digest}


    @staticmethod
    def _belongs(record, owner, task_ids):
        # Explicit provenance takes precedence over inferred task attribution.
        # Conflicting/malformed identity fields are retained for operator review.
        identities = [record[key] for key in ('owner', 'user_id') if key in record]
        if identities:
            return all(isinstance(identity, str) and identity == owner for identity in identities)
        task_id = record.get('task_id')
        return isinstance(task_id, str) and task_id in task_ids

    def _owned_files(self, owner):
        task_ids = set()
        for database in self._databases():
            with connect(database) as db:
                columns = {r[1] for r in db.execute('PRAGMA table_info(tasks)')}
                if 'owner' in columns:
                    task_ids.update(r[0] for r in db.execute('SELECT id FROM tasks WHERE owner=?', (owner,)))
        files = set()
        roots = (self.root/'profiles', self.root/'vault'/'reflections', self.root/'vault'/'skill_proposals')
        for folder in roots:
            if folder.is_symlink(): raise ValueError('Private file directory symlinks are forbidden')
            if not folder.exists(): continue
            folder.resolve().relative_to(self.root)
            for path in folder.glob('*.json'):
                if path.is_symlink(): raise ValueError('Private file symlinks are forbidden')
                try:
                    record=json.loads(path.read_text(encoding='utf-8'))
                except (ValueError,UnicodeError):
                    continue  # Unattributed legacy files are reported as retained.
                if not isinstance(record,dict):continue
                if self._belongs(record, owner, task_ids):
                    files.add(path)
                    companions = [path.with_suffix('.md')] if folder.name=='reflections' else []
                    if folder.name=='profiles':companions.append(path.with_name(path.stem+'-USER.md'))
                    for companion in companions:
                        if companion.is_symlink():raise ValueError('Private file symlinks are forbidden')
                        if companion.is_file():files.add(companion)
        return sorted(files)

    def _review_lines(self,owner):
        task_ids=set()
        for database in self._databases():
            with connect(database) as db:
                if 'owner' in {r[1] for r in db.execute('PRAGMA table_info(tasks)')}:
                    task_ids.update(r[0] for r in db.execute('SELECT id FROM tasks WHERE owner=?',(owner,)))
        folder=self.root/'vault'/'conversation_reviews'
        if folder.is_symlink():raise ValueError('Review directory symlinks are forbidden')
        if not folder.exists():return []
        folder.resolve().relative_to(self.root)
        changes=[]
        for path in folder.glob('*.jsonl'):
            if path.is_symlink():raise ValueError('Review file symlinks are forbidden')
            keep=[];count=0
            for line in path.read_bytes().splitlines(keepends=True):
                try:record=json.loads(line)
                except (ValueError,UnicodeError):record=None
                if isinstance(record,dict) and self._belongs(record, owner, task_ids):count+=1
                else:keep.append(line)
            if count:changes.append((path,b''.join(keep),count))
        return changes

    def preview(self, owner):
        from operations.maintenance import ProfileLease
        with ProfileLease(self.root):return self._preview(owner)

    def _preview(self, owner):
        self._validate_owner(owner)
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
                    rows.append({'database': path.name, **self._snapshot(db, table, f'{column}=?', (owner,))})
                    legacy += db.execute(f'SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR {column}=\'\' OR {column}=\'shared\'').fetchone()[0]
                for table in ('jobs', 'schedules'):
                    if table in tables:
                        predicate = "json_extract(CASE WHEN json_valid(payload) THEN payload ELSE '{}' END, '$.user_id')=?"
                        rows.append({'database':path.name, **self._snapshot(db, table, predicate, (owner,))})
                        legacy += db.execute(f"SELECT COUNT(*) FROM {table} WHERE json_extract(CASE WHEN json_valid(payload) THEN payload ELSE '{{}}' END, '$.user_id') IS NULL").fetchone()[0]
                if 'tasks' in tables and 'task_plans' in tables and 'owner' in {r[1] for r in db.execute('PRAGMA table_info(tasks)')}:
                    rows.append({'database':path.name, **self._snapshot(db, 'task_plans', 'task_id IN (SELECT id FROM tasks WHERE owner=?)', (owner,))})
                if 'memories' in tables and 'owner' in {r[1] for r in db.execute('PRAGMA table_info(memories)')}:
                    if 'memory_embeddings' in tables:
                        rows.append({'database':path.name, **self._snapshot(db, 'memory_embeddings', 'memory_id IN (SELECT id FROM memories WHERE owner=?)', (owner,))})
                    if 'memory_supersessions' in tables:
                        rows.append({'database':path.name, **self._snapshot(db, 'memory_supersessions', 'old_id IN (SELECT id FROM memories WHERE owner=?) OR new_id IN (SELECT id FROM memories WHERE owner=?)', (owner,owner))})
        reviews=[{'path':p.relative_to(self.root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'records':count} for p,_,count in self._review_lines(owner)]
        plan = {'profile':str(self.root),'review_records':reviews,'owner': owner, 'rows': rows, 'unattributed_rows': legacy,
                'files':[{'path':p.relative_to(self.root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in self._owned_files(owner)],
                'limits': ['Offline operation: stop every profile writer first.',
                           'Unattributed legacy files, logs, source documents, installed skills, backups and external copies are retained.',
                           'This erases active identity-attributed database records; it is not complete account or forensic erasure.']}
        plan['confirmation'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        return plan

    def erase(self, owner, confirmation):
        from operations.maintenance import ProfileLease
        with ProfileLease(self.root):return self._erase(owner,confirmation)

    def _erase(self, owner, confirmation):
        plan = self._preview(owner)
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
                'remaining': self._preview(owner), 'restore_protection': True}

    def _erase_records(self, owner):
        # Rewrite mixed-owner review journals before deleting attribution rows.
        for path,remaining,_ in self._review_lines(owner):
            fd,temp=tempfile.mkstemp(prefix='.erase-review-',dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(remaining);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
            finally:Path(temp).unlink(missing_ok=True)
        for path in self._owned_files(owner):
            path.unlink()
        for path in self._databases():
            with connect(path) as db:
                db.execute('PRAGMA secure_delete=ON')
                db.execute('BEGIN IMMEDIATE')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'memories' in tables:
                    columns = {r[1] for r in db.execute('PRAGMA table_info(memories)')}
                    if 'owner' in columns:
                        if 'memory_embeddings' in tables:
                            db.execute('DELETE FROM memory_embeddings WHERE memory_id IN (SELECT id FROM memories WHERE owner=?)', (owner,))
                        if 'memory_source_overrides' in tables:
                            db.execute('INSERT OR IGNORE INTO memory_source_overrides SELECT source_path FROM memories WHERE owner=? AND source_path IS NOT NULL', (owner,))
                        if 'memory_supersessions' in tables:
                            db.execute('DELETE FROM memory_supersessions WHERE old_id IN (SELECT id FROM memories WHERE owner=?) OR new_id IN (SELECT id FROM memories WHERE owner=?)', (owner, owner))
                if 'task_plans' in tables and 'tasks' in tables and 'owner' in {r[1] for r in db.execute('PRAGMA table_info(tasks)')}:
                    db.execute('DELETE FROM task_plans WHERE task_id IN (SELECT id FROM tasks WHERE owner=?)',(owner,))
                for table, column in SCOPES.items():
                    if table in tables and column in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
                        db.execute(f'DELETE FROM {table} WHERE {column}=?', (owner,))
                for table in ('jobs', 'schedules'):
                    if table in tables:
                        db.execute(f"DELETE FROM {table} WHERE json_extract(CASE WHEN json_valid(payload) THEN payload ELSE '{{}}' END, '$.user_id')=?", (owner,))

    def enforce_after_restore(self):
        for owner in self._ledger()['owners']:
            self._erase_records(owner)
