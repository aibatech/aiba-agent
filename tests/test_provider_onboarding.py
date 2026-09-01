from __future__ import annotations
"""Tests for discovery-aware atomic/idempotent provider onboarding (TASK 1).

Covers:
  - Successful model discovery -> registers an available model
  - Discovery failure           -> safe fallback model
  - Existing-provider reuse     -> no duplicate provider row
  - Duplicate prevention        -> repeated calls stay single provider + model
  - Invalid credentials         -> raises / no key leakage
  - Deprecated model replacement -> a preferred-but-deprecated model yields an available one when discovered
"""
import json
import tempfile
import unittest
from pathlib import Path

from models.management import ProviderStore
from onboarding.providers import connect_provider_atomically


class FakeCredentials:
    def __init__(self):pass
    def encrypt(self, value):return ("ENC:" + value)
    def decrypt(self, value):return value[4:] if value and value.startswith("ENC:") else value


class FakeStore(ProviderStore):
    """ProviderStore with a deterministic cipher so tests can inspect stored keys."""
    def __init__(self, path: Path):
        # monkeypatch instance cipher before init uses it (init doesn't encrypt anything)
        super().__init__(path, cipher=FakeCredentials())


class FakeRouter:
    """Simulates an IntelligentRouter. discovery_result controls discovery behavior."""
    def __init__(self, discovery=None, error=None):
        self.discovery_result = discovery  # list of {'id':...} or None
        self.error = error
        self.picked = None

    def discover_models(self, provider_id):
        if self.error:
            raise self.error
        return self.discovery_result if self.discovery_result is not None else []


def make_store():
    d = tempfile.TemporaryDirectory()
    store = FakeStore(Path(d.name) / "providers.db")
    return d, store


class ProviderOnboardingTests(unittest.TestCase):
    def test_successful_discovery_registers_available_model(self):
        d, store = make_store()
        try:
            router = FakeRouter(discovery=[{"id": "gemini-3.6-flash"}, {"id": "gemini-2.0-flash"}])
            res = connect_provider_atomically(store, router, "google", api_key="k")
            self.assertTrue(res["discovered"])
            self.assertEqual(res["model_id"], "gemini-3.6-flash")  # preferred family >= 2.0
            self.assertEqual(res["used_fallback"], False)
            models = store.list_models()
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["model_id"], "gemini-3.6-flash")
        finally:
            d.cleanup()

    def test_discovery_failure_uses_fallback(self):
        d, store = make_store()
        try:
            router = FakeRouter(error=RuntimeError("network down"))
            res = connect_provider_atomically(store, router, "google", api_key="k")
            self.assertFalse(res["discovered"])
            self.assertTrue(res["used_fallback"])
            self.assertTrue(res["model_id"])  # fallback selected
            self.assertTrue(res["discovery_error"])
            # registration still happened
            self.assertEqual(len(store.list_models()), 1)
        finally:
            d.cleanup()

    def test_existing_provider_reused_no_duplicate(self):
        d, store = make_store()
        try:
            router = FakeRouter(discovery=[{"id": "gemini-3.6-flash"}])
            first = connect_provider_atomically(store, router, "google", api_key="k")
            second = connect_provider_atomically(store, router, "google", api_key="k2")
            self.assertEqual(first["provider_id"], second["provider_id"])
            providers = [p for p in store.list_providers() if p["kind"] == "google"]
            self.assertEqual(len(providers), 1)
            self.assertEqual(len(store.list_models()), 1)
        finally:
            d.cleanup()

    def test_duplicate_prevention_counts(self):
        d, store = make_store()
        try:
            router = FakeRouter(discovery=[{"id": "oai-m1"}, {"id": "oai-m2"}])
            for _ in range(4):
                connect_provider_atomically(store, router, "openai", api_key="k", preferred_model="oai-m2")
            providers = [p for p in store.list_providers() if p["kind"] == "openai"]
            self.assertEqual(len(providers), 1)
            self.assertEqual(len(store.list_models()), 1)
            self.assertEqual(store.list_models()[0]["model_id"], "oai-m2")
        finally:
            d.cleanup()

    def test_invalid_credentials_are_redacted_and_never_logged(self):
        d, store = make_store()
        try:
            secret_key = "sekrit-abcdef-999888"
            # discovery fails with an error that echoes the (invalid) key
            err = RuntimeError(f"Unauthorized: bad key {secret_key} rejected")
            router = FakeRouter(error=err)
            import io
            from contextlib import redirect_stderr, redirect_stdout
            buf = io.StringIO()
            with redirect_stderr(buf), redirect_stdout(buf):
                res = connect_provider_atomically(store, router, "openai", api_key=secret_key, fallback_model="gpt-4.1-mini")
            self.assertTrue(res["used_fallback"])
            # the error surfaced to us must not contain the key
            self.assertNotIn(secret_key, res["discovery_error"])
            self.assertIn("[REDACTED]", res["discovery_error"])
            self.assertNotIn(secret_key, buf.getvalue())
        finally:
            d.cleanup()

    def test_deprecated_model_replaced_by_available(self):
        d, store = make_store()
        try:
            # Discovery lists only the NEW model; preferred is the old/deprecated one.
            router = FakeRouter(discovery=[{"id": "gemini-3.6-flash"}])
            res = connect_provider_atomically(store, router, "google", api_key="k", preferred_model="gemini-2.0-flash")
            # because gemini-2.0-flash is NOT present in discovery, use the available one
            self.assertEqual(res["model_id"], "gemini-3.6-flash")
            self.assertEqual(store.list_models()[0]["model_id"], "gemini-3.6-flash")
        finally:
            d.cleanup()


if __name__ == "__main__":
    unittest.main()
