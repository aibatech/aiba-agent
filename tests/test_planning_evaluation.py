import json
import unittest
from scripts.evaluate_planning import ROOT, evaluate

class PlanningEvaluationTests(unittest.TestCase):
    def test_harness_rejects_unsupported_completion_and_wrong_effects(self):
        corpus=json.loads((ROOT/'benchmarks/execution/planning-v1.json').read_text())
        class Unsupported:
            def complete(self,*a):return {'type':'final','response':'Done'}
        self.assertFalse(any(r['passed'] for r in evaluate(Unsupported(),corpus)))
        class Scripted:
            def __init__(self,wrong=False):self.case=0;self.step=0;self.wrong=wrong
            def complete(self,*a):
                actions=[{'type':'plan','steps':['read source','write result']},
                         {'type':'tool_call','tool':'read_file','arguments':{'path':'source.txt'},'plan_step':0},
                         {'type':'tool_call','tool':'write_file','arguments':{'path':'result.txt','content':'wrong' if self.wrong else corpus['cases'][self.case]['expected']},'plan_step':1},
                         {'type':'final','response':'Done'}]
                result=actions[self.step];self.step+=1
                if self.step==4:self.step=0;self.case+=1
                return result
        self.assertTrue(all(r['passed'] for r in evaluate(Scripted(),corpus)))
        self.assertFalse(any(r['passed'] for r in evaluate(Scripted(True),corpus)))
