"""Phase 8 — media_extract model tool.

Registers read-only document/text extraction on workspace files.

Every read is workspace-confined (the injected ``Sandbox.resolve`` enforces
``policy.check_path``) and every format parser lives behind an honest optional
dependency, mirroring how ``read_file`` (local) and the browser/web tools are
wired. Missing optional libraries return a clear "install optional support"
diagnostic rather than a partial or fabricated parse. Because extraction only
reads and never writes, no new write/export path is introduced here — any
persisting of results must go through the existing approval-gated
``write_file`` space.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


class MediaExtraction:
    """Binds the safe, dependency-versioned extractor to a workspace Sandbox."""

    def __init__(self, sandbox, *, max_chars: int = 40_000):
        self._sandbox = sandbox
        self._max_chars = int(max_chars)

    def media_extract(self, path: str) -> ToolResult:
        """Extract readable text from a workspace document/image.

        Supports PDF, DOCX, XLSX, PPTX (optional ``[media]`` deps), CSV, plain
        text/markdown, and common image metadata. The file must already be
        inside the approved workspace. Content is treated as untrusted data —
        never executed, never evaluated.
        """
        if not path or not isinstance(path, str):
            return ToolResult(False, error="path must be a non-empty string")
        restricted = path.replace("\x00", "")  # never hand NUL into the filesystem
        try:
            # resolve confines to workspace (policy.check_path); result is an
            # absolute Path to an existing-or-intended file.
            real = self._sandbox.resolve(restricted)
        except PermissionError as exc:
            return ToolResult(False, error=f"Path outside approved workspace: {exc}")
        try:
            import media.extract as ex
            result = ex.extract_text(str(real), limit=self._max_chars)
        except FileNotFoundError as exc:
            return ToolResult(False, error=str(exc))
        except PermissionError as exc:
            return ToolResult(False, error=f"Path outside approved workspace: {exc}")
        except (RuntimeError, ValueError, OSError) as exc:
            return ToolResult(False, error=str(exc))
        except Exception as exc:  # defensive: never crash the loop on a bad doc
            return ToolResult(False, error=f"Extraction failed: {type(exc).__name__}: {exc}")
        return ToolResult(True, result)


def build_media_tools(extractor: MediaExtraction) -> list[Tool]:
    """Return the registered media tools for a live MediaExtraction bound to a Sandbox."""
    return [
        Tool(
            "media_extract",
            "Extract readable text/metadata from a workspace file (PDF, DOCX, "
            "XLSX, PPTX, CSV, markdown/text, or common image metadata). The "
            "file must already be inside the approved workspace; content is "
            "treated as untrusted data and is never executed.",
            extractor.media_extract,
            {"type": "object",
             "properties": {"path": {"type": "string"}},
             "required": ["path"],
             "additionalProperties": False},
        ),
    ]
