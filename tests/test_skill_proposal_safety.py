import json
import tempfile
import unittest
from pathlib import Path
from skills.manager import SkillManager
from skills.improver import SkillImprover

class SkillProposalSafetyTests(unittest.TestCase):
    def test_observed_tools_are_not_replayable_instructions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            improver=SkillImprover(SkillManager(root/"skills"),root/"proposals")
            proposal=improver.propose("job123","write a private document",["host_write_file"],"completed")
            data=json.loads(proposal.read_text())
            self.assertEqual(data["steps"],[])
            self.assertEqual(data["observed_tools"],["host_write_file"])
            self.assertFalse(data["executable"])
            with self.assertRaises(ValueError):
                improver.approve(proposal)

if __name__=="__main__":
    unittest.main()
