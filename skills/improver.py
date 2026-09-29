from __future__ import annotations
import json,re
from pathlib import Path
from skills.manager import SkillManager

class SkillImprover:
    """Learn reusable skill proposals from successful work + durable memory.

    Learning never silently grants tools. New/updated skills are staged as
    proposals and activation remains an explicit approval boundary.
    """
    def __init__(self,manager:SkillManager,proposals_dir:Path):
        self.manager=manager;self.proposals_dir=proposals_dir;proposals_dir.mkdir(parents=True,exist_ok=True)

    def _slug(self,text:str)->str:
        words=re.findall(r"[a-z0-9]+",(text or "").lower())[:6]
        return "-".join(words)[:56] or "learned-workflow"

    def _next_version(self,current:str)->str:
        try:
            a,b,c=(int(x) for x in current.split(".")[:3]);return f"{a}.{b}.{c+1}"
        except Exception:return "0.1.1"

    def propose(self,task_id:str,task:str,tools:list[str],result:str,memories:list[dict]|None=None)->Path:
        memories=memories or []
        steps=[{'tool':name,'arguments':{}} for name in dict.fromkeys(tools)]
        slug=self._slug(task)
        existing=None
        # Prefer updating a semantically adjacent existing skill by name tokens.
        task_tokens=set(slug.split("-"))
        for row in self.manager.list():
            name=str(row.get("name","")); overlap=len(task_tokens & set(name.split("-")))
            if overlap>=2: existing=name;break
        version="0.1.0";action="create"
        if existing:
            try:version=self._next_version(self.manager.get(existing).version);action="update"
            except Exception:existing=None
        memory_evidence=[str(m.get("content",""))[:300] for m in memories[:5] if isinstance(m,dict) and m.get("content")]
        # Confidence is evidence-based: repeated similar successful workflows,
        # stable memory preferences, and an existing reviewed skill increase it.
        prior=[]
        for p in self.proposals_dir.glob("*.json"):
            try:
                d=json.loads(p.read_text(encoding="utf-8"))
                if d.get("name")== (existing or slug) and d.get("task_id")!=task_id: prior.append(d)
            except Exception: pass
        repetitions=min(len(prior)+1,5)
        memory_strength=min(len(memory_evidence),3)
        score=min(0.35 + 0.10*repetitions + 0.10*memory_strength + (0.15 if existing else 0.0),0.95)
        level="high" if score>=0.80 else ("medium" if score>=0.60 else "low")
        proposal={
            'task_id':task_id,'action':action,'target_skill':existing,
            'name':existing or slug,'version':version,
            'description':f'Learned reusable workflow from: {task[:180]}',
            'status':'requires_review','steps':steps,
            'memory_evidence':memory_evidence,'result_excerpt':result[:700],
            'confidence':{'score':round(score,2),'level':level,'successful_repetitions':repetitions,'memory_signals':memory_strength},
            'safety':'Proposal only. Memory can suggest behavior but cannot grant tools or approvals.'
        }
        path=self.proposals_dir/f'{task_id}.json';path.write_text(json.dumps(proposal,indent=2,ensure_ascii=False),encoding='utf-8');return path

    def reinforce(self,skill_name:str,positive:bool=True,note:str=""):
        """Record explicit owner feedback as evidence for future proposals."""
        path=self.proposals_dir/"feedback.jsonl"
        row={"skill":self.manager._safe(skill_name),"positive":bool(positive),"note":str(note)[:500]}
        with path.open("a",encoding="utf-8") as fh: fh.write(json.dumps(row,ensure_ascii=False)+"\n")
        return row

    def approve(self,proposal_path:Path):
        data=json.loads(proposal_path.read_text(encoding="utf-8"))
        return self.manager.create(data['name'],data['description'],data['steps'],version=data.get('version','0.1.0'))
