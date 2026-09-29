import json,tempfile,unittest
from pathlib import Path
from skills.manager import SkillManager
from skills.improver import SkillImprover

class MemorySkillLearningTests(unittest.TestCase):
    def test_memory_is_evidence_and_proposal_requires_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mgr=SkillManager(root/'skills');imp=SkillImprover(mgr,root/'proposals')
            p=imp.propose('abc123','Research roofing leads',['web_search'],'done',[{'content':'Owner prefers verified local leads'}])
            d=json.loads(p.read_text());self.assertEqual(d['status'],'requires_review');self.assertIn('Owner prefers',d['memory_evidence'][0]);self.assertEqual(mgr.list(),[])
            skill=imp.approve(p);self.assertTrue((skill.path/'skill.json').is_file())
    def test_similar_success_proposes_versioned_update(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mgr=SkillManager(root/'skills');mgr.create('research-roofing-leads','x',[{'tool':'web_search','arguments':{}}])
            imp=SkillImprover(mgr,root/'proposals');p=imp.propose('def456','Research roofing leads in Atlanta',['web_search'],'ok',[]);d=json.loads(p.read_text())
            self.assertEqual(d['action'],'update');self.assertEqual(d['target_skill'],'research-roofing-leads');self.assertEqual(d['version'],'0.1.1');self.assertEqual(mgr.get('research-roofing-leads').version,'0.1.0')

if __name__=='__main__':unittest.main()
