import json,os,tempfile,unittest
from pathlib import Path
from config.settings import Settings
from security.policy import SecurityPolicy
from tools.sandbox import Sandbox
from memory.vault import MemoryVault
from agent.tasks import TaskStore
class V02Tests(unittest.TestCase):
    def policy(self,d):
        cfg=Path(d)/'p.json'; cfg.write_text(json.dumps({'version':1,'tools':{'read_file':{'enabled':True,'requires_approval':False}},'blocked_command_fragments':['rm -rf /']})); return SecurityPolicy(Path(d),cfg)
    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as d:
            s=Sandbox(Path(d),10,self.policy(d));
            with self.assertRaises(PermissionError):s.read_file('../x')
    def test_command_block(self):
        with tempfile.TemporaryDirectory() as d:self.assertFalse(self.policy(d).check_command('rm -rf /').allowed)
    def test_markdown_sync(self):
        with tempfile.TemporaryDirectory() as d:
            vdir=Path(d)/'vault'; (vdir/'profile').mkdir(parents=True); (vdir/'profile'/'mission.md').write_text('AIBA gives everyone a fair chance')
            v=MemoryVault(Path(d)/'m.db',vdir); self.assertTrue(v.search('fair chance'))
    def test_task_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            t=TaskStore(Path(d)/'t.db'); i=t.create('test'); t.event(i,{'x':1}); t.finish(i,'done')
    def test_write_read(self):
        with tempfile.TemporaryDirectory() as d:
            s=Sandbox(Path(d),10,self.policy(d)); self.assertTrue(s.write_file('a.txt','hello').ok); self.assertEqual(s.read_file('a.txt').output,'hello')
if __name__=='__main__':unittest.main()

class LocalProviderTests(unittest.TestCase):
    def test_command_ignores_retrieved_context(self):
        from models.provider import LocalProvider
        action = json.loads(LocalProvider().complete([{"role":"user","content":"/remember clean memory\nRelevant memory: [{\"noise\":true}]"}], []))
        self.assertEqual(action["arguments"]["content"], "clean memory")
