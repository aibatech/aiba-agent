from __future__ import annotations
import json, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PRIVATE_FIELDS = ('password', 'passwd', 'token', 'authorization', 'cookie', 'secret',
                   'credential', 'passphrase', 'private_key', 'api_key', 'apikey')
_OPAQUE_FIELDS = {'text','content','command','code','prompt','question','summary','answer',
                  'output','output_preview','response_preview','error','detail','objective',
                  'objectives','instruction','context','traceback','url','path','source_path',
                  'destination_path','task','selector','value','source','preview','reason'}


def sanitise_audit(value):
    """Withhold known payload fields and credential keys; retain operational metadata."""
    if isinstance(value,dict):
        return {str(key):('[REDACTED]' if str(key).casefold() in _OPAQUE_FIELDS or
                any(marker in str(key).casefold() for marker in _PRIVATE_FIELDS) else sanitise_audit(item))
                for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [sanitise_audit(item) for item in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    return '[unsupported value withheld]'


class AuditLog:
    def __init__(self, path: Path):
        self.path=path; self.path.parent.mkdir(parents=True,exist_ok=True); self._lock=threading.Lock()
    def record(self, event: str, **data: Any) -> None:
        row={"timestamp":datetime.now(timezone.utc).isoformat(),"event":event,**sanitise_audit(data)}
        with self._lock, self.path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
