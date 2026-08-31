from __future__ import annotations
import json,sqlite3,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

def now(): return datetime.now(timezone.utc).isoformat()
class JobQueue:
    def __init__(self,path:Path): self.path=path; self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def _init(self):
        with sqlite3.connect(self.path) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL DEFAULT 100,attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 3,run_after TEXT NOT NULL,locked_at TEXT,last_error TEXT,result TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status,run_after,priority,created_at)')
    def enqueue(self,kind:str,payload:dict[str,Any],priority:int=100,max_attempts:int=3,run_after:str|None=None)->str:
        i=str(uuid.uuid4()); t=now()
        with sqlite3.connect(self.path) as c:c.execute('INSERT INTO jobs(id,kind,payload,status,priority,max_attempts,run_after,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(i,kind,json.dumps(payload),'queued',priority,max_attempts,run_after or t,t,t))
        return i
    def claim(self)->dict[str,Any]|None:
        with sqlite3.connect(self.path,timeout=10,isolation_level='IMMEDIATE') as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT id,kind,payload,attempts,max_attempts FROM jobs WHERE status='queued' AND run_after<=? ORDER BY priority,created_at LIMIT 1",(now(),)).fetchone()
            if not row:return None
            c.execute("UPDATE jobs SET status='running',locked_at=?,attempts=attempts+1,updated_at=? WHERE id=?",(now(),now(),row[0]))
            return {'id':row[0],'kind':row[1],'payload':json.loads(row[2]),'attempts':row[3]+1,'max_attempts':row[4]}
    def complete(self,i:str,result:Any)->None:
        with sqlite3.connect(self.path) as c:c.execute("UPDATE jobs SET status='complete',result=?,updated_at=? WHERE id=?",(json.dumps(result,default=str),now(),i))
    def fail(self,i:str,error:str,retry:bool=True)->None:
        with sqlite3.connect(self.path) as c:
            row=c.execute('SELECT attempts,max_attempts FROM jobs WHERE id=?',(i,)).fetchone(); status='queued' if retry and row and row[0]<row[1] else 'failed'
            c.execute('UPDATE jobs SET status=?,last_error=?,locked_at=NULL,updated_at=? WHERE id=?',(status,error[:2000],now(),i))
    def recover(self)->int:
        with sqlite3.connect(self.path) as c:
            cur=c.execute("UPDATE jobs SET status='queued',locked_at=NULL,updated_at=? WHERE status='running'",(now(),)); return cur.rowcount
    def get(self,i:str)->dict[str,Any]|None:
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row; row=c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone(); return dict(row) if row else None
    def list(self,limit:int=50)->list[dict[str,Any]]:
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row; return [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?',(limit,))]
