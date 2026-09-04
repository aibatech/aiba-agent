"""Regression: the registry audit/approval surface must not log secret content.

Defense-in-depth for the "typed secrets are never logged" invariant. The inner
desktop/browser controllers already report typed content only by length; the
registry records tool_start/tool_denied args and shows them in the approval
prompt. This test pins that the registry scrubs secrets at that outer layer too,
so the guarantee holds end-to-end (audit concern #5).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from security.audit import AuditLog
from approvals.manager import ApprovalManager
from security.policy import SecurityPolicy
from tools.registry import ToolRegistry
from tools.base import Tool, ToolResult


def _str_tool(name: str, arg: str = "text") -> Tool:
    """A tool taking a single string arg and echoing a success ToolResult."""
    def handler(**kwargs):
        return ToolResult(True, kwargs.get(arg))
    return Tool(
        name, f"placeholder {name}",
        handler,
        {"type": "object", "properties": {arg: {"type": "string"}},
         "required": [arg], "additionalProperties": False})


class RegistrySecretRedactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _make(self, path: str, tools: dict | None = None, approvals_enabled: bool = False):
        ws = self.root / (path + "_ws")
        ws.mkdir(parents=True, exist_ok=True)
        cfg = self.root / (path + ".json")
        cfg.write_text(json.dumps({"version": 1, "tools": tools or {},
                                   "blocked_command_fragments": []}))
        audit = AuditLog(self.root / (path + "_audit.jsonl"))
        reg = ToolRegistry(audit, ApprovalManager(approvals_enabled),
                           SecurityPolicy(ws, cfg))
        return reg, audit

    def _audit_text(self, audit: AuditLog) -> str:
        return audit.path.read_text(encoding="utf-8", errors="replace")

    def test_secret_named_key_redacted_from_tool_start(self):
        reg, audit = self._make("k", tools={
            "store_token": {"enabled": True, "requires_approval": False}})
        secret = "sk-liv...3456"
        reg.register(Tool("store_token", "store a token",
                          lambda token: ToolResult(True),
                          {"type": "object", "properties": {"token": {"type": "string"}},
                           "required": ["token"], "additionalProperties": False}))
        reg.execute("store_token", {"token": secret})
        text = self._audit_text(audit)
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED", text)

    def test_secretish_typed_text_redacted_for_typed_text_tools(self):
        tools = {n: {"enabled": True, "requires_approval": False}
                 for n in ("browser_type", "desktop_type", "desktop_clipboard_write")}
        reg, audit = self._make("tt", tools=tools)
        secret = "my passwd is hunter2super"
        for tool_name in tools:
            reg.register(_str_tool(tool_name, "text"))
            reg.execute(tool_name, {"text": secret})
        text = self._audit_text(audit)
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED", text)

    def test_benign_typed_text_preserved_in_audit(self):
        reg, audit = self._make("b", tools={
            "desktop_type": {"enabled": True, "requires_approval": False}})
        benign = "type the reply now and continue working"
        reg.register(_str_tool("desktop_type", "text"))
        reg.execute("desktop_type", {"text": benign})
        self.assertIn(benign, self._audit_text(audit))

    def test_non_secret_looking_unrelated_args_not_redacted(self):
        reg, audit = self._make("s", tools={
            "run_shell": {"enabled": True, "requires_approval": False}})
        reg.register(_str_tool("run_shell", "cmd"))
        body = "echo secret_value_noop"
        reg.execute("run_shell", {"cmd": body})
        self.assertIn(body, self._audit_text(audit))

    def test_secret_redacted_in_approval_prompt_preview(self):
        ws = self.root / "app2_ws"; ws.mkdir(parents=True, exist_ok=True)
        cfg = self.root / "app2.json"
        cfg.write_text(json.dumps({"version": 1,
                                   "tools": {"p": {"enabled": True, "requires_approval": True}},
                                   "blocked_command_fragments": []}))
        audit = AuditLog(self.root / "app2_audit.jsonl")
        seen = []

        class _CaptureApprover:
            def approve(self, name, reason):
                seen.append(reason)
                return True

        reg = ToolRegistry(audit, _CaptureApprover(), SecurityPolicy(ws, cfg))
        reg.register(_str_tool("p", "token"))
        secret = "Bearer hunter2-credential-999"
        reg.execute("p", {"token": secret})
        self.assertTrue(seen)
        self.assertNotIn(secret, seen[0])
        self.assertIn("[REDACTED", seen[0])


if __name__ == "__main__":
    unittest.main()
