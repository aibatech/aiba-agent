import json,tempfile,unittest
from pathlib import Path
from security.policy import SecurityPolicy
from approvals.manager import ApprovalManager
from security.audit import AuditLog
from tools.registry import ToolRegistry
from tools.base import Tool
from tools.host_files import HostFiles

class OwnerCapabilityTests(unittest.TestCase):
    def test_host_write_requires_approval_then_executes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ws=root/'ws';ws.mkdir();perms=root/'p.json';perms.write_text(json.dumps({'version':1,'tools':{'host_write_file':{'enabled':True,'requires_approval':True}}}))
            policy=SecurityPolicy(ws,perms,True);approvals=ApprovalManager(interactive=False);audit=AuditLog(root/'audit.jsonl');reg=ToolRegistry(audit,approvals,policy)
            host=HostFiles();reg.register(Tool('host_write_file','write host',host.write,{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content'],'additionalProperties':False}))
            target=root/'outside.txt'
            with approvals.request_scope():
                denied=reg.execute('host_write_file',{'path':str(target),'content':'x'});self.assertFalse(denied.ok);self.assertFalse(target.exists());self.assertEqual(approvals.pending_requests()[0]['tool'],'host_write_file')
            with approvals.request_scope(['host_write_file']):
                ok=reg.execute('host_write_file',{'path':str(target),'content':'x'});self.assertTrue(ok.ok);self.assertEqual(target.read_text(),'x')

if __name__=='__main__':unittest.main()
