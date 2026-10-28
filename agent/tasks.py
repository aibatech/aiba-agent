from __future__ import annotations
import json,sqlite3,uuid
from datetime import datetime,timezone
from pathlib import Path
from sqlite_utils import connect
def now():return datetime.now(timezone.utc).isoformat()
class TaskStore:
    def __init__(self,path:Path):self.path=path;self._init()
    def _init(self):
        with connect(self.path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,input TEXT NOT NULL,status TEXT NOT NULL,steps INTEGER NOT NULL DEFAULT 0,result TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,events TEXT NOT NULL DEFAULT "[]",checkpoint TEXT)')
            cols={row[1] for row in c.execute('PRAGMA table_info(tasks)')}
            if 'owner' not in cols:c.execute('ALTER TABLE tasks ADD COLUMN owner TEXT')
    def create(self,text,owner=None):
        i=str(uuid.uuid4());t=now()
        with connect(self.path) as c:c.execute('INSERT INTO tasks(id,input,status,created_at,updated_at,owner) VALUES(?,?,?,?,?,?)',(i,text,'running',t,t,owner))
        return i
    def event(self,i,event):
        with connect(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT events,steps FROM tasks WHERE id=?',(i,)).fetchone();events=json.loads(row[0]);events.append(event)
            c.execute('UPDATE tasks SET events=?,steps=?,checkpoint=?,updated_at=? WHERE id=?',(json.dumps(events),row[1]+1,json.dumps(event),now(),i))
    def finish(self,i,result,status='complete'):
        with connect(self.path) as c:c.execute('UPDATE tasks SET status=?,result=?,updated_at=? WHERE id=?',(status,result,now(),i))
    def recover_interrupted(self):
        with connect(self.path) as c:
            rows=c.execute("SELECT id,input FROM tasks WHERE status='running'").fetchall();c.execute("UPDATE tasks SET status='interrupted',updated_at=? WHERE status='running'",(now(),));return rows
    def get(self,i):
        with connect(self.path) as c:
            c.row_factory=sqlite3.Row;r=c.execute('SELECT * FROM tasks WHERE id=?',(i,)).fetchone();return dict(r) if r else None

    def set_plan(self, task_id, steps):
        if not isinstance(steps,list) or not 1<=len(steps)<=20 or any(not isinstance(s,str) or not s.strip() or len(s)>500 for s in steps):
            raise ValueError('Plan requires 1-20 short, nonempty steps')
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT checkpoint FROM tasks WHERE id=?',(task_id,)).fetchone()
            if row is None:raise KeyError(task_id)
            db.execute('CREATE TABLE IF NOT EXISTS task_plans(task_id TEXT PRIMARY KEY, steps TEXT NOT NULL)')
            if db.execute('SELECT 1 FROM task_plans WHERE task_id=?',(task_id,)).fetchone():
                raise ValueError('An active plan cannot be silently replaced')
            db.execute('INSERT INTO task_plans VALUES (?,?)',(task_id,json.dumps([{'description':s,'status':'pending'} for s in steps])))
        return self.plan(task_id)

    def plan(self, task_id):
        with connect(self.path) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_plans'").fetchone():return []
            row=db.execute('SELECT steps FROM task_plans WHERE task_id=?',(task_id,)).fetchone()
            return json.loads(row[0]) if row else []

    def plan_result(self, task_id, index, ok, verified=None):
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT steps FROM task_plans WHERE task_id=?',(task_id,)).fetchone()
            if not row:raise ValueError('No active plan')
            steps=json.loads(row[0])
            if type(index) is not int or not 0<=index<len(steps):raise ValueError('Invalid plan step')
            steps[index]['status']='verified' if ok and verified is True else ('unknown' if ok and verified is False else ('executed' if ok else 'blocked'))
            db.execute('UPDATE task_plans SET steps=? WHERE task_id=?',(json.dumps(steps),task_id))
        return steps

    def plan_start(self, task_id, index, fingerprint):
        """Durably fence a step before dispatch; interrupted effects are never replayed."""
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT steps FROM task_plans WHERE task_id=?',(task_id,)).fetchone()
            if not row:raise ValueError('No active plan')
            steps=json.loads(row[0])
            if type(index) is not int or not 0<=index<len(steps):raise ValueError('Invalid plan step')
            item=steps[index]
            if item['status'] != 'pending':
                raise ValueError('Step already attempted; reconcile its outcome before replay')
            item.update(status='running',fingerprint=fingerprint)
            db.execute('UPDATE task_plans SET steps=? WHERE task_id=?',(json.dumps(steps),task_id))

    def reconcile_step(self, task_id, owner, index, fingerprint, resolution):
        """Operator-only decision after inspecting external state; not a model tool.

        'verified' attests that the intended outcome was independently observed;
        'retry' attests replay is safe. Both are exact-attempt, owner-bound decisions.
        """
        if resolution not in {'verified','retry'}:raise ValueError('Invalid resolution')
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            task=db.execute('SELECT owner,status FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not owner or not task or task[0]!=owner:raise PermissionError('Task unavailable to this owner')
            if task[1]=='running':raise ValueError('Stop the active task before reconciling effects')
            row=db.execute('SELECT steps FROM task_plans WHERE task_id=?',(task_id,)).fetchone()
            if not row:raise ValueError('No active plan')
            steps=json.loads(row[0])
            if type(index) is not int or not 0<=index<len(steps):raise ValueError('Invalid plan step')
            item=steps[index]
            if item.get('fingerprint')!=fingerprint or item['status'] not in {'running','blocked','unknown','executed'}:
                raise ValueError('Exact unresolved attempt required')
            item.update(status='verified' if resolution=='verified' else 'pending',
                        reconciliation={'owner':owner,'fingerprint':fingerprint,'resolution':resolution,'at':now()})
            db.execute('UPDATE task_plans SET steps=? WHERE task_id=?',(json.dumps(steps),task_id))
        return steps

    def begin_resume(self, task_id, owner):
        with connect(self.path) as db:
            return db.execute("UPDATE tasks SET status='running',updated_at=? WHERE id=? AND owner=? AND status IN ('interrupted','partial','failed')",
                              (now(),task_id,owner)).rowcount == 1
