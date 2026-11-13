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
            self.assertEqual(json.loads(text)['tool_sha256'],__import__('hashlib').sha256(b'read_file').hexdigest())

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

    def test_audit_closed_schema_rejects_unknown_names_values_and_envelope_override(self):
        from security.audit import AuditLog
        from runtime.events import EventBus
        corpus=['private customer note', '秘密 confidential', 'private\nmultiline']
        with tempfile.TemporaryDirectory() as tmp:
            audit=AuditLog(Path(tmp)/'audit.jsonl');bus=EventBus()
            bus.subscribe('*',lambda envelope:audit.record('event',**envelope))
            for private in corpus:
                audit.record(private,tool=private,server_id=private,notes=private,
                             **{private:private,'timestamp':private,'ok':private,'steps':private})
                bus.publish('reasoning.plan',event={'summary':private},task_id=private)
            rows=[json.loads(line) for line in audit.path.read_text().splitlines()]
            self.assertEqual(len(rows),len(corpus)*2)
            self.assertEqual([r['event'] for r in rows],['other','event']*len(corpus))
            for private in corpus:self.assertNotIn(private,audit.path.read_text())
            audit.record('tool_end',ok=False,verified=False,steps=3)
            row=json.loads(audit.path.read_text().splitlines()[-1])
            self.assertFalse(row['ok']);self.assertFalse(row['verified']);self.assertEqual(row['steps'],3)

    def test_reasoning_extensions_cannot_override_safe_fields(self):
        from reasoning.protocol import VisibleReasoning
        events=[];visible=VisibleReasoning(lambda *a,**kw:events.append(kw),'trusted-task-id')
        private='owner-private-unmarked-text'
        visible.plan(private,steps=private,kind=private,unknown={private:private})
        visible.tool('read_file',{},tool_index=private,tool=private,unknown=private)
        visible.result('read_file',False,private,detail=private,unknown=private)
        visible.final(private,tool_count=private,kind=private,unknown=private)
        visible.error(private,kind=private,unknown=private)
        self.assertNotIn(private,json.dumps(events))
        self.assertEqual({e['event']['kind'] for e in events},{'plan','tool','result','final','error'})
        self.assertEqual(events[4]['event']['ok'],False)

    def test_crash_dynamic_source_names_and_exception_types_do_not_leak(self):
        private='private_dynamic_identifier_819'
        with tempfile.TemporaryDirectory() as tmp:
            reporter=CrashReporter(Path(tmp));namespace={'Failure':type(private,(Exception,),{})}
            code=compile('def '+private+'():\n    raise Failure("private message")\n'+private+'()','/private/'+private+'.py','exec')
            try:exec(code,namespace)
            except Exception as exc:reporter.capture(exc)
            record=json.loads(reporter.path.read_text())
            self.assertNotIn(private,reporter.path.read_text())
            self.assertEqual(record['type'],'OtherError')
            self.assertTrue(record['frames'])
            self.assertTrue(all(len(frame['file_sha256'])==64 for frame in record['frames']))
