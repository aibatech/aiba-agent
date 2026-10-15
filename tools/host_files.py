"""Approval-gated host filesystem access for an owner-controlled AIBA session.

These tools are intentionally separate from the sandbox. Mutations require exact
registry approvals; they never execute files or silently broaden access. The ToolRegistry approval prompt includes the requested
path/query before each operation.
"""
from __future__ import annotations

import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .base import ToolResult

_SENSITIVE_PARTS = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", "keychains",
    "login keychain-db", "credentials", "secrets",
}
_MAX_READ = 200_000
_MAX_RESULTS = 100


def _safe_host_path(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise ValueError("host path must not be empty")
    p = Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()
    lowered = {part.lower() for part in p.parts}
    blocked = lowered & _SENSITIVE_PARTS
    if blocked:
        raise PermissionError(
            "Sensitive credential/key directories are not exposed through host-file tools: "
            + ", ".join(sorted(blocked))
        )
    return p


@contextmanager
def _parent_descriptor(path: Path, create: bool = False):
    """Pin each POSIX ancestor without following a replacement symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:-1]:
            if create:
                try: os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


_DESCRIPTOR_PATHS = os.name == "posix" and hasattr(os, "O_NOFOLLOW")


class HostFiles:
    """Host file operations. Registry policy supplies exact user approval."""

    def list(self, path: str, limit: int = 100) -> ToolResult:
        p = _safe_host_path(path)
        if not p.exists():
            return ToolResult(False, error=f"Host path does not exist: {p}")
        if not p.is_dir():
            return ToolResult(False, error=f"Host path is not a directory: {p}")
        cap = min(max(int(limit), 1), _MAX_RESULTS)
        rows: list[dict[str, Any]] = []
        try:
            for child in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                try:
                    _safe_host_path(str(child))
                except PermissionError:
                    continue
                rows.append({"name": child.name, "path": str(child), "type": "dir" if child.is_dir() else "file"})
                if len(rows) >= cap:
                    break
        except PermissionError as exc:
            return ToolResult(False, error=f"Host directory access denied by OS: {exc}")
        return ToolResult(True, {"path": str(p), "entries": rows, "truncated": len(rows) >= cap})

    def read(self, path: str, max_chars: int = 50_000) -> ToolResult:
        p = _safe_host_path(path)
        if not p.exists() or not p.is_file():
            return ToolResult(False, error=f"Host file does not exist or is not a file: {p}")
        cap = min(max(int(max_chars), 1), _MAX_READ)
        try:
            if _DESCRIPTOR_PATHS:
                with _parent_descriptor(p) as parent:
                    fd = os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                            raise PermissionError("Only regular files can be read")
                        data = stream.read(cap + 1)
            else:
                with p.open("r", encoding="utf-8", errors="replace") as stream:
                    data = stream.read(cap + 1)
        except OSError as exc:
            return ToolResult(False, error=f"Host file access denied by OS: {type(exc).__name__}")
        return ToolResult(True, {"path": str(p), "text": data[:cap], "chars": len(data[:cap]), "truncated": len(data) > cap})

    def search(self, root: str, name: str, limit: int = 50, max_depth: int = 6) -> ToolResult:
        base = _safe_host_path(root)
        if not base.exists() or not base.is_dir():
            return ToolResult(False, error=f"Host root does not exist or is not a directory: {base}")
        needle = (name or "").strip().lower()
        if not needle:
            return ToolResult(False, error="name must not be empty")
        cap = min(max(int(limit), 1), _MAX_RESULTS)
        depth_cap = min(max(int(max_depth), 1), 12)
        found: list[dict[str, str]] = []
        base_depth = len(base.parts)
        for current, dirs, files in os.walk(base, topdown=True, followlinks=False):
            cur = Path(current)
            if len(cur.parts) - base_depth >= depth_cap:
                dirs[:] = []
            safe_dirs = []
            for d in dirs:
                try:
                    _safe_host_path(str(cur / d))
                    safe_dirs.append(d)
                except PermissionError:
                    pass
            dirs[:] = safe_dirs
            for item in dirs + files:
                if needle in item.lower():
                    p = cur / item
                    found.append({"name": item, "path": str(p), "type": "dir" if p.is_dir() else "file"})
                    if len(found) >= cap:
                        return ToolResult(True, {"root": str(base), "query": name, "matches": found, "truncated": True})
        return ToolResult(True, {"root": str(base), "query": name, "matches": found, "truncated": False})

    def write(self, path: str, content: str) -> ToolResult:
        p = _safe_host_path(path)
        try:
            if _DESCRIPTOR_PATHS:
                with _parent_descriptor(p, create=True) as parent:
                    temporary = ".aiba-write-" + uuid.uuid4().hex
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as stream:
                            stream.write(content); stream.flush(); os.fsync(stream.fileno())
                        os.replace(temporary, p.name, src_dir_fd=parent, dst_dir_fd=parent)
                    finally:
                        try: os.unlink(temporary, dir_fd=parent)
                        except FileNotFoundError: pass
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=".aiba-write-", dir=p.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        stream.write(content); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, p)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        except OSError as exc:
            return ToolResult(False, error=f"Host file write denied by OS: {type(exc).__name__}")
        return ToolResult(True, {"path": str(p), "bytes": len(content.encode("utf-8"))})

    def delete(self, path: str) -> ToolResult:
        p = _safe_host_path(path)
        try:
            if _DESCRIPTOR_PATHS:
                with _parent_descriptor(p) as parent:
                    if not stat.S_ISREG(os.stat(p.name, dir_fd=parent, follow_symlinks=False).st_mode):
                        raise PermissionError("Only regular files can be deleted")
                    os.unlink(p.name, dir_fd=parent)
            else:
                if not p.is_file(): return ToolResult(False, error="Host file does not exist or is not a file")
                p.unlink()
        except OSError as exc:
            return ToolResult(False, error=f"Host file delete denied by OS: {type(exc).__name__}")
        return ToolResult(True, {"deleted": str(p)})
