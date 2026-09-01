from __future__ import annotations
import json,re,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from sqlite_utils import connect
class MemoryVault:
    def __init__(self,db_path:Path,vault_dir:Path): self.db_path=db_path; self.vault_dir=vault_dir; self.vault_dir.mkdir(parents=True,exist_ok=True); self._init(); self.sync_markdown()
    def _init(self):
        with connect(self.db_path) as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY,content TEXT NOT NULL,category TEXT NOT NULL,importance REAL NOT NULL,source_path TEXT UNIQUE,created_at TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}'); CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content,category,content=memories,content_rowid=id); CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN INSERT INTO memories_fts(rowid,content,category) VALUES(new.id,new.content,new.category); END; CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN INSERT INTO memories_fts(memories_fts,rowid,content,category) VALUES('delete',old.id,old.content,old.category); END; CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN INSERT INTO memories_fts(memories_fts,rowid,content,category) VALUES('delete',old.id,old.content,old.category); INSERT INTO memories_fts(rowid,content,category) VALUES(new.id,new.content,new.category); END;''')
    def add(self,content:str,category='general',importance=0.5,metadata=None,source_path=None):
        now=datetime.now(timezone.utc).isoformat(); meta=json.dumps(metadata or {})
        with connect(self.db_path) as c:
            cur=c.execute('INSERT INTO memories(content,category,importance,source_path,created_at,metadata) VALUES(?,?,?,?,?,?)',(content,category,float(importance),source_path,now,meta)); return cur.lastrowid
    def search(self,query:str,limit=5):
        terms=[re.sub(r'[^A-Za-z0-9_-]','',x) for x in query.split()]; terms=[x for x in terms if x]
        if not terms:return []
        with connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            rows=c.execute('SELECT m.*,bm25(memories_fts) rank FROM memories_fts JOIN memories m ON m.id=memories_fts.rowid WHERE memories_fts MATCH ? ORDER BY rank,m.importance DESC LIMIT ?',(' OR '.join(f'"{x}"' for x in terms),int(limit))).fetchall()
            return [dict(r) for r in rows]
    def sync_markdown(self):
        for p in self.vault_dir.rglob('*.md'):
            rel=str(p.relative_to(self.vault_dir)); content=p.read_text(encoding='utf-8',errors='replace'); category=rel.split('/')[0] if '/' in rel else 'general'
            with connect(self.db_path) as c:
                row=c.execute('SELECT id,content FROM memories WHERE source_path=?',(rel,)).fetchone()
                if row and row[1]!=content:c.execute('UPDATE memories SET content=?,category=? WHERE id=?',(content,category,row[0]))
                elif not row:self.add(content,category,0.7,{'format':'markdown'},rel)
