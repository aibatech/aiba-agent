import json
import tempfile
import unittest
from pathlib import Path
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry
from security.policy import SecurityPolicy
from security.audit import AuditLog
from approvals.manager import ApprovalManager
from reasoning.verification import verify_file_write, verify_file_delete
from reasoning.engine import ReasoningEngine
from agent.tasks import TaskStore
from memory.dream import DreamEngine


class PostconditionTests(unittest.TestCase):
    def test_claimed_success_without_write_is_failure_and_cannot_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=root/'permissions.json'
            cfg.write_text(json.dumps({'version':1,'tools':{'write_file':{'enabled':True,'requires_approval':False}}}))
            registry=ToolRegistry(AuditLog(root/'audit.jsonl'),ApprovalManager(False),SecurityPolicy(root,cfg))
            registry.register(Tool('write_file','test',lambda **_:ToolResult(True,{'claimed':'success'}),
                {'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}}},
                verifier=lambda args,res:verify_file_write(lambda p:root/p,args,res)))
            actions=iter([{'type':'tool_call','tool':'write_file','arguments':{'path':'missing','content':'secret'}}, {'type':'final','response':'Done!'}])
            class Provider:
                def complete(self,*args,**kwargs):return next(actions)
            class Retrieval:
                def retrieve(self,*args):return []
            tasks=TaskStore(root/'tasks.db');tid=tasks.create('write file',owner='alice')
            engine=ReasoningEngine(Provider(),registry,Retrieval(),tasks)
            answer,_=engine.run(tid,'write file')
            self.assertEqual(engine.execution_status,'partial');self.assertNotEqual(answer,'Done!')
            events=json.loads(tasks.get(tid)['events'])
            self.assertFalse(next(e['tool_result']['verified'] for e in events if 'tool_result' in e))

    def test_postconditions_check_content_and_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'out';path.write_text('actual',encoding='utf-8')
            resolve=lambda p:root/p
            self.assertTrue(verify_file_write(resolve,{'path':'out','content':'actual'},None))
            self.assertFalse(verify_file_write(resolve,{'path':'out','content':'different'},None))
            self.assertFalse(verify_file_delete(resolve,{'path':'out'},None))
            path.unlink();self.assertTrue(verify_file_delete(resolve,{'path':'out'},None))

    def test_reflection_does_not_indefinitely_copy_private_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dream=DreamEngine(root,None)
            path=dream.reflect('task','private request','private answer',['read_file'],owner='alice',status='partial')
            text=path.read_text();self.assertNotIn('private',text)
            self.assertEqual(json.loads(text)['owner'],'alice')
            self.assertEqual(list(root.glob('*.md')),[])
