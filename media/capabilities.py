"""Honest media capability probes (Phase 8).

AIBA cannot truly claim OCR, speech-to-text, text-to-speech, or image
generation are available until a real backend *and its tests* exist. Rather
than ship hollow placeholders that pretend to work, this module surfaces those
capabilities as **probes that report the truth**: each answers "is a
functioning backend installed?" and every one returns ``False`` (with an
actionable reason) until the operator adds a supported dependency. Do NOT turn
a probe green without a working backend and passing tests — that would be
misreporting an unavailable capability to the model.

The *document text extraction* capability (PDF/DOCX/XLSX/PPTX/CSV + plain
text/markdown) is provided by :mod:`media.extract` and reports its own
per-format availability via the optional ``[media]`` dependency probes.
"""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass, field
from typing import Any


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _binary_present(exe: str) -> bool:
    return shutil.which(exe) is not None


def _capable(label: str, present: bool, reason_fmt: str) -> dict[str, Any]:
    """Build a single probe entry: honest (available or why not)."""
    return {
        "capability": label,
        "available": present,
        "detail": "ready" if present else reason_fmt,
    }


def media_capability_probe() -> dict[str, Any]:
    """Return the status of every media-family capability.

    ``text_extraction`` is genuinely implemented (documented in
    :mod:`media.extract`) — its independent availability follows the optional
    ``[media]`` deps and the base ``desktop`` (Pillow) extra. OCR / ASR / TTS /
    image generation are NOT implemented and correctly report unavailable with
    the concrete missing dependency named, so an operator can decide whether
    to add one.
    """
    pdf_ok = _module_present("pypdf")
    docx_ok = _module_present("docx")
    xlsx_ok = _module_present("openpyxl")
    pptx_ok = _module_present("pptx")
    pil_ok = _module_present("PIL")
    return {
        "family": "media",
        "probes": [
            _capable("text_extraction", True,
                     "text extraction core is always present"),
            _capable("pdf_extraction", pdf_ok, "requires optional dep pypdf "
                     "(pip install aiba-agent[media])"),
            _capable("docx_extraction", docx_ok,
                     "requires optional dep python-docx (pip install aiba-agent[media])"),
            _capable("xlsx_extraction", xlsx_ok,
                     "requires optional dep openpyxl (pip install aiba-agent[media])"),
            _capable("pptx_extraction", pptx_ok,
                     "requires optional dep python-pptx (pip install aiba-agent[media])"),
            _capable("image_metadata", pil_ok,
                     "requires Pillow (pip install aiba-agent[desktop] or [all])"),
            _capable("ocr", _module_present("pytesseract") and _binary_present("tesseract"),
                     "requires pytesseract + the tesseract binary; not yet a supported backend"),
            _capable("speech_to_text", False,
                     "no speech-to-text backend configured; not yet a supported capability"),
            _capable("text_to_speech", False,
                     "no text-to-speech backend configured; not yet a supported capability"),
            _capable("image_generation", False,
                     "no image-generation backend configured; not yet a supported capability"),
        ],
    }


@dataclass
class MediaStatus:
    """Structured media capability summary for diagnostics/doctor output."""

    report: dict[str, Any] = field(default_factory=dict)

    def ready_capabilities(self) -> list[str]:
        return [p["capability"] for p in self.report.get("probes", []) if p["available"]]

    def unavailable(self) -> list[dict[str, Any]]:
        return [p for p in self.report.get("probes", []) if not p["available"]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
