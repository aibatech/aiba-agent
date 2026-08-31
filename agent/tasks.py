from __future__ import annotations
import json,sqlite3,uuid
from datetime import datetime,timezone
from pathlib import Path
def now():return datetime.now(timezone.utc).isoformat()
class TaskStore:
    def __init__(self,path:Path):self.path=path;self._init()
    def _init(self):
        with sqlite3.connect(self.path) as c:c.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,input TEXT NOT NULL,status TEXT NOT NULL,steps INTEGER NOT NULL DEFAULT 0,result TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,events TEXT NOT NULL DEFAULT "[]",checkpoint TEXT)')
    def create(self,text):
        i=str(uuid.uuid4());t=now()
        with sqlite3.connect(self.path) as c:c.execute('INSERT INTO tasks(id,input,status,created_at,updated_at) VALUES(?,?,?,?,?)',(i,text,'running',t,t))
        return i
    def event(self,i,event):
        with sqlite3.connect(self.path) as c:
            row=c.execute('SELECT events,steps FROM tasks WHERE id=?',(i,)).fetchone();events=json.loads(row[0]);events.append(event)
            c.execute('UPDATE tasks SET events=?,steps=?,checkpoint=?,updated_at=? WHERE id=?',(json.dumps(events),row[1]+1,json.dumps(event),now(),i))
    def finish(self,i,result,status='complete'):
        with sqlite3.connect(self.path) as c:c.execute('UPDATE tasks SET status=?,result=?,updated_at=? WHERE id=?',(status,result,now(),i))
    def recover_interrupted(self):
        with sqlite3.connect(self.path) as c:
            rows=c.execute("SELECT id,input FROM tasks WHERE status='running'").fetchall();c.execute("UPDATE tasks SET status='interrupted',updated_at=? WHERE status='running'",(now(),));return rows
    def get(self,i):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row;r=c.execute('SELECT * FROM tasks WHERE id=?',(i,)).fetchone();return dict(r) if r else None
