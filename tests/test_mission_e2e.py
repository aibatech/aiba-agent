"""Deterministic full-runtime acceptance. No live provider calls or customer data."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.enhanced_loop import AgentLoop
from test_phase9_loop import make_settings


class MissionEndToEndTests(unittest.TestCase):
    def test_authorized_write_read_restart_memory_and_provider_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=make_settings(root)
            loop=AgentLoop(settings=settings,interactive=False,start_worker=False)
            args={'path':'goal.txt','content':'Launch Atlas'}
            actions=iter([
                {'type':'tool_call','tool':'write_file','arguments':args},
                {'type':'tool_call','tool':'read_file','arguments':{'path':'goal.txt'}},
                {'type':'final','response':'Saved and read back Launch Atlas.'}])
            try:
                with patch.object(loop.engine.provider,'complete',side_effect=lambda *a,**k:next(actions)):
                    with loop.approvals.request_scope([loop.approvals.action_fingerprint('write_file',args)]):
                        result=loop.handle_result('My goal is to launch Atlas.',user_id='alice',conversation_id='project')
                self.assertEqual(result['status'],'complete')
                self.assertEqual((settings.workspace_dir/'goal.txt').read_text(),'Launch Atlas')
                self.assertTrue(loop.vault.search('Atlas',as_user='alice'))
                self.assertEqual(loop.vault.search('Atlas',as_user='bob'),[])
            finally:loop.close()
            restarted=AgentLoop(settings=settings,interactive=False,start_worker=False)
            try:
                captured=[]
                def answer(messages,*args,**kwargs):
                    captured.extend(messages)
                    return {'type':'final','response':'Your goal is to launch Atlas.'}
                with patch.object(restarted.engine.provider,'complete',side_effect=answer):
                    result=restarted.handle_result('What is my Atlas goal?',user_id='alice',conversation_id='project')
                self.assertEqual(result['status'],'complete')
                self.assertIn('My goal is to launch Atlas',str(captured))
                with patch.object(restarted.engine.provider,'complete',side_effect=ConnectionError('provider unavailable')):
                    result=restarted.handle_result('Continue',user_id='alice')
                    self.assertEqual(result['status'],'failed')
                    self.assertEqual(restarted.tasks.get(result['task_id'])['status'],'failed')
                    with self.assertRaises(RuntimeError):
                        restarted._run_background({'prompt':'Continue','user_id':'alice'})
            finally:restarted.close()

    def test_failed_tool_cannot_be_overridden_by_model_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            actions=iter([{'type':'tool_call','tool':'write_file','arguments':{'path':'denied.txt','content':'test'}},
                          {'type':'final','response':'Everything was saved successfully.'}])
            try:
                with patch.object(loop.engine.provider,'complete',side_effect=lambda *a,**k:next(actions)):
                    result=loop.handle_result('Save the file',propose_skill=False,user_id='alice')
                self.assertEqual(result['status'],'partial')
                self.assertNotIn('saved successfully',result['result'])
                self.assertFalse((loop.settings.workspace_dir/'denied.txt').exists())
            finally:loop.close()
