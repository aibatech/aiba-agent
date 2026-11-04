import tempfile
import unittest
from pathlib import Path
from skills.manager import SkillManager
from tools.base import ToolResult

class SkillOutcomeTests(unittest.TestCase):
    def test_measure_versions_failures_isolation_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manager=SkillManager(root/'skills',root/'outcomes.db')
            calls=[]
            class Registry:
                def execute(self,name,args,blocked=None):
                    calls.append(name)
                    return ToolResult(name!='fail',verified=name!='fail')
            registry=Registry()
            manager.create('workflow','baseline',[{'tool':'read'},{'tool':'read'},{'tool':'write'}])
            for _ in range(3):manager.execute('workflow',registry,owner='alice')
            manager.create('workflow','candidate',[{'tool':'read'},{'tool':'write'}],version='0.2.0')
            for _ in range(3):manager.execute('workflow',registry,owner='alice')
            restarted=SkillManager(root/'skills',root/'outcomes.db')
            rows=restarted.outcomes.summary('alice','workflow')
            report=restarted.outcomes.compare('alice','workflow',rows[0]['digest'],rows[1]['digest'])
            self.assertEqual(report['mean_tool_calls_delta'],-1)
            self.assertEqual(report['success_rate_delta'],0)
            self.assertFalse(report['certified_improvement'])
            self.assertEqual(restarted.outcomes.summary('bob','workflow'),[])
            manager.create('workflow','bad candidate',[{'tool':'fail'}],version='0.3.0')
            manager.execute('workflow',registry,owner='alice')
            bad=manager.outcomes.summary('alice','workflow')[-1]
            self.assertEqual(bad['success_rate'],0)
            manager.rollback('workflow','0.2.0')
            self.assertTrue(all(row['ok'] for row in manager.execute('workflow',registry,owner='alice')))

    def test_operator_http_outcomes_require_authentication(self):
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
                client=TestClient(create_app(loop))
                url='/v1/skills/example/outcomes?owner=alice'
                self.assertEqual(client.get(url).status_code,401)
                response=client.get(url,headers={'Authorization':'Bearer '+loop.settings.api_token})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['versions'],[])
                denied=client.post('/v1/skills/example/compare',json={'owner':'alice','baseline_digest':'a'*64,'candidate_digest':'b'*64})
                self.assertEqual(denied.status_code,401)
            finally:loop.close()

    def test_reviewed_workflow_reduces_calls_on_matched_file_corpus(self):
        import json
        from approvals.manager import ApprovalManager
        from security.policy import SecurityPolicy
        from security.audit import AuditLog
        from tools.registry import ToolRegistry
        from tools.base import Tool
        from tools.sandbox import Sandbox
        from skills.improver import SkillImprover
        from reasoning.verification import verify_file_write
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'workspace';workspace.mkdir()
            config=root/'policy.json';config.write_text(json.dumps({'version':1,'tools':{
                'write_file':{'enabled':True,'requires_approval':True},
                'read_file':{'enabled':True,'requires_approval':False}}}))
            policy=SecurityPolicy(workspace,config);approvals=ApprovalManager(False)
            registry=ToolRegistry(AuditLog(root/'audit'),approvals,policy)
            sandbox=Sandbox(workspace,10,policy)
            registry.register(Tool('write_file','write',sandbox.write_file,{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']},
                verifier=lambda args,res:verify_file_write(sandbox.resolve,args,res)))
            registry.register(Tool('read_file','read',sandbox.read_file,{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}))
            manager=SkillManager(root/'skills',root/'outcomes.db');improver=SkillImprover(manager,root/'proposals')
            base=[{'tool':'write_file','arguments':{'path':'goal.txt','content':'{{text}}'}},
                  {'tool':'read_file','arguments':{'path':'goal.txt'}},
                  {'tool':'read_file','arguments':{'path':'goal.txt'}}]
            proposal=improver.propose('matchedcase','Save and verify a goal',['write_file','read_file'],'verified')
            reviewed=improver.review('matchedcase',base,registry,'Baseline reviewed',version='1.0.0')
            skill=improver.approve(proposal,reviewed['review_digest'])
            cases=['Launch Atlas','Prepare the budget','Write the notebook']
            for version,steps in [('1.0.0',base),('1.1.0',base[:2])]:
                if version=='1.1.0':
                    # An explicit new review is required to install the improvement.
                    next_proposal=improver.propose('matchednext','Remove redundant verification read',['read_file'],'same outcome')
                    data=json.loads(next_proposal.read_text());data['name']=skill.name;next_proposal.write_text(json.dumps(data))
                    reviewed=improver.review('matchednext',steps,registry,'Keep one read-back; remove duplicate',version=version)
                    improver.approve(next_proposal,reviewed['review_digest'])
                for text in cases:
                    (workspace/'goal.txt').unlink(missing_ok=True)
                    fingerprint=approvals.action_fingerprint('write_file',{'path':'goal.txt','content':text})
                    with approvals.request_scope([fingerprint]):
                        outputs=manager.execute(skill.name,registry,{'text':text},owner='alice')
                    self.assertTrue(all(row['ok'] for row in outputs))
                    self.assertEqual(outputs[-1]['output'],text)
                    self.assertEqual((workspace/'goal.txt').read_text(),text)
            summaries=manager.outcomes.summary('alice',skill.name)
            report=manager.outcomes.compare('alice',skill.name,summaries[0]['digest'],summaries[1]['digest'])
            self.assertEqual(report['success_rate_delta'],0)
            self.assertEqual(report['mean_tool_calls_delta'],-1)
            self.assertEqual(report['baseline']['successes'],3)
            self.assertEqual(report['candidate']['successes'],3)
