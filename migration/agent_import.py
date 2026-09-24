"""Safe migration planner for OpenClaw and Hermes user data."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import json,shutil

@dataclass(frozen=True)
class MigrationItem:
    category:str;source:str;destination:str;action:str;reason:str=""

class AgentMigration:
    def __init__(self,aiba_root:Path,data_dir:Path):
        self.root=aiba_root.resolve();self.data=data_dir.resolve()

    def plan(self,kind:str,source:Path,preset:str="user-data")->dict:
        if kind not in {"claw","hermes"}:raise ValueError("kind must be claw or hermes")
        if preset not in {"user-data","full"}:raise ValueError("preset must be user-data or full")
        src=source.expanduser().resolve()
        if not src.is_dir():raise FileNotFoundError(src)
        items=[]
        def add(cat,rel,dest):
            p=src/rel
            if p.exists():items.append(MigrationItem(cat,str(p),str(dest),"copy"))
        # User-authored persona/profile/context only. Infrastructure and secrets
        # are intentionally not migrated by the normal presets.
        for rel,dest in [("SOUL.md",self.root/"SOUL.md"),("USER.md",self.data/"migration"/kind/"USER.md"),
                         ("MEMORY.md",self.data/"migration"/kind/"MEMORY.md"),("AGENTS.md",self.data/"migration"/kind/"AGENTS.md")]:
            add("user-data",rel,dest)
        skill_candidates=["skills","optional-skills"] if kind=="hermes" else ["skills","workspace/skills"]
        for rel in skill_candidates:
            p=src/rel
            if p.is_dir():items.append(MigrationItem("skills",str(p),str(self.root/"skills"/f"{kind}-imports"),"copy"))
        # Archive unsupported user docs for manual review; never activate them.
        for rel in ("IDENTITY.md","TOOLS.md","HEARTBEAT.md","BOOTSTRAP.md"):
            add("archive",rel,self.data/"migration"/kind/"archive"/rel)
        skipped=[
          {"category":"secrets","reason":"API keys, tokens, auth profiles and .env are never imported by this command"},
          {"category":"infrastructure","reason":"MCP, plugins, hooks, cron, gateways, channel bindings and remote execution config require separate review"},
        ]
        return {"source":str(src),"kind":kind,"preset":preset,"dry_run":True,"items":[asdict(x) for x in items],"skipped":skipped}

    def apply(self,plan:dict)->dict:
        migrated=[];conflicts=[]
        for item in plan["items"]:
            src=Path(item["source"]);dst=Path(item["destination"])
            if dst.exists():
                conflicts.append({**item,"reason":"destination exists"});continue
            dst.parent.mkdir(parents=True,exist_ok=True)
            if src.is_dir():shutil.copytree(src,dst,symlinks=False,ignore=shutil.ignore_patterns(".git","__pycache__","*.pyc",".env","auth-profiles.json"))
            else:shutil.copy2(src,dst)
            migrated.append(item)
        report={"kind":plan["kind"],"source":plan["source"],"migrated":migrated,"conflicts":conflicts,"skipped":plan["skipped"]}
        report_dir=self.data/"migration"/plan["kind"];report_dir.mkdir(parents=True,exist_ok=True)
        (report_dir/"last-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        return report
