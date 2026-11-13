import json
import tempfile
import unittest
from pathlib import Path
from agent.tasks import TaskStore
from skills.improver import SkillImprover
from skills.manager import SkillManager
from privacy.erasure import OwnerErasure
from sqlite_utils import connect


class LearningFeedbackTests(unittest.TestCase):
    def test_versioned_intent_corpus_through_actual_runtime(self):
        from unittest.mock import patch
        from agent.enhanced_loop import AgentLoop
        from test_phase9_loop import make_settings
        corpus=json.loads((Path(__file__).resolve().parents[1]/'benchmarks/learning/v1.json').read_text())
        metrics={'verified_outcomes':0,'exact_cohorts':0,'cross_intent_matches':0,'automatic_executable_proposals':0}
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                for workflow in corpus['workflows']:
                    ids=[]
                    for value in workflow['values']:
                        args={'content':value}
                        if workflow['tool']=='write_file':args['path']=workflow['path']
                        actions=iter([{'type':'tool_call','tool':workflow['tool'],'arguments':args},{'type':'final','response':'Saved'}])
                        fingerprint=loop.approvals.action_fingerprint(workflow['tool'],args)
                        with loop.approvals.request_scope([fingerprint]),patch.object(loop.engine.provider,'complete',side_effect=lambda *a,**k:next(actions)):
                            outcome=loop.handle_result('Save '+value,user_id='alice')
                        self.assertEqual(outcome['status'],'complete');ids.append(outcome['task_id'])
                        if workflow['tool']=='write_file':self.assertEqual(loop.sandbox.read_file(workflow['path']).output,value)
                        else:self.assertTrue(any(row['content']==value for row in loop.vault.list(as_user='alice')))
                        loop.tasks.feedback(ids[-1],'alice',workflow['id'],True)
                        metrics['verified_outcomes']+=1
                    data=json.loads(loop.improver.propose_from_outcomes(ids[-1],loop.tasks,'alice').read_text())
                    metrics['exact_cohorts']+=int(set(data['evidence_task_ids'])==set(ids))
                    metrics['cross_intent_matches']+=len(set(data['evidence_task_ids'])-set(ids))
                    metrics['automatic_executable_proposals']+=int(data['executable'] or bool(data['steps']))
                self.assertEqual(metrics,corpus['thresholds'])
            finally:loop.close()

    def setup_cohort(self, root):
        tasks=TaskStore(root/'tasks.db');manager=SkillManager(root/'skills')
        improver=SkillImprover(manager,root/'vault'/'skill_proposals',tasks)
        ids=[]
        for i in range(3):
            task=tasks.create('save goal '+str(i),owner='alice');ids.append(task)
            tasks.event(task,{'tool_result':{'tool':'write_file','ok':True,'verified':True}})
            tasks.finish(task,'saved')
        return tasks,improver,ids

    def test_intent_feedback_required_and_rejections_block_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks,improver,ids=self.setup_cohort(Path(tmp))
            with self.assertRaises(ValueError):improver.propose_from_outcomes(ids[-1],tasks,'alice')
            for i,task in enumerate(ids):tasks.feedback(task,'alice','different' if i==0 else 'save-goal',True)
            with self.assertRaises(ValueError):improver.propose_from_outcomes(ids[-1],tasks,'alice')
            tasks.feedback(ids[0],'alice','save-goal',True)
            proposal=improver.propose_from_outcomes(ids[-1],tasks,'alice')
            data=json.loads(proposal.read_text());self.assertEqual(data['workflow_id'],'save-goal')
            self.assertFalse(data['executable']);self.assertEqual(data['steps'],[])
            tasks.feedback(ids[0],'alice','save-goal',False,'The action happened but the goal was wrong')
            with self.assertRaises(ValueError):improver.propose_from_outcomes(ids[-1],tasks,'alice')
            with self.assertRaises(ValueError):improver.approve(proposal,improver._digest(data))
            failed=tasks.create('failed attempt',owner='alice');tasks.finish(failed,'provider unavailable','failed')
            with self.assertRaises(ValueError):tasks.feedback(failed,'alice','save-goal',True)
            with self.assertRaises(ValueError):tasks.feedback(ids[0],'bob','save-goal',True)

    def test_changed_evidence_invalidates_review_after_restart_and_is_erased(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks,improver,ids=self.setup_cohort(root)
            for task in ids:tasks.feedback(task,'alice','save-goal',True)
            path=improver.propose_from_outcomes(ids[-1],tasks,'alice')
            # Validate the durable evidence binding independently of executable steps.
            data=json.loads(path.read_text());improver._validate_evidence(data)
            tasks.feedback(ids[0],'alice','save-goal',True,'Corrected owner assessment')
            restarted=SkillImprover(improver.manager,improver.proposals_dir,TaskStore(tasks.path))
            with self.assertRaises(ValueError):restarted._validate_evidence(data)
            with self.assertRaises(ValueError):restarted.approve(path,improver._digest(data))
            bob=tasks.create('private',owner='bob');tasks.finish(bob,'done');tasks.feedback(bob,'bob','save-goal',True)
            erasure=OwnerErasure(root);erasure.erase('alice',erasure.preview('alice')['confirmation'])
            with connect(tasks.path) as db:self.assertEqual(db.execute('SELECT owner FROM task_feedback').fetchall(),[('bob',)])
            self.assertFalse(path.exists())

    def test_authenticated_operator_feedback_endpoint(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest('API optional dependencies unavailable')
        from api.server import create_app
        from agent.enhanced_loop import AgentLoop
        from test_phase9_loop import make_settings
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                task=loop.tasks.create('goal',owner='alice');loop.tasks.finish(task,'done')
                client=TestClient(create_app(loop));url='/v1/tasks/'+task+'/feedback'
                body={'owner':'alice','workflow_id':'save-goal','accepted':True}
                self.assertEqual(client.post(url,json=body).status_code,401)
                headers={'Authorization':'Bearer '+loop.settings.api_token}
                self.assertEqual(client.post(url,json=body,headers=headers).status_code,200)
                body['owner']='bob'
                self.assertEqual(client.post(url,json=body,headers=headers).status_code,400)
                self.assertNotIn('task_feedback',loop.registry._tools)
            finally:loop.close()

    def test_negative_feedback_prevents_installing_previously_reviewed_runtime_skill(self):
        from agent.enhanced_loop import AgentLoop
        from test_phase9_loop import make_settings
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                ids=[]
                for i in range(3):
                    task=loop.tasks.create('save goal '+str(i),owner='alice');ids.append(task)
                    result=loop.sandbox.write_file('goal.txt',str(i))
                    self.assertTrue(result.ok)
                    self.assertEqual(loop.sandbox.read_file('goal.txt').output,str(i))
                    loop.tasks.event(task,{'tool_result':{'tool':'write_file','ok':True,'verified':True}})
                    loop.tasks.finish(task,'saved');loop.tasks.feedback(task,'alice','save-goal',True)
                path=loop.improver.propose_from_outcomes(ids[-1],loop.tasks,'alice')
                review=loop.improver.review(ids[-1],[{'tool':'write_file','arguments':{'path':'goal.txt','content':'{{goal}}'}}],loop.registry)
                loop.tasks.feedback(ids[0],'alice','save-goal',False,'Wrong goal content despite successful file write')
                restarted=SkillImprover(loop.skills,loop.improver.proposals_dir,TaskStore(loop.tasks.path))
                with self.assertRaises(ValueError):restarted.approve(path,review['review_digest'])
                self.assertEqual(json.loads(path.read_text())['status'],'reviewed')
                self.assertFalse(any(s['name']==review['proposal']['name'] for s in loop.skills.list()))
            finally:loop.close()
