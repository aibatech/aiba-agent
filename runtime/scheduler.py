from __future__ import annotations
import json,sqlite3,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from sqlite_utils import connect
from runtime.queue import JobQueue

def now_dt(): return datetime.now(timezone.utc)
class Scheduler:
    def __init__(self,path:Path,queue:JobQueue): self.path=path;self.queue=queue;self._init()
    def _init(self):
        with connect(self.path) as c:c.execute('''CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,interval_seconds INTEGER NOT NULL,next_run TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1)''')
    def add_interval(self,name:str,kind:str,payload:dict,seconds:int)->str:
        if seconds<60:raise ValueError('Minimum schedule interval is 60 seconds')
        i=str(uuid.uuid4()); nxt=(now_dt()+timedelta(seconds=seconds)).isoformat()
        with connect(self.path) as c:c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,1)',(i,name,kind,json.dumps(payload),seconds,nxt))
        return i
    def tick(self)->int:
        now=now_dt();count=0
        with connect(self.path) as c:
            rows=c.execute('SELECT id,kind,payload,interval_seconds FROM schedules WHERE enabled=1 AND next_run<=?',(now.isoformat(),)).fetchall()
            for i,kind,payload,seconds in rows:
                self.queue.enqueue(kind,json.loads(payload));c.execute('UPDATE schedules SET next_run=? WHERE id=?',((now+timedelta(seconds=seconds)).isoformat(),i));count+=1
        return count

from threading import Event,Thread
class SchedulerRunner:
    def __init__(self,scheduler:Scheduler,poll_seconds:float=1.0):self.scheduler=scheduler;self.poll_seconds=poll_seconds;self.stop_event=Event();self.thread=None
    def run_forever(self):
        while not self.stop_event.is_set():self.scheduler.tick();self.stop_event.wait(self.poll_seconds)
    def start(self):self.thread=Thread(target=self.run_forever,daemon=True,name='aiba-scheduler');self.thread.start();return self
    def stop(self):self.stop_event.set();self.thread and self.thread.join(timeout=3)
