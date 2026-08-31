from __future__ import annotations
from collections import defaultdict
from threading import RLock
from typing import Any, Callable

class EventBus:
    def __init__(self):
        self._handlers: dict[str,list[Callable[[dict[str,Any]],None]]] = defaultdict(list)
        self._lock=RLock()
    def subscribe(self,event_type:str,handler:Callable[[dict[str,Any]],None])->None:
        with self._lock:self._handlers[event_type].append(handler)
    def publish(self,event_type:str,**payload:Any)->None:
        event={'type':event_type,**payload}
        with self._lock: handlers=list(self._handlers.get(event_type,[]))+list(self._handlers.get('*',[]))
        for handler in handlers:
            try: handler(event)
            except Exception: pass
