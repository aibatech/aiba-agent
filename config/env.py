from __future__ import annotations
import os,re
from pathlib import Path

KEY_RE=re.compile(r'^[A-Z][A-Z0-9_]*$')

def load_env(path:Path,override:bool=False)->dict[str,str]:
    """Load a small, strict .env file without executing shell syntax."""
    loaded={}
    if not path.is_file():return loaded
    for number,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        if '=' not in line:raise ValueError(f'Invalid .env line {number}')
        key,value=line.split('=',1);key=key.strip();value=value.strip()
        if not KEY_RE.fullmatch(key):raise ValueError(f'Invalid .env key on line {number}')
        if len(value)>=2 and value[0]==value[-1] and value[0] in {'"',"'"}:value=value[1:-1]
        if override or key not in os.environ:os.environ[key]=value
        loaded[key]=value
    return loaded

def quote_env(value:str)->str:
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('\n','')+'"'
