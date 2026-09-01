from __future__ import annotations
import json,sqlite3,uuid
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from typing import Any
from sqlite_utils import connect as sqlite_connect
from .credentials import CredentialCipher

def now():return datetime.now(timezone.utc).isoformat()
PROVIDER_PRESETS={
 'openai':('OpenAI','https://api.openai.com/v1','OPENAI_API_KEY'),
 'anthropic':('Anthropic','https://api.anthropic.com','ANTHROPIC_API_KEY'),
 'google':('Google Gemini','https://generativelanguage.googleapis.com/v1beta/openai','GEMINI_API_KEY'),
 'xai':('xAI','https://api.x.ai/v1','XAI_API_KEY'),
 'openrouter':('OpenRouter','https://openrouter.ai/api/v1','OPENROUTER_API_KEY'),
 'groq':('Groq','https://api.groq.com/openai/v1','GROQ_API_KEY'),
 'mistral':('Mistral','https://api.mistral.ai/v1','MISTRAL_API_KEY'),
 'deepseek':('DeepSeek','https://api.deepseek.com/v1','DEEPSEEK_API_KEY'),
 'together':('Together AI','https://api.together.xyz/v1','TOGETHER_API_KEY'),
 'perplexity':('Perplexity','https://api.perplexity.ai','PERPLEXITY_API_KEY'),
 'azure_openai':('Azure OpenAI','', 'AZURE_OPENAI_API_KEY'),
 'aws_bedrock':('AWS Bedrock','', 'AWS_ACCESS_KEY_ID'),
 'ollama':('Ollama','http://localhost:11434',''),
 'lmstudio':('LM Studio','http://localhost:1234/v1',''),
 'custom':('Custom OpenAI-compatible','', ''),
}

class ProviderStore:
    def __init__(self,path:Path,cipher:CredentialCipher|None=None):
        self.path=path;path.parent.mkdir(parents=True,exist_ok=True);self.cipher=cipher or CredentialCipher();self._init()
    @contextmanager
    def connect(self):
        with sqlite_connect(self.path,timeout=15) as c:
            c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');yield c
    def _init(self):
        with self.connect() as c:c.executescript('''
        CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,base_url TEXT,api_key_encrypted TEXT,api_key_env TEXT,enabled INTEGER NOT NULL DEFAULT 1,priority INTEGER NOT NULL DEFAULT 100,config TEXT NOT NULL DEFAULT '{}',health TEXT NOT NULL DEFAULT 'unknown',failure_count INTEGER NOT NULL DEFAULT 0,last_checked_at TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY,provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,model_id TEXT NOT NULL,display_name TEXT NOT NULL,capabilities TEXT NOT NULL,context_window INTEGER,price_input REAL NOT NULL DEFAULT 0,price_output REAL NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,priority INTEGER NOT NULL DEFAULT 100,metadata TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(provider_id,model_id));
        CREATE TABLE IF NOT EXISTS routing_rules(id TEXT PRIMARY KEY,task_type TEXT NOT NULL UNIQUE,strategy TEXT NOT NULL DEFAULT 'balanced',required_capabilities TEXT NOT NULL DEFAULT '[]',preferred_models TEXT NOT NULL DEFAULT '[]',max_cost_per_million REAL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_usage(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT,task_type TEXT,provider_id TEXT,model_id TEXT,status TEXT NOT NULL,input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,estimated_cost REAL NOT NULL DEFAULT 0,latency_ms INTEGER NOT NULL DEFAULT 0,error TEXT,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_models_route ON models(enabled,priority);CREATE INDEX IF NOT EXISTS idx_usage_time ON model_usage(created_at);
        ''')
    def presets(self):return [{'kind':k,'name':v[0],'default_base_url':v[1],'api_key_env':v[2]} for k,v in PROVIDER_PRESETS.items()]
    def add_provider(self,name:str,kind:str,base_url:str|None=None,api_key:str|None=None,api_key_env:str|None=None,enabled=True,priority=100,config=None)->str:
        if kind not in PROVIDER_PRESETS:raise ValueError(f'Unsupported provider kind: {kind}')
        i=str(uuid.uuid4());t=now();preset=PROVIDER_PRESETS[kind];enc=self.cipher.encrypt(api_key) if api_key else None
        with self.connect() as c:c.execute('INSERT INTO providers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(i,name.strip() or preset[0],kind,base_url if base_url is not None else preset[1],enc,api_key_env if api_key_env is not None else preset[2],int(enabled),int(priority),json.dumps(config or {}),'unknown',0,None,None,t,t))
        return i
    def update_provider(self,i:str,**changes):
        allowed={'name','base_url','api_key_env','enabled','priority','config'};sets=[];values=[]
        if 'api_key' in changes:
            api_key=changes.pop('api_key');sets.append('api_key_encrypted=?');values.append(self.cipher.encrypt(api_key) if api_key else None)
        for k,v in changes.items():
            if k not in allowed:raise ValueError(f'Unsupported field: {k}')
            sets.append(k+'=?');values.append(json.dumps(v) if k=='config' else int(v) if k=='enabled' else v)
        if not sets:return
        sets.append('updated_at=?');values.extend([now(),i])
        with self.connect() as c:
            if c.execute(f"UPDATE providers SET {','.join(sets)} WHERE id=?",values).rowcount!=1:raise KeyError(i)
    def delete_provider(self,i:str):
        with self.connect() as c:
            if c.execute('DELETE FROM providers WHERE id=?',(i,)).rowcount!=1:raise KeyError(i)
    def list_providers(self,include_secret=False):
        with self.connect() as c:rows=[dict(x) for x in c.execute('SELECT * FROM providers ORDER BY priority,name')]
        for r in rows:
            r['enabled']=bool(r['enabled']);r['config']=json.loads(r['config']);r['has_api_key']=bool(r.pop('api_key_encrypted'))
            if include_secret:r['api_key']=self.get_key(r['id'])
        return rows
    def get_provider(self,i:str,include_secret=False):
        with self.connect() as c:r=c.execute('SELECT * FROM providers WHERE id=?',(i,)).fetchone()
        if not r:raise KeyError(i)
        d=dict(r);d['config']=json.loads(d['config']);d['enabled']=bool(d['enabled']);encrypted=d.pop('api_key_encrypted');d['has_api_key']=bool(encrypted)
        if include_secret:d['api_key']=self.cipher.decrypt(encrypted) if encrypted else None
        return d
    def get_key(self,i:str):
        p=self.get_provider(i,True);import os
        return p.get('api_key') or (os.getenv(p['api_key_env']) if p.get('api_key_env') else None)
    def add_model(self,provider_id:str,model_id:str,display_name:str|None=None,capabilities=None,context_window=None,price_input=0,price_output=0,enabled=True,priority=100,metadata=None)->str:
        self.get_provider(provider_id);i=str(uuid.uuid4());t=now();caps=sorted(set(capabilities or ['text','tools']))
        with self.connect() as c:c.execute('INSERT INTO models VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(i,provider_id,model_id,display_name or model_id,json.dumps(caps),context_window,float(price_input),float(price_output),int(enabled),int(priority),json.dumps(metadata or {}),t,t))
        return i
    def update_model(self,i:str,**changes):
        allowed={'model_id','display_name','capabilities','context_window','price_input','price_output','enabled','priority','metadata'};sets=[];values=[]
        for k,v in changes.items():
            if k not in allowed:raise ValueError(f'Unsupported field: {k}')
            sets.append(k+'=?');values.append(json.dumps(v) if k in {'capabilities','metadata'} else int(v) if k=='enabled' else v)
        if not sets:return
        sets.append('updated_at=?');values.extend([now(),i])
        with self.connect() as c:
            if c.execute(f"UPDATE models SET {','.join(sets)} WHERE id=?",values).rowcount!=1:raise KeyError(i)
    def delete_model(self,i:str):
        with self.connect() as c:
            if c.execute('DELETE FROM models WHERE id=?',(i,)).rowcount!=1:raise KeyError(i)
    def list_models(self,enabled_only=False):
        q='SELECT m.*,p.name provider_name,p.kind provider_kind,p.base_url,p.health provider_health,p.priority provider_priority FROM models m JOIN providers p ON p.id=m.provider_id'
        if enabled_only:q+=' WHERE m.enabled=1 AND p.enabled=1'
        q+=' ORDER BY m.priority,p.priority,m.display_name'
        with self.connect() as c:rows=[dict(x) for x in c.execute(q)]
        for r in rows:r['enabled']=bool(r['enabled']);r['capabilities']=json.loads(r['capabilities']);r['metadata']=json.loads(r['metadata'])
        return rows
    def set_rule(self,task_type:str,strategy='balanced',required_capabilities=None,preferred_models=None,max_cost_per_million=None):
        if strategy not in {'quality','balanced','cost','latency','manual'}:raise ValueError('Invalid routing strategy')
        t=now()
        with self.connect() as c:c.execute('INSERT INTO routing_rules VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(task_type) DO UPDATE SET strategy=excluded.strategy,required_capabilities=excluded.required_capabilities,preferred_models=excluded.preferred_models,max_cost_per_million=excluded.max_cost_per_million,updated_at=excluded.updated_at',(str(uuid.uuid4()),task_type,strategy,json.dumps(required_capabilities or []),json.dumps(preferred_models or []),max_cost_per_million,t,t))
    def list_rules(self):
        with self.connect() as c:rows=[dict(x) for x in c.execute('SELECT * FROM routing_rules ORDER BY task_type')]
        for r in rows:r['required_capabilities']=json.loads(r['required_capabilities']);r['preferred_models']=json.loads(r['preferred_models'])
        return rows
    def get_rule(self,task_type):
        with self.connect() as c:r=c.execute('SELECT * FROM routing_rules WHERE task_type=?',(task_type,)).fetchone() or c.execute("SELECT * FROM routing_rules WHERE task_type='default'").fetchone()
        if not r:return {'task_type':task_type,'strategy':'balanced','required_capabilities':['text','tools'],'preferred_models':[],'max_cost_per_million':None}
        d=dict(r);d['required_capabilities']=json.loads(d['required_capabilities']);d['preferred_models']=json.loads(d['preferred_models']);return d
    def health(self,provider_id,ok,error=None):
        with self.connect() as c:
            row=c.execute('SELECT failure_count FROM providers WHERE id=?',(provider_id,)).fetchone();failures=0 if ok else (row[0]+1 if row else 1);state='healthy' if ok else ('degraded' if failures<3 else 'unhealthy')
            c.execute('UPDATE providers SET health=?,failure_count=?,last_checked_at=?,last_error=?,updated_at=? WHERE id=?',(state,failures,now(),None if ok else str(error)[:1000],now(),provider_id))
    def record_usage(self,**data):
        fields=('request_id','task_type','provider_id','model_id','status','input_tokens','output_tokens','estimated_cost','latency_ms','error','created_at');values=[data.get(x) for x in fields[:-1]]+[now()]
        with self.connect() as c:c.execute(f"INSERT INTO model_usage({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",values)
    def usage_summary(self,days=30):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat()
        with self.connect() as c:
            totals=dict(c.execute("SELECT count(*) requests,coalesce(sum(input_tokens),0) input_tokens,coalesce(sum(output_tokens),0) output_tokens,coalesce(sum(estimated_cost),0) estimated_cost,coalesce(avg(latency_ms),0) avg_latency_ms FROM model_usage WHERE created_at>=?",(cutoff,)).fetchone())
            by_model=[dict(x) for x in c.execute("SELECT provider_id,model_id,count(*) requests,coalesce(sum(estimated_cost),0) estimated_cost,coalesce(avg(latency_ms),0) avg_latency_ms FROM model_usage WHERE created_at>=? GROUP BY provider_id,model_id ORDER BY requests DESC",(cutoff,))]
        return {'days':days,'totals':totals,'by_model':by_model}
    def performance(self):
        with self.connect() as c:return {(r['provider_id'],r['model_id']):dict(r) for r in c.execute("SELECT provider_id,model_id,avg(latency_ms) avg_latency_ms,avg(CASE WHEN status='success' THEN 1.0 ELSE 0 END) success_rate FROM model_usage GROUP BY provider_id,model_id")}
