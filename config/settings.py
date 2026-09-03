from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from config.env import load_env
class SettingsError(ValueError):pass
def _bool(name,default):
    value=os.getenv(name,'1' if default else '0').strip().lower()
    if value in {'1','true','yes','on'}:return True
    if value in {'0','false','no','off'}:return False
    raise SettingsError(f'{name} must be boolean')
def _int(name,default,minimum=1):
    try:value=int(os.getenv(name,str(default)))
    except ValueError as exc:raise SettingsError(f'{name} must be integer') from exc
    if value<minimum:raise SettingsError(f'{name} must be >= {minimum}')
    return value
@dataclass(frozen=True)
class Settings:
    root_dir:Path;data_dir:Path;workspace_dir:Path;vault_dir:Path;logs_dir:Path;skills_dir:Path
    db_path:Path;tasks_db_path:Path;jobs_db_path:Path;schedules_db_path:Path;auth_db_path:Path;providers_db_path:Path
    provider:str;fallback_provider:str;model:str;fallback_model:str;max_steps:int;command_timeout:int
    require_approval:bool;sandbox_mode:str;docker_image:str;docker_memory:str;docker_cpus:str;sandbox_network:bool
    permissions_path:Path;browser_enabled:bool;desktop_enabled:bool;vision_model:str;worker_enabled:bool
    api_token:str;api_host:str;api_port:int;allowed_origins:tuple[str,...];rate_limit_per_minute:int
    web_enabled:bool;computer_node_path:Path;desktop_clipboard_enabled:bool;desktop_process_enabled:bool
    # --- Internal subagents (Phase 3 / v1.6) ---
    # Disabled by default. Concurrency/limits default conservatively. Each has a
    # dataclass default so existing positional/keyword constructions still work.
    subagents_enabled:bool=False
    subagents_db_path:Path|None=None
    subagent_global_concurrency:int=3
    subagent_per_parent_concurrency:int=2
    # --- Memory / sessions (Phase 9 / v1.6) ---
    # Append at END with defaults (positional-safe like Phase 3). When None,
    # the AgentLoop derives a default under data_dir.
    sessions_db_path:Path|None=None
    @classmethod
    def load(cls):
        root=Path(os.getenv('AIBA_ROOT',Path(__file__).resolve().parents[1])).resolve();load_env(root/'.env');data=Path(os.getenv('AIBA_DATA_DIR',root/'agent_system')).resolve()
        sandbox=os.getenv('AIBA_SANDBOX_MODE','local').lower()
        if sandbox not in {'local','docker'}:raise SettingsError('AIBA_SANDBOX_MODE must be local or docker')
        provider=os.getenv('AIBA_PROVIDER','local').lower(); fallback=os.getenv('AIBA_FALLBACK_PROVIDER','local').lower()
        supported={'local','openai','openai_compatible','anthropic','ollama'}
        if provider not in supported or fallback not in supported:raise SettingsError(f'Providers must be one of {sorted(supported)}')
        token=os.getenv('AIBA_API_TOKEN','').strip()
        origins=tuple(x.strip() for x in os.getenv('AIBA_ALLOWED_ORIGINS','').split(',') if x.strip())
        s=cls(root,data,data/'workspace',data/'vault',data/'logs',root/'skills',data/'aiba.db',data/'tasks.db',data/'jobs.db',data/'schedules.db',data/'auth.db',data/'providers.db',provider,fallback,os.getenv('AIBA_MODEL','gpt-4.1-mini'),os.getenv('AIBA_FALLBACK_MODEL','local-v1'),_int('AIBA_MAX_STEPS',20),_int('AIBA_COMMAND_TIMEOUT',30),_bool('AIBA_REQUIRE_APPROVAL',True),sandbox,os.getenv('AIBA_DOCKER_IMAGE','python:3.12-slim'),os.getenv('AIBA_DOCKER_MEMORY','512m'),os.getenv('AIBA_DOCKER_CPUS','1.0'),_bool('AIBA_SANDBOX_NETWORK',False),root/'config'/'permissions.json',_bool('AIBA_BROWSER_ENABLED',False),_bool('AIBA_DESKTOP_ENABLED',False),os.getenv('AIBA_VISION_MODEL','gpt-4.1-mini'),_bool('AIBA_WORKER_ENABLED',True),token,os.getenv('AIBA_API_HOST','127.0.0.1'),_int('AIBA_API_PORT',8765),origins,_int('AIBA_RATE_LIMIT_PER_MINUTE',60),_bool('AIBA_WEB_ENABLED',False),data/'computer_node.json',_bool('AIBA_DESKTOP_CLIPBOARD',False),_bool('AIBA_DESKTOP_PROCESS',False),
            _bool('AIBA_SUBAGENTS_ENABLED',False),data/'subagents.db',_int('AIBA_SUBAGENT_CONCURRENCY',3,minimum=1),_int('AIBA_SUBAGENT_PER_PARENT',2,minimum=1),
            )
        for d in (s.data_dir,s.workspace_dir,s.vault_dir,s.logs_dir,s.skills_dir):d.mkdir(parents=True,exist_ok=True)
        return s
