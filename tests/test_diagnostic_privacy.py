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

    def test_headless_setup_does_not_print_authentication_link(self):
        import io
        from unittest.mock import patch
        import setup_cli
        output=io.StringIO()
        with patch.object(setup_cli,'SetupManager') as manager, \
             patch.object(setup_cli.sys,'argv',['setup_cli.py','--no-browser']), \
             patch.object(setup_cli.sys,'stdout',output):
            manager.return_value.ensure_configuration.return_value={'api_token':'synthetic-private-token'}
            setup_cli.main()
        self.assertNotIn('synthetic-private-token',output.getvalue())
        self.assertNotIn('#token=',output.getvalue())
        self.assertIn('withheld',output.getvalue())

    def test_metrics_closed_schema_prevents_private_labels_and_cardinality_growth(self):
        from operations.observability import Metrics
        metrics=Metrics()
        private='owner-private-text-with-no-secret-markers'
        for i in range(100):
            metrics.increment(private+str(i),path='/'+private+str(i),unexpected=private,status=private,error=private,method=private)
            metrics.set(private+str(i),private)
        metrics.increment('http_requests_total',method='POST',status='200',path='/owners/'+private)
        metrics.set('last_http_latency_ms',12.5)
        for surface in [json.dumps(metrics.snapshot()),metrics.prometheus()]:
            self.assertNotIn(private,surface)
            self.assertIn('http_requests_total',surface)
        self.assertEqual(len(metrics.counters),2)
        self.assertEqual(metrics.gauges,{'last_http_latency_ms':12.5})
