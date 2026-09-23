"""Approval-gated, read-only host filesystem access for a paired desktop.

These tools are intentionally separate from the sandbox. They never write, execute,
or silently broaden access. The ToolRegistry approval prompt includes the requested
path/query before each operation.
"""
from __future__ import annotations

import os
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


class HostFiles:
    """Read-only host file discovery. Registry approval + paired node are required."""

    def __init__(self, node_gate=None):
        self.node_gate = node_gate

    def _authorize(self) -> ToolResult | None:
        if self.node_gate is None:
            return ToolResult(False, error="Host files require a paired computer node.")
        allowed, reason = self.node_gate.authorize("files_read")
        if not allowed:
            return ToolResult(False, error=reason)
        return None

    def list(self, path: str, limit: int = 100) -> ToolResult:
        denied = self._authorize()
        if denied: return denied
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
        denied = self._authorize()
        if denied: return denied
        p = _safe_host_path(path)
        if not p.exists() or not p.is_file():
            return ToolResult(False, error=f"Host file does not exist or is not a file: {p}")
        cap = min(max(int(max_chars), 1), _MAX_READ)
        try:
            data = p.read_text(encoding="utf-8", errors="replace")[:cap]
        except PermissionError as exc:
            return ToolResult(False, error=f"Host file access denied by OS: {exc}")
        return ToolResult(True, {"path": str(p), "text": data, "chars": len(data), "truncated": len(data) >= cap})

    def search(self, root: str, name: str, limit: int = 50, max_depth: int = 6) -> ToolResult:
        denied = self._authorize()
        if denied: return denied
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
