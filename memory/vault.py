from __future__ import annotations
import json,re,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from sqlite_utils import connect

# Owner sentinels for the memory vault.
#   SHARED   : operator-global memory. Reachable only through an UN-scoped read
#              (the single operator / primary view), never to a concrete
#              secondary-user scope, so a future second user can never see
#              legacy/global rows.
# Legacy rows created before the v1.6 ownership migration have no owner and are
# backfilled to SHARED, preserving the pre-isolation operator view exactly.
SHARED = 'shared'


class MemoryVault:
    """Owner-scoped durable memory store (SQLite + FTS5).

    Ownership model (v1.6):
      * Every row carries an ``owner`` column (default/backfill ``'shared'``).
      * An *unscoped* read (``as_user=None`` — the operating single-user agent
        view) returns the whole table, exactly the pre-v1.6 behaviour. Today
        the agent acts for one operator, so this is the primary view and sees
        both ``'shared'`` rows and any operator-owned rows.
      * A *scoped* read (``as_user=<concrete user key>``) returns ONLY that
        user's own rows (``owner == as_user``) and NEVER ``'shared'`` or
        another user's rows. That is the isolation guarantee which keeps legacy
        ``'shared'`` records from ever becoming visible to a second user.
    """

    def __init__(self,db_path:Path,vault_dir:Path):
        self.db_path=db_path; self.vault_dir=vault_dir; self.vault_dir.mkdir(parents=True,exist_ok=True); self._init(); self.sync_markdown()

    def _init(self):
        with connect(self.db_path) as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY,content TEXT NOT NULL,category TEXT NOT NULL,importance REAL NOT NULL,source_path TEXT UNIQUE,owner TEXT NOT NULL DEFAULT 'shared',created_at TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}'); CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content,category,content=memories,content_rowid=id); CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN INSERT INTO memories_fts(rowid,content,category) VALUES(new.id,new.content,new.category); END; CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN INSERT INTO memories_fts(memories_fts,rowid,content,category) VALUES('delete',old.id,old.content,old.category); END; CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN INSERT INTO memories_fts(memories_fts,rowid,content,category) VALUES('delete',old.id,old.content,old.category); INSERT INTO memories_fts(rowid,content,category) VALUES(new.id,new.content,new.category); END;''')
            # Upgrade a pre-1.6 database (the memories table already existed
            # without an owner column) idempotently: add the column and backfill
            # every existing legacy row to 'shared'. Safe to run repeatedly.
            cols=[r[1] for r in c.execute('PRAGMA table_info(memories)')]
            if 'owner' not in cols:
                # SQLite requires a literal (not a bound parameter) in the
                # DEFAULT of an ALTER ... ADD COLUMN; existing legacy rows are
                # backfilled to 'shared' by this single atomic statement.
                c.execute(f"ALTER TABLE memories ADD COLUMN owner TEXT NOT NULL DEFAULT '{SHARED}'")

    def _scope(self, as_user):
        """Return (sql_fragment, args) to restrict a query to one user's OWN
        rows. Unscoped (as_user=None) returns ('', []) -> whole table (primary
        view). A concrete as_user adds WHERE owner = <user> so 'shared' and
        other users' rows are never returned."""
        if as_user is None:
            return '', []
        return 'owner = ?', [str(as_user)]

    def add(self,content:str,category='general',importance=0.5,metadata=None,source_path=None,owner=None):
        now=datetime.now(timezone.utc).isoformat(); meta=json.dumps(metadata or {}); owner=str(owner or SHARED)
        with connect(self.db_path) as c:
            cur=c.execute('INSERT INTO memories(content,category,importance,source_path,owner,created_at,metadata) VALUES(?,?,?,?,?,?,?)',(content,category,float(importance),source_path,owner,now,meta)); return cur.lastrowid

    def search(self,query:str,limit=5,as_user=None):
        terms=[re.sub(r'[^A-Za-z0-9_-]','',x) for x in query.split()]; terms=[x for x in terms if x]
        if not terms:return []
        scope,args=self._scope(as_user)
        with connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            sql='SELECT m.*,bm25(memories_fts) rank FROM memories_fts JOIN memories m ON m.id=memories_fts.rowid WHERE memories_fts MATCH ?'
            if scope:sql+=' AND '+scope
            sql+=' ORDER BY rank,m.importance DESC LIMIT ?'
            rows=c.execute(sql,[(' OR '.join(f'"{x}"' for x in terms))]+args+[int(limit)]).fetchall()
            return [dict(r) for r in rows]
    def get(self,memory_id:int,as_user=None):
        scope,args=self._scope(as_user)
        with connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            sql='SELECT * FROM memories WHERE id=?'
            if scope:sql+=' AND '+scope
            r=c.execute(sql,[int(memory_id)]+args).fetchone();return dict(r) if r else None
    def update(self,memory_id:int,content:str|None=None,category:str|None=None,importance:float|None=None,metadata:dict|None=None,as_user=None):
        """Update a memory row. When as_user is given only that user's own rows
        (never 'shared' or another user's) can be mutated; a cross-scope update
        simply matches no row and changes nothing (no cross-owner write).
        Updates stay in FTS sync via the memories_au trigger."""
        sets=[];vals=[]
        if content is not None:sets.append('content=?');vals.append(str(content))
        if category is not None:sets.append('category=?');vals.append(str(category))
        if importance is not None:sets.append('importance=?');vals.append(float(importance))
        if metadata is not None:sets.append('metadata=?');vals.append(json.dumps(metadata))
        if not sets:raise ValueError('Provide at least one field to update')
        scope,args=self._scope(as_user)
        sql='UPDATE memories SET '+', '.join(sets)+' WHERE id=?'
        if scope:sql+=' AND '+scope
        with connect(self.db_path) as c:
            c.execute(sql,vals+[int(memory_id)]+args)
        # The UPDATE may have matched nothing (e.g. a scoped caller targeting a
        # 'shared' or foreign row); no cross-owner mutation can occur.
    def remove(self,memory_id:int,as_user=None)->bool:
        scope,args=self._scope(as_user)
        with connect(self.db_path) as c:
            sql='DELETE FROM memories WHERE id=?'
            if scope:sql+=' AND '+scope
            cur=c.execute(sql,[int(memory_id)]+args);return cur.rowcount>0  # FTS in sync via memories_ad trigger
    def list(self,limit:int=100,category:str|None=None,as_user=None):
        sql='SELECT * FROM memories';args=[]
        scope,sargs=self._scope(as_user)
        if scope:
            sql+=' WHERE '+scope;args+=sargs
        if category:
            sql+= (' AND ' if scope else ' WHERE ')+'category=?';args.append(category)
        sql+=' ORDER BY id DESC LIMIT ?';args.append(int(limit))
        with connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=c.execute(sql,args).fetchall();return [dict(r) for r in rows]
    def export(self,category:str|None=None,as_user=None):
        rows=self.list(limit=10000,category=category,as_user=as_user)
        return [{'id':r['id'],'content':r['content'],'category':r['category'],'importance':r['importance'],'created_at':r['created_at'],'source_path':r.get('source_path')} for r in rows]
    def sync_markdown(self,owner=None):
        for p in self.vault_dir.rglob('*.md'):
            rel=str(p.relative_to(self.vault_dir)); content=p.read_text(encoding='utf-8',errors='replace'); category=rel.split('/')[0] if '/' in rel else 'general'
            with connect(self.db_path) as c:
                row=c.execute('SELECT id,content FROM memories WHERE source_path=?',(rel,)).fetchone()
                if row and row[1]!=content:c.execute('UPDATE memories SET content=?,category=? WHERE id=?',(content,category,row[0]))
                elif not row:self.add(content,category,0.7,{'format':'markdown'},rel,owner=owner)
