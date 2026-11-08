from __future__ import annotations
import os,shlex,shutil,subprocess,sys,stat,tempfile,uuid
from execution.backends import DockerBackend,SSHBackend,RemoteDockerComposeBackend
from pathlib import Path
from .base import ToolResult
from .host_files import _parent_descriptor, _DESCRIPTOR_PATHS
class Sandbox:
    def __init__(self,workspace:Path,timeout:int,policy,mode='local',docker_image='python:3.12-slim',memory='512m',cpus='1.0',network=False,
                 max_archive_members:int=10_000, max_archive_bytes_per_file:int=256*1024*1024,
                 max_archive_total_bytes:int=2*1024*1024*1024, backend=None):
        self.workspace=workspace.resolve(); self.workspace.mkdir(parents=True,exist_ok=True); self.timeout=timeout; self.policy=policy
        self.mode=mode; self.image=docker_image; self.memory=memory; self.cpus=cpus; self.network=network
        # Bounded extraction limits (archive-bomb protection). Generous defaults;
        # callers may tighten them per-instance for constrained environments.
        self.max_archive_members=int(max_archive_members)
        self.max_archive_bytes_per_file=int(max_archive_bytes_per_file)
        self.max_archive_total_bytes=int(max_archive_total_bytes)
        if mode=='docker' and not shutil.which('docker'): raise RuntimeError('Docker sandbox requested but docker is unavailable')
        self.backend=backend
        if mode=='docker' and backend is None:self.backend=DockerBackend(self.workspace,self.image,self.memory,self.cpus,self.network)
    def _safe(self,relative_path:str)->Path:
        p=(self.workspace/relative_path).resolve(); d=self.policy.check_path(p)
        if not d.allowed: raise PermissionError(d.reason)
        return p
    def resolve(self,path:str)->Path:return self._safe(path)
    def list_files(self,path:str='.') -> ToolResult:
        p=self._safe(path)
        if not p.exists():return ToolResult(False,error='Path does not exist')
        return ToolResult(True,[str(x.relative_to(self.workspace)) for x in sorted(p.rglob('*')) if x.is_file()])
    def _read_text(self, p: Path, errors='strict'):
        def read(fd):
            with os.fdopen(fd, 'r', encoding='utf-8', errors=errors) as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise PermissionError('Workspace reads require a regular, singly linked file')
                return stream.read()
        if _DESCRIPTOR_PATHS:
            with _parent_descriptor(p) as parent:
                return read(os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent))
        return read(os.open(p, os.O_RDONLY | getattr(os, 'O_BINARY', 0)))

    def _write_bytes(self, p: Path, data: bytes):
        # Replace the directory entry, never truncate an existing inode that may
        # also be reachable through an outside hard link.
        if _DESCRIPTOR_PATHS:
            with _parent_descriptor(p, create=True) as parent:
                temporary='.aiba-write-'+uuid.uuid4().hex
                fd=os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(data);stream.flush();os.fsync(stream.fileno())
                    os.replace(temporary, p.name, src_dir_fd=parent, dst_dir_fd=parent)
                finally:
                    try:os.unlink(temporary, dir_fd=parent)
                    except FileNotFoundError:pass
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd,temporary=tempfile.mkstemp(prefix='.aiba-write-',dir=p.parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,p)
            finally:Path(temporary).unlink(missing_ok=True)

    def read_file(self,path:str)->ToolResult:
        p=self._safe(path)
        try:return ToolResult(True,self._read_text(p,errors='replace'))
        except OSError as exc:return ToolResult(False,error=f'Workspace read failed: {type(exc).__name__}')
    def write_file(self,path:str,content:str)->ToolResult:
        p=self._safe(path)
        try:self._write_bytes(p,content.encode('utf-8'))
        except OSError as exc:return ToolResult(False,error=f'Workspace write failed: {type(exc).__name__}')
        return ToolResult(True,{'path':str(p.relative_to(self.workspace)),'bytes':len(content.encode('utf-8'))})
    def delete_file(self,path:str)->ToolResult:
        p=self._safe(path)
        try:
            if _DESCRIPTOR_PATHS:
                with _parent_descriptor(p) as parent:
                    if not stat.S_ISREG(os.stat(p.name,dir_fd=parent,follow_symlinks=False).st_mode):
                        return ToolResult(False,error='File not found or directory deletion disabled')
                    os.unlink(p.name,dir_fd=parent)
            else:
                if not p.is_file():return ToolResult(False,error='File not found or directory deletion disabled')
                p.unlink()
        except OSError as exc:return ToolResult(False,error=f'Workspace delete failed: {type(exc).__name__}')
        return ToolResult(True,{'deleted':path})
    def _run(self,command:str)->ToolResult:
        d=self.policy.check_command(command)
        if not d.allowed:return ToolResult(False,error=d.reason)
        if self.backend is None:
            # Owner-approved local execution uses the AIBA process OS account.
            # Approval grants authority; it never bypasses OS permissions.
            try:
                # Invoke an explicit OS shell executable without Python's shell=True.
                # This remains an approval-gated owner capability; argv prevents
                # Python from implicitly selecting/interpolating a shell.
                if os.name == 'nt':
                    argv=[os.environ.get('COMSPEC','cmd.exe'),'/d','/s','/c',command]
                else:
                    argv=[os.environ.get('SHELL') or '/bin/sh','-c',command]
                cp=subprocess.run(argv,shell=False,cwd=self.workspace,text=True,capture_output=True,timeout=self.timeout)
                return ToolResult(cp.returncode==0,{'returncode':cp.returncode,'stdout':cp.stdout[-12000:],'stderr':cp.stderr[-12000:]},None if cp.returncode==0 else 'Command failed')
            except Exception as exc:return ToolResult(False,error=f'Local execution failed: {exc}')
        try:r=self.backend.execute(command,self.timeout)
        except Exception as exc:return ToolResult(False,error=f'Execution backend failed: {exc}')
        return ToolResult(r.ok,{'returncode':r.returncode,'stdout':r.stdout[-12000:],'stderr':r.stderr[-12000:]},None if r.ok else 'Command failed')
    def run_shell(self,command:str)->ToolResult:return self._run(command)
    def run_python(self, code: str) -> ToolResult:
        if self.backend is not None:
            return self._run("python3 -c " + repr(code))
        d=self.policy.check_command("python -c <approved code>")
        if not d.allowed:return ToolResult(False,error=d.reason)
        try:
            cp=subprocess.run([sys.executable,'-c',code],shell=False,cwd=self.workspace,text=True,capture_output=True,timeout=self.timeout)
            return ToolResult(cp.returncode==0,{'returncode':cp.returncode,'stdout':cp.stdout[-12000:],'stderr':cp.stderr[-12000:]},None if cp.returncode==0 else 'Command failed')
        except Exception as exc:return ToolResult(False,error=f'Local Python execution failed: {exc}')

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
            content = self._read_text(p)
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(False, error=f"Cannot read text file: {exc}")
        count = content.count(old)
        if count == 0:
            return ToolResult(False, error="old_text not found in file")
        if count > 1 and not replace_all:
            return ToolResult(False, error=f"old_text found {count} times; pass replace_all=True or add unique context")
        new_content = content.replace(old, new, -1 if replace_all else 1)
        diff = "".join(difflib.unified_diff(content.splitlines(True), new_content.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
        try:
            self._write_bytes(p,new_content.encode('utf-8'))
        except OSError as exc:
            return ToolResult(False,error=f'Workspace patch failed: {type(exc).__name__}')
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
        """Extract a zip/tar archive into a workspace destination, safely.

        Hardening driven by a Bandit B202 finding: extraction never calls
        ``TarFile.extractall``/``ZipFile.extractall``. Each member is extracted
        one at a time and every final destination path is re-canonicalised and
        containment-checked immediately before the write. Members are rejected
        when they are absolute, drive-qualified, use ``..`` traversal or
        backslash traversal, are symlinks/hardlinks/devices/FIFOs, or when any
        component already exists as a symlink that could redirect the write
        outside the destination. Bounded limits (member count, per-file and
        total expanded sizes) protect against archive bombs. After a rejected
        member, any files already written by this call are removed so a failed
        extraction never leaves a partial result behind.
        """
        import zipfile
        import tarfile

        use_members_limit = self.max_archive_members
        use_per_file_limit = self.max_archive_bytes_per_file
        use_total_limit = self.max_archive_total_bytes

        p = self._safe(path)
        if not p.is_file():
            return ToolResult(False, error="Archive file not found")
        out = self._safe(dest)
        out.mkdir(parents=True, exist_ok=True)
        suffix = p.suffix.lower()

        def _unsafe(name: str) -> bool:
            """Return True if a raw member name is structurally dangerous."""
            # Normalize backslashes so Windows-style traversal is caught on every OS.
            norm = name.replace("\\", "/")
            # Drive-qualified (Windows): C: or C:/...
            if len(norm) >= 2 and norm[0].isalpha() and norm[1] == ":":
                return True
            # Absolute / rooted.
            if norm.startswith("/"):
                return True
            # Any .. component (after normalization) can escape via traversal.
            for part in norm.split("/"):
                if part == "..":
                    return True
            return False

        def _target(member_name: str) -> Path | None:
            """Return the final canonical destination, or None if unsafe.

            Resolves the full path (shedding any symlinks) and requires the
            result to remain under ``out``. Also rejects the target when an
            existing path component is a symlink that resolves outside ``out``
            (so a pre-seeded symlink cannot redirect the write)."""
            if _unsafe(member_name):
                return None
            candidate = (out / member_name)
            try:
                resolved = candidate.resolve(strict=False)
                resolved.relative_to(out.resolve())
            except ValueError:
                # candidate escapes out, or an existing symlink in the chain
                # points outside out.
                return None
            # If the candidate (or any component) already exists as a symlink,
            # even one that points inside, refuse to follow it — a symlinked
            # destination can be swapped after the check.
            if candidate.is_symlink():
                return None
            for parent in candidate.parents:
                if parent.is_symlink():
                    return None
            return resolved

        def _read_limited(stream, limit: int) -> bytes:
            """Read at most ``limit`` bytes; raise if the member is larger."""
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise EOFError(f"member exceeds per-file extraction limit ({limit} bytes)")
            return data

        extracted_this_call: list[Path] = []

        def _cleanup_partial() -> None:
            """Remove anything this call already wrote (best-effort)."""
            for fp in reversed(extracted_this_call):
                try:
                    if fp.is_file() or fp.is_symlink():
                        fp.unlink(missing_ok=True)
                    elif fp.is_dir():
                        fp.rmdir()
                except OSError:
                    pass

        def _reject(reason: str) -> ToolResult:
            _cleanup_partial()
            return ToolResult(False, error=reason + " (partial extraction rolled back)")

        try:
            total = 0
            if suffix in {".zip", ".whl", ".epub"}:
                with zipfile.ZipFile(p) as z:
                    if len(z.infolist()) > use_members_limit:
                        return _reject(f"Archive exceeds maximum member count ({use_members_limit})")
                    for member in z.infolist():
                        if member.is_dir():
                            continue
                        if member.file_size > use_per_file_limit:
                            return _reject(f"Member exceeds per-file extraction limit ({use_per_file_limit} bytes)")
                        tgt = _target(member.filename)
                        if tgt is None:
                            return _reject("Archive contains unsafe path (zip-slip) blocked")
                        try:
                            with z.open(member) as f:
                                data = _read_limited(f, use_per_file_limit)
                        except zipfile.BadZipFile as exc:
                            return _reject(f"Corrupt zip member: {exc}")
                        total += len(data)
                        if total > use_total_limit:
                            return _reject(f"Archive exceeds total expanded size limit ({use_total_limit} bytes)")
                        tgt.parent.mkdir(parents=True, exist_ok=True)
                        tgt.write_bytes(data)
                        extracted_this_call.append(tgt)
            elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
                with tarfile.open(p, "r:*") as t:
                    members = t.getmembers()
                    if len(members) > use_members_limit:
                        return _reject(f"Archive exceeds maximum member count ({use_members_limit})")
                    for member in members:
                        if member.isdir():
                            continue
                        # Reject symlinks/hardlinks (can redirect writes outside),
                        # devices, FIFOs, and any other special member type.
                        if member.issym() or member.islnk() or member.isdev() or not member.isfile():
                            return _reject("Archive contains unsafe link/device/special member (zip-slip) blocked")
                        if member.size > use_per_file_limit:
                            return _reject(f"Member exceeds per-file extraction limit ({use_per_file_limit} bytes)")
                        tgt = _target(member.name)
                        if tgt is None:
                            return _reject("Archive contains unsafe path (zip-slip) blocked")
                        total += member.size
                        if total > use_total_limit:
                            return _reject(f"Archive exceeds total expanded size limit ({use_total_limit} bytes)")
                        f = t.extractfile(member)
                        if f is None:
                            continue
                        try:
                            data = _read_limited(f, use_per_file_limit)
                        except OSError as exc:
                            return _reject(f"Cannot read tar member: {exc}")
                        tgt.parent.mkdir(parents=True, exist_ok=True)
                        tgt.write_bytes(data)
                        extracted_this_call.append(tgt)
            else:
                return ToolResult(False, error="Unsupported archive format; use .zip or .tar[.gz]")
        except EOFError as exc:
            _cleanup_partial()
            return ToolResult(False, error=str(exc))
        except Exception as exc:
            _cleanup_partial()
            return ToolResult(False, error=f"Extract failed: {exc}")
        count = sum(1 for _ in out.rglob("*") if _.is_file())
        return ToolResult(True, {"extracted_to": dest, "files": count})
