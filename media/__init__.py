"""Media / document capability package.

Read-only extraction lives in :mod:`media.extract`; honest capability probing
for the (not-yet-implemented) OCR/ASR/TTS/image-generation backends lives in
:mod:`media.capabilities`. Importing this package never requires optional
third-party libraries.
"""
from media.capabilities import media_capability_probe
from media.extract import extract_text

__all__ = ["extract_text", "media_capability_probe"]
