from __future__ import annotations
import shutil,subprocess,sys
from pathlib import Path
from .base import ToolResult
class Sandbox:
    def __init__(self,workspace:Path,timeout:int,policy,mode='local',docker_image='python:3.12-slim',memory='512m',cpus='1.0',network=False):
        self.workspace=workspace.resolve(); self.workspace.mkdir(parents=True,exist_ok=True); self.timeout=timeout; self.policy=policy
        self.mode=mode; self.image=docker_image; self.memory=memory; self.cpus=cpus; self.network=network
        if mode=='docker' and not shutil.which('docker'): raise RuntimeError('Docker sandbox requested but docker is unavailable')
    def _safe(self,relative_path:str)->Path:
        p=(self.workspace/relative_path).resolve(); d=self.policy.check_path(p)
        if not d.allowed: raise PermissionError(d.reason)
        return p
    def resolve(self,path:str)->Path:return self._safe(path)
    def list_files(self,path:str='.') -> ToolResult:
        p=self._safe(path)
        if not p.exists():return ToolResult(False,error='Path does not exist')
        return ToolResult(True,[str(x.relative_to(self.workspace)) for x in sorted(p.rglob('*')) if x.is_file()])
    def read_file(self,path:str)->ToolResult:
        p=self._safe(path)
        if not p.is_file():return ToolResult(False,error='File not found')
        return ToolResult(True,p.read_text(encoding='utf-8',errors='replace'))
    def write_file(self,path:str,content:str)->ToolResult:
        p=self._safe(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content,encoding='utf-8')
        return ToolResult(True,{'path':str(p.relative_to(self.workspace)),'bytes':len(content.encode())})
    def delete_file(self,path:str)->ToolResult:
        p=self._safe(path)
        if not p.is_file():return ToolResult(False,error='File not found or directory deletion disabled')
        p.unlink(); return ToolResult(True,{'deleted':path})
    def _run(self,command:str)->ToolResult:
        d=self.policy.check_command(command)
        if not d.allowed:return ToolResult(False,error=d.reason)
        if self.mode=='docker':
            cmd=['docker','run','--rm','-v',f'{self.workspace}:/workspace','-w','/workspace','--memory',self.memory,'--cpus',self.cpus]
            if not self.network:cmd += ['--network','none']
            cmd += [self.image,'sh','-lc',command]
            cp=subprocess.run(cmd,text=True,capture_output=True,timeout=self.timeout)
        else:return ToolResult(False,error='Shell execution requires AIBA_SANDBOX_MODE=docker')
        return ToolResult(cp.returncode==0,{'returncode':cp.returncode,'stdout':cp.stdout[-12000:],'stderr':cp.stderr[-12000:]},None if cp.returncode==0 else 'Command failed')
    def run_shell(self,command:str)->ToolResult:return self._run(command)
    def run_python(self, code: str) -> ToolResult:
        if self.mode == "docker":
            return self._run("python -c " + repr(code))
        return ToolResult(False,error='Python execution requires AIBA_SANDBOX_MODE=docker')

    def patch_file(self, path: str, old: str, new: str, replace_all: bool = False) -> ToolResult:
        """Apply a find-and-replace edit to a workspace text file and return the
        resulting unified-style diff. Uses atomic write (temp + os.replace) so a
        partial edit can never leave a half-written file."""
        import difflib
        import os
        import tempfile
        p = self._safe(path)
        if not p.is_file():
            return ToolResult(False, error="File not found")
        if not old:
            return ToolResult(False, error="old_text must not be empty")
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(False, error=f"Cannot read text file: {exc}")
        count = content.count(old)
        if count == 0:
            return ToolResult(False, error="old_text not found in file")
        if count > 1 and not replace_all:
            return ToolResult(False, error=f"old_text found {count} times; pass replace_all=True or add unique context")
        new_content = content.replace(old, new, -1 if replace_all else 1)
        diff = "".join(difflib.unified_diff(content.splitlines(True), new_content.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
        # Atomic write inside the same directory (safe cross-filesystem).
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return ToolResult(True, {"path": path, "replacements": 1 if not replace_all else count, "diff": diff})

    def archive(self, path: str, format: str = "zip", name: str | None = None) -> ToolResult:
        """Create a zip or tarball of a workspace path. The archive is written
        inside the workspace (never outside it)."""
        import datetime
        src = self._safe(path)
        if not src.exists():
            return ToolResult(False, error="Path does not exist")
        fmt = (format or "zip").lower().strip(".")
        if fmt in {"tar.gz", "tgz"}:
            fmt = "gztar"
        if fmt not in {"zip", "tar", "gztar"}:
            return ToolResult(False, error="format must be zip, tar, gztar, or tgz")
        ext = {"zip": "zip", "tar": "tar", "gztar": "tar.gz"}[fmt]
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = (name or f"{src.name or 'archive'}_{stamp}")
        if base.endswith(f".{ext}"):
            base = base[: -len(ext) - 1]
        dest_dir = self._safe(".archives")
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = dest_dir / base
        try:
            created = shutil.make_archive(
                str(stem), fmt,
                root_dir=str(src.parent),
                base_dir=str(src.name),
            )
        except Exception as exc:
            return ToolResult(False, error=f"Archive failed: {exc}")
        actual = Path(created)
        return ToolResult(True, {"archive": str(actual.relative_to(self.workspace)), "path": path})

    def extract_archive(self, path: str, dest: str = ".extracted") -> ToolResult:
        """Extract a zip/tar archive into a workspace destination. Archive and
        destination are both confined to the workspace; archive paths are
        sanitised to prevent zip-slip (no extraction outside destination)."""
        import zipfile
        import tarfile
        p = self._safe(path)
        if not p.is_file():
            return ToolResult(False, error="Archive file not found")
        out = self._safe(dest)
        out.mkdir(parents=True, exist_ok=True)
        suffix = p.suffix.lower()
        try:
            if suffix in {".zip", ".whl", ".epub"}:
                with zipfile.ZipFile(p) as z:
                    for member in z.infolist():
                        target = (out / member.filename).resolve()
                        if not target.is_relative_to(out):
                            return ToolResult(False, error="Archive contains unsafe path (zip-slip) blocked")
                    z.extractall(out)
            elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
                with tarfile.open(p, "r:*") as t:
                    for member in t.getmembers():
                        target = (out / member.name).resolve()
                        if not target.is_relative_to(out):
                            return ToolResult(False, error="Archive contains unsafe path (zip-slip) blocked")
                    t.extractall(out)
            else:
                return ToolResult(False, error="Unsupported archive format; use .zip or .tar[.gz]")
        except Exception as exc:
            return ToolResult(False, error=f"Extract failed: {exc}")
        count = sum(1 for _ in out.rglob("*") if _.is_file())
        return ToolResult(True, {"extracted_to": dest, "files": count})
