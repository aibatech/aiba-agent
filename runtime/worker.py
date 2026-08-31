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
        try:
            handler=self.handlers.get(job['kind'])
            if not handler:raise KeyError(f"No handler for {job['kind']}")
            self.queue.complete(job['id'],handler(job['payload']))
        except Exception as exc:self.queue.fail(job['id'],f'{type(exc).__name__}: {exc}')
        return True
    def run_forever(self):
        self.queue.recover()
        while not self.stop_event.is_set():
            if not self.run_once():self.stop_event.wait(self.poll_seconds)
    def start(self): self.thread=Thread(target=self.run_forever,daemon=True,name='aiba-worker');self.thread.start();return self
    def stop(self): self.stop_event.set(); self.thread and self.thread.join(timeout=3)
