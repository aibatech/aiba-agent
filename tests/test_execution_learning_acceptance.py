"""Real stores/runtime/registry; only provider responses and web transport are scripted."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.enhanced_loop import AgentLoop
from agent.tasks import TaskStore
from runtime.queue import JobQueue
from runtime.worker import Worker
from skills.improver import SkillImprover
from skills.manager import SkillManager
from test_phase9_loop import make_settings
from tools.web import WebTools
from sqlite_utils import connect


class ExecutionLearningAcceptanceTests(unittest.TestCase):
    def test_uncertain_action_is_not_retried_after_exception_or_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue=JobQueue(Path(tmp)/'jobs.db');effects=[]
            def dispatch(payload):
                effects.append('effect')
                raise TimeoutError('response lost after effect')
            job=queue.enqueue('action',{})
            worker=Worker(queue,{'action':dispatch})
            worker.run_once()
            self.assertEqual(queue.get(job)['status'],'needs_review')
            self.assertFalse(worker.run_once());self.assertEqual(effects,['effect'])
            second=queue.enqueue('action',{})
            queue.claim();JobQueue(queue.path).recover()
            self.assertEqual(queue.get(second)['status'],'needs_review')
            self.assertIsNone(queue.claim())

    def test_actual_worker_cancellation_prevents_following_runtime_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                job=loop.queue.enqueue('agent_task',{'prompt':'list files','user_id':'alice'})
                def cancelled(*args,**kwargs):
                    loop.queue.cancel(job)
                    return {'type':'tool_call','tool':'list_files','arguments':{}}
                with patch.object(loop.engine.provider,'complete',side_effect=cancelled), patch.object(loop.registry,'execute',wraps=loop.registry.execute) as dispatch:
                    loop.worker.run_once()
                self.assertEqual(loop.queue.get(job)['status'],'cancelled')
                dispatch.assert_not_called()
                with connect(loop.tasks.path) as db:
                    self.assertEqual(db.execute('SELECT status FROM tasks ORDER BY created_at DESC LIMIT 1').fetchone()[0],'cancelled')
            finally:loop.close()

    def test_restart_resume_skips_completed_effect_and_checks_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings=make_settings(Path(tmp));loop=AgentLoop(settings=settings,interactive=False,start_worker=False)
            tid=loop.tasks.create('write then list',owner='alice')
            loop.tasks.set_plan(tid,['write','list'])
            loop.tasks.plan_start(tid,0,'a'*64)
            loop.tasks.plan_result(tid,0,True,True)
            loop.close()
            loop=AgentLoop(settings=settings,interactive=False,start_worker=False)
            try:
                with self.assertRaises(PermissionError):loop.resume_task(tid,'bob')
                actions=iter([{'type':'tool_call','tool':'list_files','arguments':{},'plan_step':1}, {'type':'final','response':'Done'}])
                with patch.object(loop.engine.provider,'complete',side_effect=lambda *a,**k:next(actions)),patch.object(loop.registry,'execute',wraps=loop.registry.execute) as dispatch:
                    self.assertEqual(loop.resume_task(tid,'alice')['status'],'complete')
                    self.assertEqual([c.args[0] for c in dispatch.call_args_list],['list_files'])
            finally:loop.close()

    def test_persisted_running_step_cannot_replay_or_claim_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                tid=loop.tasks.create('uncertain write',owner='alice');loop.tasks.set_plan(tid,['write'])
                loop.tasks.plan_start(tid,0,'b'*64);loop.tasks.finish(tid,'interrupted','interrupted')
                with patch.object(loop.engine.provider,'complete',return_value={'type':'final','response':'Done'}):
                    self.assertEqual(loop.resume_task(tid,'alice')['status'],'partial')
                action={'type':'tool_call','tool':'write_file','arguments':{'path':'x','content':'x'},'plan_step':0}
                with patch.object(loop.engine.provider,'complete',return_value=action),patch.object(loop.registry,'execute',wraps=loop.registry.execute) as dispatch:
                    self.assertEqual(loop.resume_task(tid,'alice')['status'],'failed');dispatch.assert_not_called()
            finally:loop.close()

    def test_evidence_proposal_requires_owner_matched_verified_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=TaskStore(root/'tasks.db')
            improver=SkillImprover(SkillManager(root/'skills'),root/'proposals')
            ids=[]
            for owner,ok in [('alice',True),('bob',True),('alice',False),('alice',True),('alice',True)]:
                tid=tasks.create('save goal',owner=owner);ids.append(tid)
                tasks.event(tid,{'tool_result':{'tool':'write_file','ok':ok,'verified':ok}})
                tasks.finish(tid,'done','complete' if ok else 'failed')
                if len(ids)==1:
                    with self.assertRaises(ValueError):improver.propose_from_outcomes(tid,tasks,'alice')
            with self.assertRaises(ValueError):improver.propose_from_outcomes(ids[-1],tasks,'bob')
            data=json.loads(improver.propose_from_outcomes(ids[-1],tasks,'alice','Keep verification').read_text())
            self.assertEqual(set(data['evidence_task_ids']),{ids[0],ids[3],ids[4]})
            self.assertEqual(data['steps'],[]);self.assertFalse(data['executable'])
            self.assertEqual(data['feedback'],'Keep verification')

    def test_failed_web_pages_are_not_successful_actions(self):
        with patch('tools.web._public_url',return_value=True):
            for response in [(503,'Unavailable'),(200,'<script>empty</script>')]:
                result=WebTools(fetch=lambda *a:response).web_extract(['https://example.com'])
                self.assertFalse(result.ok);self.assertFalse(result.verified)
            result=WebTools(fetch=lambda *a:(200,'<h1>Evidence</h1>')).web_extract(['https://example.com'])
            self.assertTrue(result.ok);self.assertTrue(result.verified)

    def test_reconciliation_is_owner_and_exact_attempt_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks=TaskStore(Path(tmp)/'tasks.db');tid=tasks.create('work',owner='alice')
            tasks.set_plan(tid,['effect']);tasks.plan_start(tid,0,'a'*64)
            with self.assertRaises(ValueError):tasks.reconcile_step(tid,'alice',0,'a'*64,'retry')
            tasks.finish(tid,'interrupted','interrupted')
            with self.assertRaises(PermissionError):tasks.reconcile_step(tid,'bob',0,'a'*64,'retry')
            with self.assertRaises(ValueError):tasks.reconcile_step(tid,'alice',0,'b'*64,'retry')
            tasks.reconcile_step(tid,'alice',0,'a'*64,'retry')
            with self.assertRaises(ValueError):tasks.reconcile_step(tid,'alice',0,'a'*64,'retry')
            tasks.plan_start(tid,0,'b'*64)
            self.assertEqual(tasks.plan(tid)[0]['status'],'running')

    def test_reviewed_skill_negative_outcomes_and_rollback_on_real_registry(self):
        # Predefined criterion: exact target content, plus refusal when writes are blocked.
        # A successful write of the wrong content is a domain failure, even if dispatch succeeds.
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                proposal=loop.improver.propose('baseline','save goal',['write_file'],'advisory')
                def review_install(task,steps,version):
                    review=loop.improver.review(task,steps,loop.registry,'Require exact content',version)
                    return loop.improver.approve(loop.improver._path(task),review['review_digest'])
                base=[{'tool':'write_file','arguments':{'path':'goal.txt','content':'{{goal}}'}}]
                skill=review_install('baseline',base,'1.0.0')
                cases=['Atlas','Budget','Notebook'];metrics={}
                for version,steps in [('1.0.0',base),('1.1.0',[{'tool':'write_file','arguments':{'path':'goal.txt','content':'wrong'}}])]:
                    if version=='1.1.0':
                        path=loop.improver.propose('candidate','candidate',['write_file'],'advisory')
                        data=json.loads(path.read_text());data['name']=skill.name;path.write_text(json.dumps(data))
                        review_install('candidate',steps,version)
                    passed=0
                    for goal in cases:
                        content=goal if version=='1.0.0' else 'wrong'
                        args={'path':'goal.txt','content':content}
                        with loop.approvals.request_scope([loop.approvals.action_fingerprint('write_file',args)]):
                            result=loop.skills.execute(skill.name,loop.registry,{'goal':goal},owner='alice')
                        passed+=int(result[0]['ok'] and (loop.settings.workspace_dir/'goal.txt').read_text()==goal)
                    metrics[version]=passed
                    denied=loop.skills.execute(skill.name,loop.registry,{'goal':'denied'},blocked={'write_file'},owner='alice')
                    self.assertFalse(denied[0]['ok'])
                self.assertEqual(metrics,{'1.0.0':3,'1.1.0':0})
                loop.skills.rollback(skill.name,'1.0.0')
                self.assertEqual(loop.skills.get(skill.name).steps,base)
                with self.assertRaises(ValueError):loop.improver.review('candidate',[{'tool':'run_skill','arguments':{'name':skill.name}}],loop.registry)
            finally:loop.close()

    def test_domain_verifiers_reject_successful_dispatch_without_persisted_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                mid=loop.vault.add('old',owner='default')
                cases=[('remember',{'content':'new'},loop.vault,'add',None),
                       ('update_memory',{'memory_id':mid,'content':'new'},loop.vault,'update',None),
                       ('enqueue_task',{'prompt':'later'},loop.queue,'enqueue','missing-job'),
                       ('schedule_task',{'name':'daily','prompt':'later','interval_seconds':60},loop.scheduler,'add_interval','missing-schedule')]
                for tool,args,target,method,value in cases:
                    fp=loop.approvals.action_fingerprint(tool,args)
                    with loop.approvals.request_scope([fp]),patch.object(target,method,return_value=value):
                        result=loop.registry.execute(tool,args)
                    self.assertFalse(result.ok,tool);self.assertFalse(result.verified,tool)
                self.assertEqual(loop.vault.get(mid)['content'],'old')
                args={'memory_id':mid,'content':'new'}
                with loop.approvals.request_scope([loop.approvals.action_fingerprint('update_memory',args)]):
                    result=loop.registry.execute('update_memory',args)
                self.assertTrue(result.ok);self.assertTrue(result.verified)
            finally:loop.close()

    def test_runtime_outcomes_enrich_existing_advisory_without_overwriting_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                ids=[]
                for goal in ['Atlas','Budget','Notebook']:
                    args={'path':'goal.txt','content':goal}
                    actions=iter([{'type':'tool_call','tool':'write_file','arguments':args},{'type':'final','response':'Saved'}])
                    with patch.object(loop.engine.provider,'complete',side_effect=lambda *a,**k:next(actions)),loop.approvals.request_scope([loop.approvals.action_fingerprint('write_file',args)]):
                        result=loop.handle_result('Save '+goal,user_id='alice')
                    self.assertEqual(result['status'],'complete');ids.append(result['task_id'])
                path=loop.improver.propose_from_outcomes(ids[-1],loop.tasks,'alice','Keep exact content')
                evidence=json.loads(path.read_text())
                self.assertEqual(set(evidence['evidence_task_ids']),set(ids))
                self.assertEqual(evidence['steps'],[])
                steps=[{'tool':'write_file','arguments':{'path':'goal.txt','content':'{{goal}}'}}]
                review=loop.improver.review(ids[-1],steps,loop.registry,'Owner supplied arguments')
                with self.assertRaises(ValueError):loop.improver.propose_from_outcomes(ids[-1],loop.tasks,'alice')
                self.assertEqual(loop.improver._digest(loop.improver._load(path)),review['review_digest'])
            finally:loop.close()
