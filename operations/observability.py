from __future__ import annotations
import json,threading,time,traceback,uuid
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

class Metrics:
    def __init__(self):self.started=time.monotonic();self._lock=threading.Lock();self.counters=Counter();self.gauges={}
    def increment(self,name,value=1,**labels):
        key=(name,tuple(sorted((str(k),str(v)) for k,v in labels.items())))
        with self._lock:self.counters[key]+=value
    def set(self,name,value):
        with self._lock:self.gauges[name]=value
    def snapshot(self):
        with self._lock:return {'uptime_seconds':round(time.monotonic()-self.started,3),'counters':{'|'.join([k[0],*(f'{a}={b}' for a,b in k[1])]):v for k,v in self.counters.items()},'gauges':dict(self.gauges)}
    def prometheus(self):
        lines=['# TYPE aiba_uptime_seconds gauge',f'aiba_uptime_seconds {time.monotonic()-self.started:.3f}']
        with self._lock:
            for (name,labels),value in sorted(self.counters.items()):
                label_text=',' .join(f'{k}="{v.replace(chr(34), chr(92)+chr(34))}"' for k,v in labels)
                lines.append(f'aiba_{name}{{{label_text}}} {value}' if labels else f'aiba_{name} {value}')
            for name,value in sorted(self.gauges.items()):lines.append(f'aiba_{name} {value}')
        return '\n'.join(lines)+'\n'

class CrashReporter:
    def __init__(self,logs_dir:Path):self.path=logs_dir/'crashes.jsonl';self.path.parent.mkdir(parents=True,exist_ok=True);self._lock=threading.Lock()
    def capture(self,exc,context=None):
        crash_id=str(uuid.uuid4());row={'id':crash_id,'timestamp':datetime.now(timezone.utc).isoformat(),'type':type(exc).__name__,'message':str(exc)[:2000],'context':context or {},'traceback':''.join(traceback.format_exception(exc))[-12000:]}
        with self._lock,self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,default=str)+'\n')
        return crash_id
