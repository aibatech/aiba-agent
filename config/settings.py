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
    # --- Media / docs extraction (Phase 8 / v1.6) ---
    # Opt-in document/text extraction. Works only when the optional `media`
    # extra (pypdf/python-docx/openpyxl/python-pptx) is installed; otherwise it
    # is still advertised but reports an "install optional support" diagnostic.
    # Read-only extraction defaults ON (low-risk); the operator may set
    # AIBA_MEDIA_ENABLED=false to hide these tools entirely.
    media_enabled:bool=True
    # --- MCP client (Phase 7 / v1.6) ---
    # Disabled by default. Each MCP server additionally requires the optional
    # `mcp` extra (the client SDK), an explicit entry in config/mcp_servers.json
    # (enabled:true) and per-tool policy allowlist; stdio servers run as
    # external child processes. Remote (http) transports are gated behind the
    # AIBA_MCP_REMOTE feature flag and security.urlguard.
    mcp_enabled:bool=False
    # --- Memory ownership (v1.6 Gap 2 hardening) ---
    # The explicitly-authorized single-owner/admin identity keys. Authorized
    # owners (plus the unnamed 'default' operator used by API/CLI/queued work)
    # get the unscoped admin memory view; ANY other authenticated identity is
    # scoped strictly to its own rows and never sees 'shared'/legacy records.
    # Explicit administrative grant, separate from permission to chat with a
    # connector. Adding a second allowed chat user must NEVER grant vault admin.
    memory_owner_users: frozenset[str] = frozenset({'default'})
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
            None,_bool('AIBA_MEDIA_ENABLED',True),
            _bool('AIBA_MCP_ENABLED',False),
            cls._owner_users_from_env(),
            )
        for d in (s.data_dir,s.workspace_dir,s.vault_dir,s.logs_dir,s.skills_dir):d.mkdir(parents=True,exist_ok=True)
        return s

    @staticmethod
    def _owner_users_from_env() -> frozenset[str]:
        """Explicit owner keys only; connector allowlists are not admin grants.

        CLI and the bearer-token management API retain the local 'default'
        operator. Remote owners must be explicitly named in
        AIBA_MEMORY_OWNER_USERS using their connector-qualified identity.
        """
        owners = {'default'}
        for raw in os.getenv('AIBA_MEMORY_OWNER_USERS', '').split(','):
            key = raw.strip()
            if not key:
                continue
            if key != 'default':
                channel, sep, ident = key.partition(':')
                if not sep or channel not in {'telegram', 'whatsapp'} or not ident.isascii() or not ident.isdigit():
                    raise SettingsError('AIBA_MEMORY_OWNER_USERS requires connector-qualified numeric identities')
            owners.add(key)
        return frozenset(owners)
