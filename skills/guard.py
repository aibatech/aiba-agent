"""Static review aid for portable Agent Skills packages.

This scanner is intentionally conservative and never marks a skill "safe".
It reports review findings; OS/container/tool policy remains the boundary.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import re

@dataclass(frozen=True)
class SkillFinding:
    severity:str;code:str;path:str;detail:str

class SkillsGuard:
    MAX_FILE=512*1024
    TEXT_SUFFIXES={".md",".txt",".py",".sh",".js",".ts",".json",".yaml",".yml",".toml"}
    RULES=[
      ("high","credential-access",re.compile(r"(?:\.ssh/|\.aws/|\.env\b|id_rsa|keychain|password\s*manager)",re.I)),
      ("high","destructive-command",re.compile(r"\b(?:rm\s+-rf|mkfs\b|dd\s+if=|shutdown\b|reboot\b)",re.I)),
      ("high","download-execute",re.compile(r"(?:curl|wget)[^\n|;]*(?:\||;)\s*(?:sh|bash|python)",re.I)),
      ("medium","network-reference",re.compile(r"https?://|\b(?:curl|wget|requests\.|urllib\.|fetch\()",re.I)),
      ("medium","shell-execution",re.compile(r"\b(?:subprocess\.|os\.system|child_process|eval\s*\(|exec\s*\()",re.I)),
      ("medium","persistence",re.compile(r"(?:crontab|systemd|launchd|registry\s+run|startup)",re.I)),
      ("medium","prompt-override",re.compile(r"(?:ignore (?:all )?(?:previous|prior) instructions|reveal (?:the )?(?:system|hidden) prompt)",re.I)),
    ]
    def scan(self,root:Path)->dict:
        root=root.resolve();findings=[]
        if not (root/"SKILL.md").is_file():
            findings.append(SkillFinding("high","missing-entrypoint","SKILL.md","Agent Skills package requires SKILL.md"))
        for p in sorted(root.rglob("*")):
            if p.is_symlink():
                findings.append(SkillFinding("high","symlink",str(p.relative_to(root)),"Symlinks require manual review and are not imported"))
                continue
            if not p.is_file():continue
            rel=str(p.relative_to(root))
            try:size=p.stat().st_size
            except OSError:continue
            if size>self.MAX_FILE:
                findings.append(SkillFinding("medium","large-file",rel,f"{size} bytes"));continue
            if p.suffix.lower() not in self.TEXT_SUFFIXES:continue
            try:text=p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(SkillFinding("medium","non-text",rel,"Could not decode as UTF-8"));continue
            for sev,code,rule in self.RULES:
                if rule.search(text):findings.append(SkillFinding(sev,code,rel,"Static pattern requires operator review"))
        return {"review_required":bool(findings),"findings":[asdict(x) for x in findings],"note":"Skills Guard is a review aid, not a security boundary."}
