from __future__ import annotations
import time
from threading import Event,Thread
from typing import Callable,Any
from runtime.queue import JobQueue
class Worker:
    def __init__(self,queue:JobQueue,handlers:dict[str,Callable[[dict],Any]],poll_seconds:float=.5): self.queue=queue;self.handlers=handlers;self.poll_seconds=poll_seconds;self.stop_event=Event();self.thread=None
    def run_once(self)->bool:
        job=self.queue.claim()
        if not job:return False
        heartbeat_stop=Event()
        def renew():
            while not heartbeat_stop.wait(10):
                if not self.queue.heartbeat(job['id'],job['claim_token']):break
        heartbeat=Thread(target=renew,daemon=True,name='aiba-job-heartbeat');heartbeat.start()
        try:
            handler=self.handlers.get(job['kind'])
            if not handler:raise KeyError(f"No handler for {job['kind']}")
            self.queue.complete(job['id'],handler(job['payload']),claim_token=job['claim_token'])
        except Exception as exc:self.queue.fail(job['id'],f'{type(exc).__name__}: {exc}',claim_token=job['claim_token'])
        finally:heartbeat_stop.set();heartbeat.join(timeout=1)
        return True
    def run_forever(self):
        self.queue.recover(stale_seconds=60)
        last_recovery=time.monotonic()
        while not self.stop_event.is_set():
            if time.monotonic()-last_recovery >= 30:
                self.queue.recover(stale_seconds=60)
                last_recovery=time.monotonic()
            if not self.run_once():self.stop_event.wait(self.poll_seconds)
    def start(self): self.thread=Thread(target=self.run_forever,daemon=True,name='aiba-worker');self.thread.start();return self
    def stop(self): self.stop_event.set(); self.thread and self.thread.join(timeout=3)
