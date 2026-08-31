import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.browser import _public_url
from tools.base import Tool,ToolResult
from tools.registry import ToolRegistry
from approvals.manager import ApprovalManager
from security.audit import AuditLog
from security.policy import SecurityPolicy
from models.provider import OpenAIProvider

class V10Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);self.ws=root/'ws';self.ws.mkdir()
        cfg=root/'permissions.json';cfg.write_text(json.dumps({'version':1,'tools':{'echo':{'enabled':True,'requires_approval':False}},'blocked_command_fragments':[]}))
        self.registry=ToolRegistry(AuditLog(root/'audit.jsonl'),ApprovalManager(False),SecurityPolicy(self.ws,cfg))
    def tearDown(self):self.tmp.cleanup()
    def test_registry_rejects_unknown_arguments(self):
        self.registry.register(Tool('echo','echo',lambda value:ToolResult(True,value),{'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}))
        self.assertFalse(self.registry.execute('echo',{'value':'ok','extra':1}).ok)
    def test_private_browser_targets_are_blocked(self):
        self.assertFalse(_public_url('http://127.0.0.1/admin'))
        self.assertFalse(_public_url('file:///etc/passwd'))
    def test_openai_sends_native_tools(self):
        provider=OpenAIProvider('test')
        response={'choices':[{'message':{'tool_calls':[{'function':{'name':'echo','arguments':'{"value":"ok"}'}}]}}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret'}),patch('models.provider._post',return_value=response) as post:
            action=provider.complete([{'role':'user','content':'go'}],[{'name':'echo','description':'echo','parameters':{'type':'object'}}])
        self.assertEqual(action['tool'],'echo');self.assertIn('tools',post.call_args.args[1])

if __name__=='__main__':unittest.main()
