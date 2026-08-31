import json,os,tempfile,unittest
from pathlib import Path
from runtime.queue import JobQueue
from runtime.worker import Worker
from runtime.scheduler import Scheduler
from skills.manager import SkillManager
from security.auth import AuthStore
from tools.base import ToolResult

class FakeRegistry:
    def execute(self,name,args):return ToolResult(True,{'name':name,'args':args})

class V03Tests(unittest.TestCase):
    def test_queue_worker_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            q=JobQueue(Path(d)/'jobs.db');i=q.enqueue('echo',{'x':2});w=Worker(q,{'echo':lambda p:p['x']*2});self.assertTrue(w.run_once());self.assertEqual(q.get(i)['status'],'complete')
            j=q.enqueue('echo',{'x':3});claimed=q.claim();self.assertEqual(claimed['id'],j);self.assertEqual(q.recover(),1);self.assertEqual(q.get(j)['status'],'queued')
    def test_scheduler_enforces_minimum(self):
        with tempfile.TemporaryDirectory() as d:
            q=JobQueue(Path(d)/'jobs.db');s=Scheduler(Path(d)/'schedules.db',q)
            with self.assertRaises(ValueError):s.add_interval('bad','agent_task',{},30)
            self.assertTrue(s.add_interval('ok','agent_task',{'prompt':'x'},60))
    def test_skill_create_and_execute(self):
        with tempfile.TemporaryDirectory() as d:
            m=SkillManager(Path(d));m.create('Write Note','test',[{'tool':'write_file','arguments':{'path':'{{name}}.txt','content':'hello'}}]);out=m.execute('write-note',FakeRegistry(),{'name':'a'});self.assertTrue(out[0]['ok']);self.assertEqual(out[0]['output']['args']['path'],'a.txt')
    def test_auth_token(self):
        with tempfile.TemporaryDirectory() as d:
            a=AuthStore(Path(d)/'auth.db');token=a.create('test');self.assertTrue(a.verify(token));self.assertFalse(a.verify(token+'x'))
    def test_permissions_include_sensitive_disabled(self):
        data=json.loads((Path(__file__).parents[1]/'config'/'permissions.json').read_text());self.assertFalse(data['tools']['desktop_click']['enabled']);self.assertFalse(data['tools']['vision_analyze']['enabled'])

if __name__=='__main__':unittest.main()
