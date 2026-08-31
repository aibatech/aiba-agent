from __future__ import annotations
import json,os,secrets,stat
from datetime import datetime,timezone
from pathlib import Path
from config.env import load_env,quote_env

def now():return datetime.now(timezone.utc).isoformat()

class SetupManager:
    def __init__(self,root:Path,data_dir:Path):self.root=root;self.data_dir=data_dir;self.state_path=data_dir/'setup.json';self.env_path=root/'.env'
    def ensure_configuration(self)->dict:
        load_env(self.env_path)
        generated={}
        for name in ('AIBA_API_TOKEN','AIBA_MASTER_KEY'):
            if not os.getenv(name):generated[name]=secrets.token_urlsafe(48);os.environ[name]=generated[name]
        if generated:self._merge_env(generated)
        self.data_dir.mkdir(parents=True,exist_ok=True)
        return {'generated':list(generated),'api_token':os.environ['AIBA_API_TOKEN']}
    def _merge_env(self,changes:dict[str,str]):
        existing={};order=[]
        if self.env_path.exists():
            for line in self.env_path.read_text(encoding='utf-8').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key=line.split('=',1)[0].strip();existing[key]=line;order.append(key)
        for k,v in changes.items():existing[k]=f'{k}={quote_env(v)}';order.append(k) if k not in order else None
        defaults={'AIBA_API_HOST':'127.0.0.1','AIBA_API_PORT':'8765','AIBA_PROVIDER':'local','AIBA_FALLBACK_PROVIDER':'local','AIBA_WORKER_ENABLED':'true','AIBA_REQUIRE_APPROVAL':'true'}
        for k,v in defaults.items():
            if k not in existing:existing[k]=f'{k}={v}';order.append(k)
        self.env_path.write_text('\n'.join(existing[k] for k in order)+'\n',encoding='utf-8')
        try:self.env_path.chmod(stat.S_IRUSR|stat.S_IWUSR)
        except OSError:pass
    def status(self,provider_count=0)->dict:
        state={}
        if self.state_path.is_file():
            try:state=json.loads(self.state_path.read_text(encoding='utf-8'))
            except Exception:state={}
        return {'complete':bool(state.get('complete')),'completed_at':state.get('completed_at'),'has_provider':provider_count>0,'version':state.get('version',1)}
    def complete(self):
        self.data_dir.mkdir(parents=True,exist_ok=True);payload={'complete':True,'completed_at':now(),'version':1};self.state_path.write_text(json.dumps(payload,indent=2),encoding='utf-8');return payload
