from __future__ import annotations
import json, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class AuditLog:
    def __init__(self, path: Path):
        self.path=path; self.path.parent.mkdir(parents=True,exist_ok=True); self._lock=threading.Lock()
    def record(self, event: str, **data: Any) -> None:
        row={"timestamp":datetime.now(timezone.utc).isoformat(),"event":event,**data}
        with self._lock, self.path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
