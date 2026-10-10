"""Secret-safe owner administration helpers.

Secret values are copied runtime-to-runtime and are never returned in ToolResult,
conversation context, or audit arguments. Explicit approval is supplied by the
ToolRegistry permission row.
"""
from __future__ import annotations
import os,re,tempfile
from pathlib import Path
from .base import ToolResult

_KEY=re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")

def _env(path:str)->Path:
    p=Path(os.path.expanduser(os.path.expandvars(path))).resolve()
    if not p.is_file(): raise FileNotFoundError(str(p))
    return p

def _parse(path:Path)->dict[str,str]:
    out={}
    for raw in path.read_text(encoding="utf-8",errors="replace").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,v=line.split("=",1);k=k.strip()
        if _KEY.fullmatch(k): out[k]=v.strip()
    return out

class SecretAdmin:
    def list_names(self,source_path:str)->ToolResult:
        try:return ToolResult(True,{"path":str(_env(source_path)),"keys":sorted(_parse(_env(source_path)).keys())})
        except Exception as exc:return ToolResult(False,error=f"Cannot inspect secret names: {type(exc).__name__}: {exc}")

    def copy_env_secret(self,source_path:str,destination_path:str,key:str)->ToolResult:
        if not _KEY.fullmatch(str(key or "")):return ToolResult(False,error="Invalid environment key name")
        try:
            src=_env(source_path); values=_parse(src)
            if key not in values:return ToolResult(False,error=f"Secret key not found: {key}")
            dest=Path(os.path.expanduser(os.path.expandvars(destination_path)))\n            if dest.is_symlink(): return ToolResult(False,error="Destination symlinks are not supported")\n            dest=dest.resolve()
            if src == dest: return ToolResult(False,error="Source and destination must differ")
            if dest.is_symlink(): return ToolResult(False,error="Destination symlinks are not supported")
            dest.parent.mkdir(parents=True,exist_ok=True)
            original=dest.read_text(encoding="utf-8") if dest.is_file() else ""
            lines=original.splitlines(keepends=True)
            replacement=key+"="+values[key]+"\\n"
            matched=False
            for i,line in enumerate(lines):
                if line.strip().startswith(key+"="):
                    lines[i]=replacement
                    matched=True
            if not matched:
                if lines and not lines[-1].endswith("\\n"): lines.append("\\n")
                lines.append(replacement)
            fd,tmp=tempfile.mkstemp(prefix=".aiba-secret-",dir=str(dest.parent))
            try:
                os.fchmod(fd,0o600)
                with os.fdopen(fd,"w",encoding="utf-8") as handle:
                    handle.writelines(lines)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp,dest)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            return ToolResult(True,{"copied":key,"destination":str(dest),"secret_value":"[REDACTED]"})
        except Exception as exc:return ToolResult(False,error=f"Secret transfer failed: {type(exc).__name__}: {exc}")
