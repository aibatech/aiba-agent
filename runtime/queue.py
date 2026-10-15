from __future__ import annotations
import json,sqlite3,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from typing import Any
from sqlite_utils import connect

def now(): return datetime.now(timezone.utc).isoformat()
class JobQueue:
    def __init__(self,path:Path): self.path=path; self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def _init(self):
        with connect(self.path) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL DEFAULT 100,attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 3,run_after TEXT NOT NULL,locked_at TEXT,last_error TEXT,result TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            cols={r[1] for r in c.execute('PRAGMA table_info(jobs)')}
            for name,definition in [('idempotency_key','TEXT'),('claim_token','TEXT')]:
                if name not in cols:c.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status,run_after,priority,created_at)')
    def enqueue(self,kind:str,payload:dict[str,Any],priority:int=100,max_attempts:int=3,run_after:str|None=None,idempotency_key:str|None=None)->str:
        if not isinstance(max_attempts,int) or max_attempts < 1:raise ValueError('max_attempts must be positive')
        i=str(uuid.uuid4()); t=now()
        with connect(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            if idempotency_key:
                row=c.execute('SELECT id,kind,payload FROM jobs WHERE idempotency_key=?',(idempotency_key,)).fetchone()
                if row:
                    if row[1]!=kind or json.loads(row[2])!=payload:raise ValueError('Idempotency key reused for a different job')
                    return row[0]
            c.execute('INSERT INTO jobs(id,kind,payload,status,priority,max_attempts,run_after,created_at,updated_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?)',(i,kind,json.dumps(payload),'queued',priority,max_attempts,run_after or t,t,t,idempotency_key))
        return i
    def claim(self)->dict[str,Any]|None:
        with connect(self.path,timeout=10,isolation_level='IMMEDIATE') as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT id,kind,payload,attempts,max_attempts FROM jobs WHERE status='queued' AND run_after<=? ORDER BY priority,created_at LIMIT 1",(now(),)).fetchone()
            if not row:return None
            token=uuid.uuid4().hex
            c.execute("UPDATE jobs SET status='running',locked_at=?,attempts=attempts+1,updated_at=?,claim_token=? WHERE id=?",(now(),now(),token,row[0]))
            return {'id':row[0],'kind':row[1],'payload':json.loads(row[2]),'attempts':row[3]+1,'max_attempts':row[4],'claim_token':token}
    def complete(self,i:str,result:Any,claim_token:str|None=None)->None:
        with connect(self.path) as c:c.execute("UPDATE jobs SET status='complete',result=?,updated_at=? WHERE id=? AND status='running' AND (? IS NULL OR claim_token=?)",(json.dumps(result,default=str),now(),i,claim_token,claim_token))
    def fail(self,i:str,error:str,retry:bool=True,claim_token:str|None=None)->None:
        with connect(self.path) as c:
            row=c.execute("SELECT attempts,max_attempts FROM jobs WHERE id=? AND status='running'",(i,)).fetchone(); status='queued' if retry and row and row[0]<row[1] else 'failed'
            c.execute("UPDATE jobs SET status=?,last_error=?,locked_at=NULL,updated_at=? WHERE id=? AND status='running' AND (? IS NULL OR claim_token=?)",(status,error[:2000],now(),i,claim_token,claim_token))
    def cancel(self, i: str) -> bool:
        with connect(self.path) as c:
            return c.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (now(), i)).rowcount > 0

    def heartbeat(self,i:str,claim_token:str)->bool:
        with connect(self.path) as c:
            return c.execute("UPDATE jobs SET locked_at=? WHERE id=? AND status='running' AND claim_token=?",(now(),i,claim_token)).rowcount>0

    def recover(self,stale_seconds:float=0)->int:
        with connect(self.path) as c:
            cur=c.execute("UPDATE jobs SET status=CASE WHEN attempts<max_attempts THEN 'queued' ELSE 'failed' END,locked_at=NULL,updated_at=? WHERE status='running' AND locked_at<=?",(now(),(datetime.now(timezone.utc)-timedelta(seconds=stale_seconds)).isoformat())); return cur.rowcount
    def get(self,i:str)->dict[str,Any]|None:
        with connect(self.path) as c:
            c.row_factory=sqlite3.Row; row=c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone(); return dict(row) if row else None
    def list(self,limit:int=50)->list[dict[str,Any]]:
        with connect(self.path) as c:
            c.row_factory=sqlite3.Row; return [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?',(limit,))]
