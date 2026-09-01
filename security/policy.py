from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool; requires_approval: bool=False; reason: str=''

class SecurityPolicy:
    def __init__(self, workspace: Path, permissions_path: Path, require_approval: bool=True):
        self.workspace=workspace.resolve(); self.require_approval=require_approval
        raw=json.loads(permissions_path.read_text(encoding='utf-8'))
        if raw.get('version') != 1 or not isinstance(raw.get('tools'),dict): raise ValueError('Invalid permissions schema')
        self.config=raw
    def check_path(self,path: Path)->PolicyDecision:
        try:path.resolve().relative_to(self.workspace)
        except ValueError:return PolicyDecision(False,reason='Path is outside the AIBA workspace')
        return PolicyDecision(True)
    def check_command(self,command: str)->PolicyDecision:
        low=command.lower()
        if any(x.lower() in low for x in self.config.get('blocked_command_fragments',[])):
            return PolicyDecision(False,reason='Command blocked by security policy')
        return PolicyDecision(True,self.require_approval,'Command execution can modify the workspace')
    def check_tool(self,name: str)->PolicyDecision:
        cfg=self.config['tools'].get(name)
        if not cfg or not cfg.get('enabled',False): return PolicyDecision(False,reason=f'Tool disabled: {name}')
        return PolicyDecision(True,self.require_approval and bool(cfg.get('requires_approval',True)),'Sensitive tool')
