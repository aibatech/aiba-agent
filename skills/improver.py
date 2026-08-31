from __future__ import annotations
import json
from pathlib import Path
from skills.manager import SkillManager
class SkillImprover:
    def __init__(self,manager:SkillManager,proposals_dir:Path): self.manager=manager;self.proposals_dir=proposals_dir;proposals_dir.mkdir(parents=True,exist_ok=True)
    def propose(self,task_id:str,task:str,tools:list[str],result:str)->Path:
        steps=[{'tool':name,'arguments':{}} for name in tools]
        proposal={'task_id':task_id,'name':f'learned-{task_id[:8]}','description':f'Draft learned from: {task[:160]}','status':'requires_review','steps':steps,'result_excerpt':result[:500]}
        path=self.proposals_dir/f'{task_id}.json';path.write_text(json.dumps(proposal,indent=2),encoding='utf-8');return path
    def approve(self,proposal_path:Path):
        data=json.loads(proposal_path.read_text()); return self.manager.create(data['name'],data['description'],data['steps'])
