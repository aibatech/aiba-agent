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
        return json.loads(path.read_text()) if path.exists() else {'owners': []}

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
                if record.get('owner')==owner or record.get('user_id')==owner or record.get('task_id') in task_ids:
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
                if isinstance(record,dict) and record.get('task_id') in task_ids:count+=1
                else:keep.append(line)
            if count:changes.append((path,b''.join(keep),count))
        return changes

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
        reviews=[{'path':p.relative_to(self.root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'records':count} for p,_,count in self._review_lines(owner)]
        plan = {'review_records':reviews,'owner': owner, 'rows': rows, 'unattributed_rows': legacy,
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
                        db.execute(f"DELETE FROM {table} WHERE json_extract(payload, '$.user_id')=?", (owner,))

    def enforce_after_restore(self):
        for owner in self._ledger()['owners']:
            self._erase_records(owner)
