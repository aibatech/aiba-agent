from __future__ import annotations

import unittest

from approvals.manager import ApprovalManager
from api.product_bridge import _principal, create_product_app


class ApprovalManagerProductTests(unittest.TestCase):
    def test_request_scope_records_pending_and_does_not_leak(self):
        approvals = ApprovalManager(interactive=False, auto_approve=False)
        with approvals.request_scope():
            self.assertFalse(approvals.approve("browser_click", "{'text': 'Continue'}"))
            pending = approvals.pending_requests()
            self.assertEqual(pending[0]["tool"], "browser_click")
        self.assertEqual(approvals.pending_requests(), [])

    def test_request_scope_grants_only_named_tool(self):
        approvals = ApprovalManager(interactive=False, auto_approve=False)
        with approvals.request_scope(["browser_click"]):
            self.assertTrue(approvals.approve("browser_click"))
            self.assertFalse(approvals.approve("browser_submit"))
            self.assertEqual(approvals.pending_requests()[0]["tool"], "browser_submit")


class ProductIdentityTests(unittest.TestCase):
    def test_principal_is_product_namespaced(self):
        self.assertEqual(_principal("user-123"), "product:user-123")

    def test_principal_rejects_blank_or_unsafe_value(self):
        for value in (None, "", "bad user", "x" * 201):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _principal(value)


class _FakeAgent:
    def __init__(self):
        self.approvals = ApprovalManager(interactive=False, auto_approve=False)
        self.calls = []

    def capability_report(self):
        return {"web_search": {"ready": True}}

    def handle(self, text, **kwargs):
        self.calls.append((text, kwargs))
        if "click" in text.lower():
            self.approvals.approve("browser_click", "{'text': 'Continue'}")
        return "agent-result"


class ProductBridgeApiTests(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI test dependencies are not installed")
        self.agent = _FakeAgent()
        self.client = TestClient(create_product_app(self.agent, bridge_token="test-token"))
        self.headers = {
            "Authorization": "Bearer test-token",
            "X-AIBA-User-ID": "abc123",
        }

    def test_text_and_voice_use_same_execution_path(self):
        for mode in ("text", "voice"):
            response = self.client.post(
                "/v1/product/execute",
                headers=self.headers,
                json={"instruction": "Research this", "input_mode": mode},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["input_mode"], mode)
            self.assertEqual(payload["user_scope"], "product:abc123")
            self.assertEqual(payload["status"], "complete")
        for _, kwargs in self.agent.calls:
            self.assertEqual(kwargs["user_id"], "product:abc123")
            self.assertFalse(kwargs["onboard"])

    def test_mutation_surfaces_approval_then_accepts_narrow_retry_grant(self):
        first = self.client.post(
            "/v1/product/execute",
            headers=self.headers,
            json={"instruction": "Click Continue", "input_mode": "text"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "approval_required")
        self.assertEqual(first.json()["approval_required"][0]["tool"], "browser_click")

        second = self.client.post(
            "/v1/product/execute",
            headers=self.headers,
            json={
                "instruction": "Click Continue",
                "input_mode": "text",
                "approved_tools": ["browser_click"],
            },
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "complete")
        self.assertEqual(second.json()["approval_required"], [])

    def test_bridge_requires_auth_and_user_identity(self):
        response = self.client.post(
            "/v1/product/execute",
            json={"instruction": "Research this"},
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/v1/product/execute",
            headers={"Authorization": "Bearer test-token"},
            json={"instruction": "Research this"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
