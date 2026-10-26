"""Minimal deletion tombstones retained independently of profile snapshots."""
from pathlib import Path
from sqlite_utils import connect

LEDGER_DB='privacy-deletions.db'

def record(database, memory_id, created_at, owner):
    path=Path(database).parent/LEDGER_DB
    if path.is_symlink():raise ValueError('Unsafe memory deletion ledger')
    with connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS deletions(database_name TEXT,memory_id INTEGER,created_at TEXT,owner TEXT,PRIMARY KEY(database_name,memory_id,created_at,owner))')
        db.execute('INSERT OR IGNORE INTO deletions VALUES (?,?,?,?)',(Path(database).name,memory_id,created_at,owner))

def enforce(data_dir,database_name=None):
    root=Path(data_dir);ledger=root/LEDGER_DB
    if not ledger.exists():return
    if ledger.is_symlink():raise ValueError('Unsafe memory deletion ledger')
    with connect(ledger) as db:rows=db.execute('SELECT database_name,memory_id,created_at,owner FROM deletions').fetchall()
    for filename,mid,created,owner in rows:
        if database_name is not None and filename!=database_name:continue
        if Path(filename).name!=filename:raise ValueError('Unsafe deletion database name')
        path=root/filename
        if not path.exists():continue
        if path.is_symlink():raise ValueError('Unsafe memory database')
        with connect(path) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'memories' not in tables:continue
            if not {'owner','created_at','source_path'}.issubset({r[1] for r in db.execute('PRAGMA table_info(memories)')}):
                raise ValueError('Migrate legacy memory schema before applying deletion tombstones')
            row=db.execute('SELECT source_path FROM memories WHERE id=? AND created_at=? AND owner=?',(mid,created,owner)).fetchone()
            if not row:continue
            if row[0] and 'memory_source_overrides' in tables:db.execute('INSERT OR IGNORE INTO memory_source_overrides VALUES (?)',(row[0],))
            if 'memory_facts' in tables:db.execute('DELETE FROM memory_facts WHERE memory_id=?',(mid,))
            if 'memory_supersessions' in tables:db.execute('DELETE FROM memory_supersessions WHERE old_id=? OR new_id=?',(mid,mid))
            db.execute('DELETE FROM memories WHERE id=?',(mid,))
