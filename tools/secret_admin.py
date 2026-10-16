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

_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Z][A-Z0-9_]{1,127})\s*=\s*(.*)$")


def _assignment(raw: str):
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    match = _ASSIGNMENT.fullmatch(line)
    if not match:
        raise ValueError("Unsupported environment assignment")
    key, value = match.groups()
    if value.startswith(("'", '\"')):
        quote = value[0]
        escaped = False
        closing = None
        for index, char in enumerate(value[1:], 1):
            if char == quote and not escaped:
                closing = index
                break
            escaped = char == "\\" and not escaped
        if closing is None or (value[closing + 1:].strip() and
                               not value[closing + 1:].lstrip().startswith("#")):
            raise ValueError("Multiline or malformed environment values are unsupported")
    if "\x00" in value:
        raise ValueError("Invalid environment value")
    return key, value


def _parse(path: Path) -> dict[str, str]:
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        assignment = _assignment(raw)
        if assignment is None:
            continue
        key, value = assignment
        if key in out:
            raise ValueError("Duplicate environment assignments are unsupported")
        out[key] = value
    return out

class SecretAdmin:
    def list_names(self,source_path:str)->ToolResult:
        try:return ToolResult(True,{"path":str(_env(source_path)),"keys":sorted(_parse(_env(source_path)).keys())})
        except Exception as exc:return ToolResult(False,error=f"Cannot inspect secret names: {type(exc).__name__}")

    def copy_env_secret(self,source_path:str,destination_path:str,key:str)->ToolResult:
        if not _KEY.fullmatch(str(key or "")):return ToolResult(False,error="Invalid environment key name")
        try:
            src=_env(source_path); values=_parse(src)
            if key not in values:return ToolResult(False,error=f"Secret key not found: {key}")
            dest=Path(os.path.expanduser(os.path.expandvars(destination_path)))
            if dest.is_symlink(): return ToolResult(False,error="Destination symlinks are not supported")
            dest=dest.resolve()
            if src == dest: return ToolResult(False,error="Source and destination must differ")
            if dest.is_symlink(): return ToolResult(False,error="Destination symlinks are not supported")
            dest.parent.mkdir(parents=True,exist_ok=True)
            original=dest.read_text(encoding="utf-8") if dest.is_file() else ""
            lines=original.splitlines(keepends=True)
            replacement=key+"="+values[key]+"\n"
            matched=False
            for i,line in enumerate(lines):
                assignment = _assignment(line)
                if assignment is not None and assignment[0] == key:
                    lines[i]=replacement
                    matched=True
            if not matched:
                if lines and not lines[-1].endswith("\n"): lines.append("\n")
                lines.append(replacement)
            fd,tmp=tempfile.mkstemp(prefix=".aiba-secret-",dir=str(dest.parent))
            try:
                with os.fdopen(fd,"w",encoding="utf-8") as handle:
                    if hasattr(os,"fchmod"):os.fchmod(handle.fileno(),0o600)
                    handle.writelines(lines)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp,dest)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            return ToolResult(True,{"copied":key,"destination":str(dest),"secret_value":"[REDACTED]"})
        except Exception as exc:return ToolResult(False,error=f"Secret transfer failed: {type(exc).__name__}")
