from __future__ import annotations
import shutil,subprocess,sys
from pathlib import Path
from .base import ToolResult
class Sandbox:
    def __init__(self,workspace:Path,timeout:int,policy,mode='local',docker_image='python:3.12-slim',memory='512m',cpus='1.0',network=False):
        self.workspace=workspace.resolve(); self.workspace.mkdir(parents=True,exist_ok=True); self.timeout=timeout; self.policy=policy
        self.mode=mode; self.image=docker_image; self.memory=memory; self.cpus=cpus; self.network=network
        if mode=='docker' and not shutil.which('docker'): raise RuntimeError('Docker sandbox requested but docker is unavailable')
    def _safe(self,relative_path:str)->Path:
        p=(self.workspace/relative_path).resolve(); d=self.policy.check_path(p)
        if not d.allowed: raise PermissionError(d.reason)
        return p
    def resolve(self,path:str)->Path:return self._safe(path)
    def list_files(self,path:str='.') -> ToolResult:
        p=self._safe(path)
        if not p.exists():return ToolResult(False,error='Path does not exist')
        return ToolResult(True,[str(x.relative_to(self.workspace)) for x in sorted(p.rglob('*')) if x.is_file()])
    def read_file(self,path:str)->ToolResult:
        p=self._safe(path)
        if not p.is_file():return ToolResult(False,error='File not found')
        return ToolResult(True,p.read_text(encoding='utf-8',errors='replace'))
    def write_file(self,path:str,content:str)->ToolResult:
        p=self._safe(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content,encoding='utf-8')
        return ToolResult(True,{'path':str(p.relative_to(self.workspace)),'bytes':len(content.encode())})
    def delete_file(self,path:str)->ToolResult:
        p=self._safe(path)
        if not p.is_file():return ToolResult(False,error='File not found or directory deletion disabled')
        p.unlink(); return ToolResult(True,{'deleted':path})
    def _run(self,command:str)->ToolResult:
        d=self.policy.check_command(command)
        if not d.allowed:return ToolResult(False,error=d.reason)
        if self.mode=='docker':
            cmd=['docker','run','--rm','-v',f'{self.workspace}:/workspace','-w','/workspace','--memory',self.memory,'--cpus',self.cpus]
            if not self.network:cmd += ['--network','none']
            cmd += [self.image,'sh','-lc',command]
            cp=subprocess.run(cmd,text=True,capture_output=True,timeout=self.timeout)
        else:return ToolResult(False,error='Shell execution requires AIBA_SANDBOX_MODE=docker')
        return ToolResult(cp.returncode==0,{'returncode':cp.returncode,'stdout':cp.stdout[-12000:],'stderr':cp.stderr[-12000:]},None if cp.returncode==0 else 'Command failed')
    def run_shell(self,command:str)->ToolResult:return self._run(command)
    def run_python(self, code: str) -> ToolResult:
        if self.mode == "docker":
            return self._run("python -c " + repr(code))
        return ToolResult(False,error='Python execution requires AIBA_SANDBOX_MODE=docker')
