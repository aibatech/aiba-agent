from __future__ import annotations
import json,threading,time,traceback,uuid,math
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

class Metrics:
    def __init__(self):self.started=time.monotonic();self._lock=threading.Lock();self.counters=Counter();self.gauges={}
    def increment(self,name,value=1,**labels):
        # Closed diagnostic schema: paths, arbitrary labels, metric names and
        # plugin exception class names can contain private data or explode cardinality.
        names={'tasks_total','task_failures_total','http_errors_total','http_requests_total'}
        if not isinstance(name,str) or name not in names:name='other_total'
        safe={}
        if 'status' in labels:
            status=str(labels['status'])
            safe['status']=status if status in {'ok','complete','partial','failed','cancelled','waiting','interrupted'} or (status.isascii() and status.isdigit() and len(status)==3 and 100<=int(status)<=599) else 'other'
        if 'method' in labels:
            method=labels['method']
            safe['method']=method if isinstance(method,str) and method in {'GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS'} else 'OTHER'
        if 'error' in labels:
            error=labels['error']
            safe['error']=error if isinstance(error,str) and error in {'ValueError','RuntimeError','TimeoutError','ConnectionError','PermissionError','ExecutionStopped','OSError','KeyError'} else 'OtherError'
        if not isinstance(value,(int,float)) or not math.isfinite(value):return
        key=(name,tuple(sorted(safe.items())))
        with self._lock:self.counters[key]+=value
    def set(self,name,value):
        if name != 'last_http_latency_ms' or not isinstance(value,(int,float)) or not math.isfinite(value):return
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
        crash_id=str(uuid.uuid4())
        # Exception text, source lines, locals and request paths can contain secrets.
        frames=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-30:]]
        safe_context={}
        if isinstance(context,dict):
            candidate=context.get('task_id')
            if isinstance(candidate,str):
                try:safe_context['task_id']=str(uuid.UUID(candidate))
                except ValueError:pass
            if isinstance(context.get('method'),str) and context['method'] in {'GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS'}:
                safe_context['method']=context['method']
        row={'id':crash_id,'timestamp':datetime.now(timezone.utc).isoformat(),'type':type(exc).__name__,
             'message':'Exception details withheld from diagnostics','context':safe_context,'frames':frames}
        with self._lock,self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,default=str)+'\n')
        return crash_id
