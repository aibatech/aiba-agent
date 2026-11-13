import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from agent.tasks import TaskStore
from approvals.manager import ApprovalManager
from reasoning.engine import ReasoningEngine
from tools.base import ToolResult

class ExecutionEvidenceTests(unittest.TestCase):
    def engine(self, tasks, actions, result, calls):
        actions=iter(actions)
        class Provider:
            def complete(self,*a,**k):return next(actions)
        class Registry:
            def schemas(self,*a):return []
            def execute(self,name,args,blocked=None):
                calls.append(name)
                if isinstance(result,Exception):raise result
                return result
        class Retrieval:
            def retrieve(self,*a):return []
        return ReasoningEngine(Provider(),Registry(),Retrieval(),tasks)

    def test_unverified_side_effect_never_completes_or_replays(self):
        for planned in (False,True):
            with self.subTest(planned=planned),tempfile.TemporaryDirectory() as tmp:
                tasks=TaskStore(Path(tmp)/'tasks.db');tid=tasks.create('send',owner='alice');calls=[]
                call={'type':'tool_call','tool':'send_external','arguments':{'value':1}}
                actions=[]
                if planned:actions.append({'type':'plan','steps':['send']});call['plan_step']=0
                actions += [call,{'type':'final','response':'Sent successfully'}]
                engine=self.engine(tasks,actions,ToolResult(True,dispatched=True),calls)
                self.assertNotEqual(engine.run(tid,'send')[0],'Sent successfully')
                self.assertEqual(engine.execution_status,'partial');tasks.finish(tid,'uncertain','partial')
                restarted=TaskStore(tasks.path)
                retry=self.engine(restarted,[call],ToolResult(True,verified=True),calls)
                with self.assertRaises(ValueError):retry.run(tid,'retry')
                self.assertEqual(calls,['send_external'])
                self.assertEqual(restarted.actions(tid)[0]['status'],'unknown')

    def test_timeout_persists_fence_then_exact_owner_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks=TaskStore(Path(tmp)/'tasks.db');tid=tasks.create('send',owner='alice');calls=[]
            args={'destination':'test'};fp=ApprovalManager.action_fingerprint('send_external',args)
            call={'type':'tool_call','tool':'send_external','arguments':args}
            engine=self.engine(tasks,[call],TimeoutError('boundary outcome unknown'),calls)
            with self.assertRaises(TimeoutError):engine.run(tid,'send')
            tasks.finish(tid,'uncertain','failed');tasks=TaskStore(tasks.path)
            self.assertEqual(tasks.actions(tid)[0]['status'],'running')
            with self.assertRaises(ValueError):tasks.reconcile_action(tid,'bob',fp,'retry')
            with self.assertRaises(ValueError):tasks.reconcile_action(tid,'alice','0'*64,'retry')
            tasks.reconcile_action(tid,'alice',fp,'verified')
            final=self.engine(tasks,[{'type':'final','response':'Owner confirmed receipt'}],ToolResult(True),calls)
            self.assertEqual(final.run(tid,'resume')[0],'Owner confirmed receipt')
            self.assertEqual(calls,['send_external'])
            with self.assertRaises(ValueError):tasks.reconcile_action(tid,'alice',fp,'retry')

    def test_concurrent_claim_and_erasure_are_owner_scoped(self):
        from privacy.erasure import OwnerErasure
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=TaskStore(root/'tasks.db');tid=tasks.create('work',owner='alice')
            def claim(_):
                try:tasks.action_start(tid,'external','a'*64);return True
                except ValueError:return False
            with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(sum(pool.map(claim,range(8))),1)
            other=tasks.create('other',owner='bob');tasks.action_start(other,'external','b'*64)
            erasure=OwnerErasure(root);plan=erasure.preview('alice')
            tasks.action_result(tid,'a'*64,ToolResult(True,verified=True),True)
            with self.assertRaises(ValueError):erasure.erase('alice',plan['confirmation'])
            erasure.erase('alice',erasure.preview('alice')['confirmation'])
            self.assertEqual(tasks.actions(tid),[]);self.assertEqual(len(tasks.actions(other)),1)

    def test_known_read_only_observation_can_complete_without_mutation_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks=TaskStore(Path(tmp)/'tasks.db');tid=tasks.create('read');calls=[]
            engine=self.engine(tasks,[{'type':'tool_call','tool':'read_file','arguments':{'path':'a'}},{'type':'final','response':'Read'}],ToolResult(True,'text'),calls)
            self.assertEqual(engine.run(tid,'read')[0],'Read');self.assertEqual(tasks.actions(tid),[])

    def test_actual_runtime_denied_action_can_retry_but_approval_is_still_required(self):
        from agent.enhanced_loop import AgentLoop
        from test_phase9_loop import make_settings
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                args={'path':'test.txt','content':'expected'}
                action={'type':'tool_call','tool':'write_file','arguments':args}
                with patch.object(loop.engine.provider,'complete',side_effect=[action,{'type':'final','response':'Done'}]):
                    first=loop.handle_result('write',user_id='alice')
                self.assertEqual(first['status'],'partial')
                self.assertEqual(loop.tasks.actions(first['task_id'])[0]['status'],'retryable')
                fp=ApprovalManager.action_fingerprint('write_file',args)
                with loop.approvals.request_scope([fp]),patch.object(loop.engine.provider,'complete',side_effect=[action,{'type':'final','response':'Verified'}]):
                    resumed=loop.resume_task(first['task_id'],'alice')
                self.assertEqual(resumed['status'],'complete')
                self.assertEqual(loop.sandbox.read_file('test.txt').output,'expected')
            finally:loop.close()

    def test_actual_process_death_after_effect_does_not_replay(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=TaskStore(root/'tasks.db');tid=tasks.create('external effect',owner='alice')
            script='''
import os,sys
from pathlib import Path
from agent.tasks import TaskStore
from reasoning.engine import ReasoningEngine
root=Path(sys.argv[1]);tid=sys.argv[2]
class Provider:
    def complete(self,*a,**k):return {'type':'tool_call','tool':'external_write','arguments':{}}
class Registry:
    def schemas(self,*a):return []
    def execute(self,*a,**k):
        with (root/'effect.txt').open('a') as f:f.write('effect\\n');f.flush();os.fsync(f.fileno())
        os._exit(73)
class Retrieval:
    def retrieve(self,*a):return []
ReasoningEngine(Provider(),Registry(),Retrieval(),TaskStore(root/'tasks.db')).run(tid,'execute')
'''
            child=subprocess.run([sys.executable,'-c',script,str(root),tid],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=30)
            self.assertEqual(child.returncode,73,child.stderr.decode())
            restarted=TaskStore(tasks.path);restarted.recover_interrupted();calls=[]
            retry=self.engine(restarted,[{'type':'tool_call','tool':'external_write','arguments':{}}],ToolResult(True,verified=True),calls)
            with self.assertRaises(ValueError):retry.run(tid,'resume')
            self.assertEqual(calls,[]);self.assertEqual((root/'effect.txt').read_text(),'effect\n')
            fp=ApprovalManager.action_fingerprint('external_write',{})
            restarted.reconcile_action(tid,'alice',fp,'verified')
            self.assertEqual(restarted.actions(tid)[0]['status'],'verified')

    def test_cancellation_during_handler_cannot_complete_worker(self):
        from threading import Event,Thread
        from runtime.queue import JobQueue
        from runtime.worker import Worker
        from runtime.control import checkpoint
        with tempfile.TemporaryDirectory() as tmp:
            queue=JobQueue(Path(tmp)/'jobs.db');started=Event();release=Event();later=[]
            def handler(payload):
                started.set()
                if not release.wait(5):raise TimeoutError('test did not release boundary')
                checkpoint();later.append('forbidden subsequent effect')
                return {'status':'complete'}
            job=queue.enqueue('external',{});worker=Worker(queue,{'external':handler})
            thread=Thread(target=worker.run_once);thread.start()
            try:
                self.assertTrue(started.wait(5));queue.cancel(job)
            finally:release.set();thread.join(5)
            self.assertFalse(thread.is_alive());self.assertEqual(later,[])
            self.assertEqual(queue.get(job)['status'],'cancelled')

    def test_command_file_postconditions_use_actual_bytes_not_exit_status(self):
        from agent.enhanced_loop import AgentLoop
        from test_phase9_loop import make_settings
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                args={'code':"from pathlib import Path; Path('made.txt').write_bytes(b'exact\\n')",'expected_files':[{'path':'made.txt','content':'exact\n'}]}
                with loop.approvals.request_scope([ApprovalManager.action_fingerprint('run_python',args)]):
                    result=loop.registry.execute('run_python',args)
                self.assertTrue(result.ok);self.assertTrue(result.verified)
                args={'code':'pass','expected_files':[{'path':'made.txt','content':'wrong'}]}
                with loop.approvals.request_scope([ApprovalManager.action_fingerprint('run_python',args)]):
                    result=loop.registry.execute('run_python',args)
                self.assertFalse(result.ok);self.assertFalse(result.verified)
                args={'code':'pass'}
                with loop.approvals.request_scope([ApprovalManager.action_fingerprint('run_python',args)]):
                    result=loop.registry.execute('run_python',args)
                self.assertTrue(result.ok);self.assertIsNone(result.verified)
            finally:loop.close()

    def test_patch_noop_and_archive_name_traversal_are_rejected(self):
        from tools.sandbox import Sandbox
        from test_sandbox import _Policy
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sandbox=Sandbox(root,10,_Policy(root));(root/'file.txt').write_text('old')
            with patch.object(sandbox,'_write_bytes',return_value=None):
                result=sandbox.patch_file('file.txt','old','new')
            self.assertFalse(result.ok);self.assertFalse(result.verified)
            self.assertTrue(sandbox.patch_file('file.txt','old','new').verified)
            for name in ('../escaped','/tmp/escaped','..\\escaped','C:escaped'):
                with patch('tools.sandbox.shutil.make_archive') as archive:
                    self.assertFalse(sandbox.archive('file.txt',name=name).ok)
                    archive.assert_not_called()
