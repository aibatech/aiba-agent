from __future__ import annotations
import json,re,shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
@dataclass
class Skill:
    name:str;description:str;version:str;steps:list[dict[str,Any]];path:Path;instructions:str=''
class SkillManager:
    def __init__(self,root:Path): self.root=root;root.mkdir(parents=True,exist_ok=True)
    def _safe(self,name:str)->str:
        value=re.sub(r'[^a-z0-9_-]+','-',name.lower()).strip('-')
        if not value:raise ValueError('Invalid skill name')
        return value
    def create(self,name:str,description:str,steps:list[dict],version:str='0.1.0')->Skill:
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):raise ValueError('Skill version must use semantic versioning')
        if not isinstance(steps,list) or any(not isinstance(x,dict) or not isinstance(x.get('tool'),str) or not isinstance(x.get('arguments',{}),dict) for x in steps):raise ValueError('Each skill step requires a tool and object arguments')
        slug=self._safe(name); folder=(self.root/slug).resolve(); folder.relative_to(self.root.resolve());folder.mkdir(parents=True,exist_ok=True)
        target=folder/'skill.json'
        # Versioning: if a different version already exists, snapshot the prior
        # one first so it can be reviewed / rolled back later.
        if target.is_file():
            try:
                prev=json.loads(target.read_text(encoding='utf-8'))
                if prev.get('version') and prev.get('version')!=version:
                    # versions are semver-validated (only [0-9A-Za-z.+-]);
                    # raw form is filesystem-safe and human-readable
                    rev=folder/'revisions'/f"{prev['version']}.json"
                    rev.parent.mkdir(parents=True,exist_ok=True)
                    rev.write_text(json.dumps(prev,indent=2),encoding='utf-8')
            except Exception:pass
        data={'name':slug,'description':description,'version':version,'steps':steps}
        target.write_text(json.dumps(data,indent=2),encoding='utf-8')
        return Skill(slug,description,version,steps,folder,'')
    def get(self,name:str)->Skill:
        folder=self.root/self._safe(name);path=folder/'skill.json'
        if path.is_file():
            data=json.loads(path.read_text(encoding='utf-8'));return Skill(data['name'],data.get('description',''),data.get('version','0.1.0'),data.get('steps',[]),path.parent,data.get('instructions',''))
        markdown=folder/'SKILL.md'
        if not markdown.is_file():raise KeyError(name)
        text=markdown.read_text(encoding='utf-8');meta,body=self._frontmatter(text);return Skill(self._safe(meta.get('name',name)),meta.get('description',''),meta.get('version','0.1.0'),[],folder,body)
    def list(self)->list[dict]:
        result=[]
        for folder in sorted(x for x in self.root.iterdir() if x.is_dir()):
            try:s=self.get(folder.name);result.append({'name':s.name,'description':s.description,'version':s.version,'steps':len(s.steps),'format':'aiba-json' if (folder/'skill.json').is_file() else 'portable-markdown'})
            except Exception:continue
        return result
    def revisions(self,name:str)->list[dict]:
        folder=self.root/self._safe(name);rev_dir=folder/'revisions'
        if not rev_dir.is_dir():return []
        out=[]
        for p in sorted(rev_dir.glob('*.json'),key=lambda x:x.name):
            try:
                d=json.loads(p.read_text(encoding='utf-8'))
                out.append({'version':d.get('version',p.stem),'description':d.get('description',''),'steps':len(d.get('steps',[]))})
            except Exception:continue
        return out
    def rollback(self,name:str,version:str)->Skill:
        slug=self._safe(name);folder=self.root/slug;rev=folder/'revisions'/f"{version}.json"
        if not rev.is_file():raise KeyError(f"No saved revision {version} for skill {slug}")
        data=json.loads(rev.read_text(encoding='utf-8'))
        # current (broken) revision is preserved before restoring the target
        target=folder/'skill.json'
        if target.is_file():
            self.create(slug,data.get('description',''),data.get('steps',[]),version=data.get('version','0.1.0'))
        else:
            (folder/'skill.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
        return self.get(slug)
    def _frontmatter(self,text):
        meta={};body=text
        if text.startswith('---\n') and '\n---\n' in text[4:]:
            header,body=text[4:].split('\n---\n',1)
            for line in header.splitlines():
                if ':' in line:
                    key,value=line.split(':',1);meta[key.strip()]=value.strip().strip('"\'')
        return meta,body.strip()
    def import_markdown(self,path:Path):
        if path.name!='SKILL.md':raise ValueError('Portable skill entrypoint must be named SKILL.md')
        text=path.read_text(encoding='utf-8');meta,body=self._frontmatter(text);name=self._safe(meta.get('name') or path.parent.name)
        if not body:raise ValueError('Portable skill instructions cannot be empty')
        target=self.root/name;target.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target/'SKILL.md');return self.get(name)
    def instructions(self,name):
        skill=self.get(name);return {'name':skill.name,'description':skill.description,'version':skill.version,'instructions':skill.instructions,'executable':bool(skill.steps)}
    def execute(self,name:str,registry,variables:dict[str,Any]|None=None)->list[dict]:
        skill=self.get(name); variables=variables or {}; outputs=[]
        if not skill.steps:raise ValueError('Instruction-only portable skills must be reviewed by the model and cannot execute tools directly')
        for index,step in enumerate(skill.steps):
            tool=step['tool'];args=json.loads(json.dumps(step.get('arguments',{})))
            for k,v in list(args.items()):
                if isinstance(v,str):
                    for key,value in variables.items():v=v.replace('{{'+key+'}}',str(value))
                    args[k]=v
            res=registry.execute(tool,args);outputs.append({'step':index,'tool':tool,'ok':res.ok,'output':res.output,'error':res.error})
            if not res.ok:break
        return outputs
