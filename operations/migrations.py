from __future__ import annotations
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from sqlite_utils import connect

class MigrationError(RuntimeError):pass
def now():return datetime.now(timezone.utc).isoformat()

MIGRATIONS={
 'providers.db':[(1,'provider-baseline','SELECT 1'),(2,'usage-status-index','CREATE INDEX IF NOT EXISTS idx_usage_status_time ON model_usage(status,created_at)')],
 'jobs.db':[(1,'jobs-baseline','SELECT 1'),(2,'jobs-lock-index','CREATE INDEX IF NOT EXISTS idx_jobs_locked ON jobs(status,locked_at)')],
 'tasks.db':[(1,'tasks-baseline','SELECT 1')],
 'schedules.db':[(1,'schedules-baseline','SELECT 1')],
 'auth.db':[(1,'auth-baseline','SELECT 1')],
 'aiba.db':[(1,'memory-baseline','SELECT 1')],
}

class MigrationManager:
    """Owns explicit, idempotent SQLite schema versions for every runtime database."""
    def __init__(self,data_dir:Path):self.data_dir=data_dir;self.data_dir.mkdir(parents=True,exist_ok=True)
    def _checksum(self,sql):return hashlib.sha256(sql.encode()).hexdigest()
    def apply(self):
        results=[]
        for name,migrations in MIGRATIONS.items():
            path=self.data_dir/name
            if not path.exists():continue
            with connect(path,timeout=30) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)')
                applied={r[0]:r[1] for r in db.execute('SELECT version,checksum FROM schema_migrations')}
                for version,label,sql in migrations:
                    checksum=self._checksum(sql)
                    if version in applied:
                        if applied[version]!=checksum:raise MigrationError(f'{name} migration {version} checksum changed')
                        continue
                    try:
                        db.execute('BEGIN IMMEDIATE');db.execute(sql);db.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)',(version,label,checksum,now()));db.execute(f'PRAGMA user_version={version}');db.commit()
                    except Exception as exc:db.rollback();raise MigrationError(f'{name} migration {version} failed: {exc}') from exc
                integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity!='ok':raise MigrationError(f'{name} integrity check failed: {integrity}')
                current=db.execute('PRAGMA user_version').fetchone()[0]
                results.append({'database':name,'version':current,'integrity':'ok'})
        return results
    def status(self):
        result=[]
        for name,migrations in MIGRATIONS.items():
            path=self.data_dir/name;current=0
            if path.exists():
                with connect(path) as db:current=db.execute('PRAGMA user_version').fetchone()[0]
            result.append({'database':name,'current':current,'target':migrations[-1][0],'exists':path.exists(),'ready':not path.exists() or current==migrations[-1][0]})
        return result
