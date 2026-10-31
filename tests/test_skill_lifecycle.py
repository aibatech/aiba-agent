import json
import tempfile
import unittest
from pathlib import Path
from approvals.manager import ApprovalManager
from security.audit import AuditLog
from security.policy import SecurityPolicy
from skills.manager import SkillManager
from skills.improver import SkillImprover
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


class SkillLifecycleTests(unittest.TestCase):
    def test_review_install_execute_permission_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / 'policy.json'
            policy.write_text(json.dumps({'version': 1, 'tools': {'write_file': {'enabled': True, 'requires_approval': True}}}))
            approvals = ApprovalManager(interactive=False)
            registry = ToolRegistry(AuditLog(root/'audit'), approvals, SecurityPolicy(root, policy))
            calls = []
            registry.register(Tool('write_file', 'test', lambda content: (calls.append(content) or ToolResult(True, content)),
                                  {'type': 'object', 'properties': {'content': {'type': 'string'}}, 'required': ['content'], 'additionalProperties': False}))
            manager = SkillManager(root/'skills')
            improver = SkillImprover(manager, root/'proposals')
            proposal = improver.propose('task123', 'write greeting', ['write_file'], 'done')
            steps = [{'tool': 'write_file', 'arguments': {'content': 'hello'}}]
            review = improver.review('task123', steps, registry, 'Use this greeting')
            with self.assertRaises(ValueError):
                improver.approve(proposal, 'wrong')
            skill = improver.approve(proposal, review['review_digest'])
            with self.assertRaises(ValueError):
                improver.approve(proposal, review['review_digest'])
            self.assertFalse(manager.execute(skill.name, registry)[0]['ok'])
            self.assertEqual(calls, [])
            fp = approvals.action_fingerprint('write_file', steps[0]['arguments'])
            with approvals.request_scope([fp]):
                self.assertTrue(manager.execute(skill.name, registry)[0]['ok'])
            self.assertEqual(calls, ['hello'])
            manager.create(skill.name, 'v2', [{'tool': 'write_file', 'arguments': {'content': 'new'}}], '0.2.0')
            manager.rollback(skill.name, '0.1.0')
            self.assertEqual(manager.get(skill.name).steps, steps)
            with self.assertRaises(ValueError):
                manager.rollback(skill.name, '../../outside')
            with self.assertRaises(ValueError):
                improver.propose('../escape', 'task', [], '')

    def test_nested_execution_preserves_blocked_tools_and_reports_failure(self):
        from agent.loop import AgentLoop
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manager=SkillManager(root/'skills')
            manager.create('workflow','test',[{'tool':'remember','arguments':{'content':'private'}}])
            calls=[]
            class Registry:
                def execute(self,name,args,blocked=None):
                    calls.append((name,blocked))
                    return ToolResult(False,error='blocked') if name in (blocked or set()) else ToolResult(True)
            loop=SimpleNamespace(skills=manager,registry=Registry(),_current_user='alice',
                personal=SimpleNamespace(blocked_tools=lambda user:{'remember'}))
            result=AgentLoop._run_skill(loop,'workflow')
            self.assertFalse(result.ok)
            self.assertIn('remember',calls[0][1])
            manager.create('recursive','test',[{'tool':'run_skill','arguments':{'name':'recursive'}}])
            self.assertFalse(manager.execute('recursive',loop.registry)[0]['ok'])

    def test_symlink_skill_cannot_read_or_overwrite_external_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = SkillManager(root/'skills')
            outside = root/'outside'
            outside.mkdir()
            try:
                (manager.root/'evil').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation unavailable')
            for action in (lambda: manager.create('evil', '', []), lambda: manager.get('evil')):
                with self.assertRaises(ValueError):
                    action()

    def test_optional_fields_and_unknown_fields_validate_correctly(self):
        from tools.registry import _valid
        schema={'type':'object','properties':{'path':{'type':'string'}},'additionalProperties':False}
        self.assertTrue(_valid({},schema))
        self.assertTrue(_valid({'path':'.'},schema))
        self.assertFalse(_valid({'path':'.','injected':'value'},schema))
        self.assertFalse(_valid({'injected':'value'},schema))
