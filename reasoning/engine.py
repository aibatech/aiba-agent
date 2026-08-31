from __future__ import annotations
import json,re
SYSTEM=('You are AIBA Agent v1.0. Work autonomously, safely, and verify consequential results. Never expose private chain-of-thought. Valid actions: '
'{"type":"tool_call","tool":"name","arguments":{}}, {"type":"final","response":"text"}, or '
'{"type":"delegate","role":"research|builder|reviewer","instruction":"text"}. Use listed tools only; verify results; never invent tool output.')
class ReasoningEngine:
    def __init__(self,provider,registry,retrieval,tasks,max_steps=15):self.provider=provider;self.registry=registry;self.retrieval=retrieval;self.tasks=tasks;self.max_steps=max_steps
    def _parse(self,text):
        if isinstance(text,dict):a=text
        else:
            try:a=json.loads(text)
            except json.JSONDecodeError:
                m=re.search(r'\{.*\}',text,re.S)
                if not m:return {'type':'final','response':text}
                a=json.loads(m.group())
        if a.get('type') not in {'tool_call','final','delegate'}:raise ValueError('Unknown action type')
        return a
    def run(self,task_id,user_input,task_type=None,manual_model_id=None):
        memories=self.retrieval.retrieve(user_input,7);schemas=self.registry.schemas();messages=[{'role':'system','content':SYSTEM+'\nTools: '+json.dumps(schemas)},{'role':'user','content':user_input+'\nRelevant memory: '+json.dumps(memories,default=str)}];used=[]
        for step in range(self.max_steps):
            action=self._parse(self.provider.complete(messages,schemas,task_type=task_type,manual_model_id=manual_model_id));self.tasks.event(task_id,{'step':step,'action':action,'route':getattr(self.provider,'last_route',None)})
            if action['type']=='final':return str(action.get('response','')),used
            if action['type']=='delegate':
                role=action.get('role','worker');instruction=action.get('instruction','');messages += [{'role':'assistant','content':json.dumps(action)},{'role':'user','content':f'Delegated {role} lane completed analysis request: {instruction}. Continue with available tools; this is one AIBA runtime, not an independent agent.'}];continue
            name=action.get('tool');args=action.get('arguments') or {};res=self.registry.execute(name,args);used.append(name)
            messages += [{'role':'assistant','content':json.dumps(action)},{'role':'user','content':'Tool result: '+json.dumps({'ok':res.ok,'output':res.output,'error':res.error},default=str)}]
        raise RuntimeError(f'Stopped after maximum reasoning steps ({self.max_steps})')
