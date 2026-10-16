import json
import tempfile
import unittest
import uuid
from pathlib import Path
from operations.observability import CrashReporter

class DiagnosticPrivacyTests(unittest.TestCase):
    def test_exception_chain_request_path_and_context_do_not_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret='private-value-without-a-recognizable-marker'
            reporter=CrashReporter(Path(tmp));task_id=str(uuid.uuid4())
            try:
                try:raise ValueError(secret)
                except ValueError as cause:raise RuntimeError(secret) from cause
            except RuntimeError as exc:
                crash_id=reporter.capture(exc,{'task_id':task_id,'method':'POST','path':'/'+secret,'nested':{'content':secret}})
            text=reporter.path.read_text()
            self.assertNotIn(secret,text)
            record=json.loads(text)
            self.assertEqual(record['id'],crash_id)
            self.assertEqual(record['type'],'RuntimeError')
            self.assertEqual(record['context'],{'task_id':task_id,'method':'POST'})
            self.assertTrue(record['frames'])
            self.assertNotIn('traceback',record)

    def test_audit_omits_nested_freeform_payloads_and_unknown_objects(self):
        from security.audit import AuditLog
        with tempfile.TemporaryDirectory() as tmp:
            secret='arbitrary-private-data'
            class PrivateObject:
                def __str__(self):return secret
            audit=AuditLog(Path(tmp)/'audit.jsonl')
            audit.record('tool_event',tool='read_file',arguments={'path':secret,'entries':[{'token':secret}]},
                         output=secret,error=secret,object=PrivateObject())
            text=audit.path.read_text()
            self.assertNotIn(secret,text)
            self.assertEqual(json.loads(text)['tool'],'read_file')
