from __future__ import annotations
import os,platform,shutil,socket,sqlite3,sys
from pathlib import Path

class Doctor:
    def __init__(self,settings,provider_store=None):self.s=settings;self.providers=provider_store
    def run(self,check_port=True):
        checks=[]
        def add(code,label,ok,detail,fix=None,severity='error'):checks.append({'code':code,'label':label,'ok':bool(ok),'severity':severity,'detail':detail,'fix':fix})
        add('PYTHON_VERSION','Python 3.11+',sys.version_info>=(3,11),platform.python_version(),'Install Python 3.11 or newer from python.org.')
        writable=os.access(self.s.data_dir,os.W_OK) if self.s.data_dir.exists() else os.access(self.s.data_dir.parent,os.W_OK)
        add('DATA_WRITABLE','Data directory writable',writable,str(self.s.data_dir),'Grant your user write permission to the AIBA folder.')
        add('API_TOKEN','API security token',len(self.s.api_token)>=32,'Configured' if self.s.api_token else 'Missing','Run the installer again or `python setup_cli.py`.')
        add('MASTER_KEY','Credential encryption key',len(os.getenv('AIBA_MASTER_KEY',''))>=32,'Configured' if os.getenv('AIBA_MASTER_KEY') else 'Missing','Run the installer again or `python setup_cli.py`.')
        docker=shutil.which('docker');add('DOCKER','Docker sandbox',bool(docker),'Available' if docker else 'Not installed','Install Docker Desktop or Docker Engine to enable isolated code execution.',severity='warning')
        if self.s.sandbox_mode=='docker':add('DOCKER_REQUIRED','Configured Docker sandbox',bool(docker),'Ready' if docker else 'Docker mode cannot start','Install and start Docker, or set AIBA_SANDBOX_MODE=local.')
        try:
            with sqlite3.connect(self.s.providers_db_path) as c:c.execute('SELECT 1')
            db_ok=True;db_detail='Database opened successfully'
        except Exception as exc:db_ok=False;db_detail=str(exc)
        add('DATABASE','Provider database',db_ok,db_detail,'Check disk space and folder permissions.')
        count=len(self.providers.list_providers()) if self.providers else 0
        add('PROVIDER','AI provider connected',count>0,f'{count} provider connection(s)','Open Setup and connect OpenAI, Anthropic, Gemini, Ollama, or another provider.',severity='warning')
        if os.getenv('AIBA_TELEGRAM_ENABLED','false').lower() in {'1','true','yes','on'}:
            telegram_ok=bool(os.getenv('AIBA_TELEGRAM_BOT_TOKEN','').strip() and os.getenv('AIBA_TELEGRAM_ALLOWED_USERS','').strip())
            add('TELEGRAM','Telegram connector',telegram_ok,'Configured' if telegram_ok else 'Missing bot token or owner ID','Set AIBA_TELEGRAM_BOT_TOKEN and AIBA_TELEGRAM_ALLOWED_USERS.')
        if os.getenv('AIBA_WHATSAPP_ENABLED','false').lower() in {'1','true','yes','on'}:
            required=('AIBA_WHATSAPP_ACCESS_TOKEN','AIBA_WHATSAPP_PHONE_NUMBER_ID','AIBA_WHATSAPP_VERIFY_TOKEN','AIBA_WHATSAPP_APP_SECRET','AIBA_WHATSAPP_ALLOWED_NUMBERS')
            missing=[name for name in required if not os.getenv(name,'').strip()]
            add('WHATSAPP','WhatsApp connector',not missing,'Configured' if not missing else 'Missing: '+', '.join(missing),'Complete the official Meta WhatsApp Cloud API settings.')
        if check_port:
            port_ok=True
            try:
                sock=socket.socket();sock.bind((self.s.api_host,self.s.api_port));sock.close()
            except OSError as exc:port_ok=False;port_detail=str(exc)
            else:port_detail=f'{self.s.api_host}:{self.s.api_port} is available'
            add('PORT','Dashboard port',port_ok,port_detail,f'Close the process using port {self.s.api_port}, or change AIBA_API_PORT.',severity='warning')
        errors=sum(1 for x in checks if not x['ok'] and x['severity']=='error');warnings=sum(1 for x in checks if not x['ok'] and x['severity']=='warning')
        return {'ok':errors==0,'errors':errors,'warnings':warnings,'checks':checks,'system':{'platform':platform.platform(),'python':platform.python_version(),'executable':sys.executable}}
