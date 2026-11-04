import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from approvals.manager import ApprovalManager
from security.audit import AuditLog
from security.policy import SecurityPolicy
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry, _scrub_args_for_surface

class ExactApprovalTests(unittest.TestCase):
    def test_exact_grant_does_not_authorize_different_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            p=root/"permissions.json"
            p.write_text(json.dumps({"version":1,"tools":{"host_write_file":{"enabled":True,"requires_approval":True}}}))
            approvals=ApprovalManager(interactive=False)
            registry=ToolRegistry(AuditLog(root/"audit.jsonl"),approvals,SecurityPolicy(root,p,True))
            calls=[]
            registry.register(Tool("host_write_file","test",lambda path,content: (calls.append(path) or ToolResult(True,{"path":path})),{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}))
            args={"path":"/tmp/approved","content":"hello"}
            token=approvals.action_fingerprint("host_write_file",args)
            with approvals.request_scope([token]):
                self.assertTrue(registry.execute("host_write_file",args).ok)
                self.assertFalse(registry.execute("host_write_file",args).ok)
                self.assertFalse(registry.execute("host_write_file",{"path":"/tmp/other","content":"hello"}).ok)
                self.assertEqual(calls,["/tmp/approved"])
    def test_invalid_arguments_do_not_consume_one_time_grant(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            p=root/"permissions.json"
            p.write_text(json.dumps({"version":1,"tools":{"host_read_file":{"enabled":True,"requires_approval":True}}}))
            approvals=ApprovalManager(interactive=False)
            registry=ToolRegistry(AuditLog(root/"audit.jsonl"),approvals,SecurityPolicy(root,p,True))
            registry.register(Tool("host_read_file","test",lambda path: ToolResult(True,{"path":path}),{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}))
            args={"path":"/tmp/file","extra":"invalid"}
            token=approvals.action_fingerprint("host_read_file",args)
            with approvals.request_scope([token]):
                self.assertFalse(registry.execute("host_read_file",args).ok)
                self.assertTrue(approvals.approve_exact("host_read_file",args))

    def test_exact_grant_expires(self):
        approvals=ApprovalManager(interactive=False)
        token=approvals.action_fingerprint("host_read_file",{"path":"/tmp/file"})
        with patch("approvals.manager.time.monotonic", side_effect=[100.0, 102.0]):
            with approvals.request_scope([token], ttl_seconds=1.0):
                self.assertFalse(approvals.approve_exact("host_read_file",{"path":"/tmp/file"}))

    def test_host_content_never_appears_in_audit_arguments(self):
        args={"path":"/tmp/test","content":"customer-private-document"}
        shown=_scrub_args_for_surface("host_write_file",args)
        self.assertNotIn("customer-private-document",str(shown))
        self.assertEqual(shown["path"],"/tmp/test")

    def test_auto_approve_cannot_bypass_sensitive_approval(self):
        approvals=ApprovalManager(interactive=False,auto_approve=True)
        with approvals.request_scope():
            self.assertFalse(approvals.approve_exact("secret_copy_env",{"key":"TOKEN"}))

    def test_legacy_tool_name_does_not_grant_sensitive_operation(self):
        approvals=ApprovalManager(interactive=False)
        with approvals.request_scope(["secret_copy_env"]):
            self.assertFalse(approvals.approve_exact("secret_copy_env",{"key":"TOKEN"}))
            self.assertEqual(len(approvals.pending_requests()),1)
if __name__=="__main__":
    unittest.main()
