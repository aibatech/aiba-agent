from __future__ import annotations
"""Discovery-aware, atomic, idempotent provider connection for AIBA onboarding.

TASK 1 implementation: before choosing a default model, consult the provider's own
model-discovery endpoint and register a model that is currently *available*, rather
than blindly relying on a hardcoded (possibly deprecated) model id. The flow is
atomic and idempotent: existing providers/models are reused, never duplicated.

This module never logs or prints provider API keys.
"""
from typing import Iterable

from models.management import ProviderStore
from models.intelligent_router import IntelligentRouter
from models.provider import ProviderError


# Safe fallback / preference order when discovery is unavailable or yields nothing.
# Keep the list generic; per-kind fallbacks can be extended below.
FALLBACK_MODELS_PER_KIND = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "google": "gemini-2.0-flash",
    "xai": "grok-2-latest",
    "openrouter": "openai/gpt-4.1-mini",
    "groq": "llama-3.3-70b-versatile",
    "deepseek": "deepseek-chat",
    "azure_openai": "gpt-4o-mini",
    "ollama": "llama3.2:3b",
    "custom": "qwen2.5:latest",
}

# Model families we prefer when picking an "available" model after discovery.
_PREFERRED_FAMILY_HINTS = {
    "google": ("gemini-3.6", "gemini-3.5", "gemini-3", "gemini-2.5", "gemini-2.0"),
    "openai": ("gpt-5", "gpt-4.1", "gpt-4o", "gpt-4"),
    "anthropic": ("claude-3.7", "claude-3.5", "claude-sonnet", "claude-haiku"),
}


def _pick_available_model(kind: str, discovered: Iterable[dict]) -> str | None:
    """Select a currently-available model id from discovery output.

    Prefers orderings that favour stable, well-known families so we do not pick a
    throwaway internal model id. Returns the first sensible match or None.
    """
    ids: list[str] = []
    for m in discovered:
        mid = m.get("id")
        if isinstance(mid, str) and mid:
            ids.append(mid)
    if not ids:
        return None
    hints = _PREFERRED_FAMILY_HINTS.get(kind)
    if hints:
        for hint in hints:
            for mid in ids:
                if hint in mid and not _looks_internal(mid):
                    return mid
    # fall back to a stable, non-internal id (last one is usually newest/fullest)
    stable = [mid for mid in ids if not _looks_internal(mid)]
    return (stable[-1] if stable else ids[-1])


def _looks_internal(model_id: str) -> bool:
    lowered = model_id.lower()
    return any(tok in lowered for tok in ("-dev", "-preview-", "beta", "experimental", "-internal"))


def _redact(text: str, secret: str | None) -> str:
    """Remove any occurrence of an API key/secret from a string (error text logging safety)."""
    if secret and secret in text:
        text = text.replace(secret, "[REDACTED]")
    return text


def connect_provider_atomically(
    store: ProviderStore,
    router: IntelligentRouter | None,
    kind: str,
    api_key: str | None = None,
    base_url: str | None = None,
    preferred_model: str | None = None,
    capabilities: list[str] | None = None,
    fallback_model: str | None = None,
    display_name: str | None = None,
) -> dict:
    """Create/reuse a provider and register a currently-available model, atomically.

    Discovery-aware: calls the provider's live model-discovery endpoint when a router
    is available and the provider has a key/base_url. If discovery fails or the
    preferred/hardcoded model is not available, falls back to a safe default.
    Never logs the api_key. Returns a non-secret result dict.
    """
    caps = capabilities or ["text", "tools", "code"]
    provider_id = store.upsert_provider(
        name=display_name or "",
        kind=kind,
        base_url=base_url,
        api_key=api_key,
        enabled=True,
    )

    model_id = None
    discovered = []
    discovery_error = None
    if router is not None:
        try:
            if store.get_key(provider_id) or api_key:
                discovered = router.discover_models(provider_id)
        except ProviderError as exc:
            discovery_error = _redact(str(exc), api_key)
        except Exception as exc:  # noqa: BLE001 - discovery must never break onboarding
            discovery_error = _redact(f"{type(exc).__name__}: {exc}", api_key)

    if discovered:
        selected = _pick_available_model(kind, discovered)
        if preferred_model and any(m.get("id") == preferred_model for m in discovered):
            selected = preferred_model
        model_id = selected or fallback_model or FALLBACK_MODELS_PER_KIND.get(kind)
    else:
        # Discovery unavailable or empty -> safe fallback.
        model_id = preferred_model or fallback_model or FALLBACK_MODELS_PER_KIND.get(kind)
        if model_id is None:
            model_id = "gpt-4o-mini"

    registered = store.upsert_model(
        provider_id,
        model_id,
        display_name=f"{kind} ({model_id})"
        if not display_name
        else f"{display_name} ({model_id})",
        capabilities=caps,
        enabled=True,
    )

    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "model_row_id": registered,
        "discovered": bool(discovered),
        "discovery_model_count": len(discovered),
        "discovery_error": discovery_error,
        "used_fallback": not discovered,
        "has_key": bool(api_key is not None),
    }
