"""Optional-dependency availability + sensitivity helpers for the MCP client.

The real ``mcp`` SDK (Pip extra ``[mcp]`` / included in ``[all]``) is imported
lazily: no AIBA module that may load in a base ``[api]`` install (which does
*not* ship ``mcp``) ever imports ``mcp`` at module top level. These helpers are
the single gate every Phase 7 path (loop wiring, diagnostics, manager) consults
so a missing SDK is reported honestly as an actionable \"install the optional
extra\" diagnostic and never crashes.

The import probe is monkeypatchable so deterministic tests can simulate a
missing SDK without uninstalling packages (see the Phase 7 test module).
"""
from __future__ import annotations

import importlib.util
from typing import Any, Dict, List, Tuple, Union

# Probe label used by config/capability_manifest.json optional_dependency and
# by docs/diagnostics. ``python:mcp`` mirrors the media extra's ``python:pypdf``
# convention used in capability _dep_satisfied.
EXTRA_LABEL = "python:mcp"

#: Module-level override used by tests to simulate a missing SDK. ``None``
#: (the default) probes the real interpreter; a boolean forces the result.
_AVAILABILITY_OVERRIDE: bool | None = None

#: Keys whose values are scrubbed from audit/diagnostic payloads. Matched
#: case-insensitively (and treating ``-`` as ``_``) on the key name; nested
#: dict/list values are traversed.
_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "auth",
    "private_key",
)

#: When a value forces a scrub regardless of the key (e.g. an inline bearer
#: token). Kept conservative so normal text is never mangled.
_VALUE_MARKERS = ("bearer ", "password=", "token=", "-----begin")


def sdk_available() -> bool:
    """Return whether the MCP SDK is installed (or fake-forced by tests)."""
    if _AVAILABILITY_OVERRIDE is not None:
        return _AVAILABILITY_OVERRIDE
    try:
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


def set_sdk_available_override(value: bool | None) -> None:
    """Override the SDK probe for tests; ``None`` re-probes the interpreter."""
    global _AVAILABILITY_OVERRIDE  # noqa: PLW0603
    _AVAILABILITY_OVERRIDE = value


def is_secret_key(key: str) -> bool:
    """True if *key* names a credential-like value (case-insensitive)."""
    low = (key or "").lower().replace("-", "_")
    return any(m in low for m in _SECRET_KEY_MARKERS)


def _redact_value(value: str) -> bool:
    low = value.lower()
    return any(m in low for m in _VALUE_MARKERS)


#: Type of a JSON-serialisable, possibly-nested scrub result so callers can index.
JsonLike = Union[str, int, float, bool, None, List["JsonLike"], Dict[str, "JsonLike"]]


def scrub_secrets(obj: object) -> Any:
    """Return *obj* with secret-like values redacted.

    Recurses through dicts/lists/tuples. A leaf is redacted to the constant
    ``[REDACTED by AIBA]`` when its key looks secret (``is_secret_key``) or when
    the value itself looks secret-like (e.g. an inline bearer token), so nothing
    leaks into audit logs, diagnostics or returned tool payloads. Returns ``Any``
    so callers may index the result without re-casting.
    """
    if isinstance(obj, dict):
        return {
            str(k): (
                "[REDACTED by AIBA]"
                if is_secret_key(str(k)) or (isinstance(v, str) and _redact_value(v))
                else scrub_secrets(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [scrub_secrets(i) for i in obj]
    if isinstance(obj, tuple):
        return tuple(scrub_secrets(i) for i in obj)  # type: ignore[return-value]
    return obj
