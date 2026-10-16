import tempfile
import unittest
from pathlib import Path
from agent.tasks import TaskStore
from reasoning.engine import ReasoningEngine
from tools.base import ToolResult

class ExecutionPlanTests(unittest.TestCase):
    def engine(self,root,actions):
        iterator=iter(actions);calls=[]
        class Provider:
            def complete(self,*args,**kwargs):return next(iterator)
        class Registry:
            def schemas(self,*args):return []
            def execute(self,name,args,blocked=None):
                calls.append(name)
                return ToolResult(name!='fail',verified=name!='fail')
        class Retrieval:
            def retrieve(self,*args):return []
        tasks=TaskStore(root/'tasks.db')
        return ReasoningEngine(Provider(),Registry(),Retrieval(),tasks),tasks,calls

    def test_plan_progress_persists_and_unfinished_plan_cannot_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            engine,tasks,calls=self.engine(root,[{'type':'plan','steps':['read source','save result']},
                {'type':'tool_call','tool':'read','arguments':{},'plan_step':0},
                {'type':'final','response':'Everything complete'}])
            tid=tasks.create('work',owner='alice')
            answer,_=engine.run(tid,'work')
            self.assertEqual(engine.execution_status,'partial')
            self.assertNotEqual(answer,'Everything complete')
            restarted=TaskStore(root/'tasks.db')
            self.assertEqual([x['status'] for x in restarted.plan(tid)],['verified','pending'])
            engine,tasks,calls=self.engine(root,[{'type':'tool_call','tool':'write','arguments':{},'plan_step':1},
                {'type':'final','response':'Verified'}])
            self.assertEqual(engine.run(tid,'continue')[0],'Verified')
            self.assertEqual(calls,['write'])
            self.assertEqual(engine.execution_status,'complete')

    def test_invalid_plan_reference_cannot_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine,tasks,calls=self.engine(Path(tmp),[{'type':'plan','steps':['write']},
                {'type':'tool_call','tool':'write','arguments':{},'plan_step':99}])
            with self.assertRaises(ValueError):engine.run(tasks.create('work'),'work')
            self.assertEqual(calls,[])

    def test_delegation_updates_plan_and_persists_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine,tasks,calls=self.engine(Path(tmp),[
                {'type':'plan','steps':['review result']},
                {'type':'delegate','role':'reviewer','instruction':'review','plan_step':0},
                {'type':'final','response':'Reviewed'}])
            tid=tasks.create('review')
            self.assertEqual(engine.run(tid,'review')[0],'Reviewed')
            self.assertEqual(calls,['delegate_task'])
            self.assertEqual(tasks.plan(tid)[0]['status'],'verified')

    def test_delegation_cannot_bypass_plan_reference_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine,tasks,calls=self.engine(Path(tmp),[
                {'type':'plan','steps':['review result']},
                {'type':'delegate','role':'reviewer','instruction':'review','plan_step':-1}])
            with self.assertRaises(ValueError):engine.run(tasks.create('review'),'review')
            self.assertEqual(calls,[])
