from __future__ import annotations
import hashlib,json,os,re,shutil,tempfile,threading,urllib.request,zipfile
from pathlib import Path
from urllib.parse import urlparse

VERSION_RE=re.compile(r'^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$')
def version_tuple(value):return tuple(int(x) for x in value.split('-',1)[0].split('.')[:3])

class UpdateError(RuntimeError):pass
class UpdateManager:
    def __init__(self,root:Path,data_dir:Path):self.root=root;self.dir=data_dir/'updates';self.dir.mkdir(parents=True,exist_ok=True);self.manifest_url=os.getenv('AIBA_UPDATE_MANIFEST_URL','').strip();self.state_path=self.dir/'state.json'
    @property
    def current_version(self):return (self.root/'VERSION').read_text().strip()
    def status(self):
        state={}
        if self.state_path.is_file():
            try:state=json.loads(self.state_path.read_text())
            except Exception:state={}
        return {'current_version':self.current_version,'configured':bool(self.manifest_url),**state}
    def check(self):
        if not self.manifest_url:return {'available':False,'reason':'AIBA_UPDATE_MANIFEST_URL is not configured','current_version':self.current_version}
        if urlparse(self.manifest_url).scheme!='https':raise UpdateError('Update manifest must use HTTPS')
        try:
            with urllib.request.urlopen(self.manifest_url,timeout=20) as r:manifest=json.loads(r.read())
        except Exception as exc:raise UpdateError(f'Update check failed: {exc}') from exc
        for field in ('version','url','sha256'):
            if not manifest.get(field):raise UpdateError(f'Update manifest is missing {field}')
        if not VERSION_RE.fullmatch(manifest['version']):raise UpdateError('Update manifest version is invalid')
        if urlparse(manifest['url']).scheme!='https':raise UpdateError('Update archive must use HTTPS')
        available=version_tuple(manifest['version'])>version_tuple(self.current_version);state={'available':available,'latest_version':manifest['version'],'manifest':manifest if available else None}
        self.state_path.write_text(json.dumps(state,indent=2),encoding='utf-8');return {'current_version':self.current_version,**state}
    def stage(self,manifest=None):
        manifest=manifest or self.check().get('manifest')
        if not manifest:return {'staged':False,'reason':'No update is available'}
        target=self.dir/f"aiba-{manifest['version']}.zip";digest=hashlib.sha256()
        try:
            with urllib.request.urlopen(manifest['url'],timeout=120) as r,target.open('wb') as out:
                while chunk:=r.read(1024*1024):digest.update(chunk);out.write(chunk)
        except Exception as exc:
            target.unlink(missing_ok=True);raise UpdateError(f'Update download failed: {exc}') from exc
        if digest.hexdigest().lower()!=manifest['sha256'].lower():target.unlink(missing_ok=True);raise UpdateError('Update checksum verification failed')
        self._validate_archive(target);state={'available':True,'latest_version':manifest['version'],'staged_version':manifest['version'],'staged_path':str(target),'sha256':digest.hexdigest()};self.state_path.write_text(json.dumps(state,indent=2));return {'staged':True,**state}
    def _validate_archive(self,path):
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                p=Path(info.filename)
                if p.is_absolute() or '..' in p.parts:raise UpdateError('Unsafe path in update archive')
                if (info.external_attr>>16)&0o170000==0o120000:raise UpdateError('Symlinks are not permitted in updates')
            names=[x for x in z.namelist() if x.endswith('/VERSION') or x=='VERSION']
            if not names:raise UpdateError('Update archive does not contain VERSION')
    def apply_staged(self):
        state=self.status();path=Path(state.get('staged_path',''))
        if not path.is_file():return {'applied':False,'reason':'No staged update'}
        self._validate_archive(path);version=state['staged_version'];backup=self.root/'agent_system'/'update-backups'/self.current_version
        with tempfile.TemporaryDirectory(prefix='aiba-update-') as tmp:
            with zipfile.ZipFile(path) as z:z.extractall(tmp)
            extracted=Path(tmp);children=[x for x in extracted.iterdir()]
            source=children[0] if len(children)==1 and children[0].is_dir() else extracted
            if not (source/'VERSION').is_file() or (source/'VERSION').read_text().strip()!=version:raise UpdateError('Staged update version does not match manifest')
            excludes={'.env','agent_system','.venv','.git','__pycache__'};backup.mkdir(parents=True,exist_ok=True)
            try:
                for item in self.root.iterdir():
                    if item.name in excludes or item==backup.parent:continue
                    destination=backup/item.name
                    if item.is_dir():shutil.copytree(item,destination,dirs_exist_ok=True)
                    elif item.is_file():shutil.copy2(item,destination)
                for item in source.iterdir():
                    if item.name in excludes:continue
                    destination=self.root/item.name
                    if item.is_dir():shutil.copytree(item,destination,dirs_exist_ok=True)
                    elif item.is_file():shutil.copy2(item,destination)
            except Exception as exc:raise UpdateError(f'Update apply failed; backup retained at {backup}: {exc}') from exc
        path.unlink(missing_ok=True);self.state_path.write_text(json.dumps({'available':False,'last_applied_version':version},indent=2));return {'applied':True,'version':version,'backup':str(backup)}

class UpdateChecker:
    def __init__(self,manager:UpdateManager,interval_seconds=None):self.manager=manager;self.interval=int(interval_seconds or os.getenv('AIBA_UPDATE_INTERVAL_SECONDS','86400'));self.stop_event=threading.Event();self.thread=None;self.last_error=None
    def run_once(self):
        try:
            result=self.manager.check()
            if result.get('available') and os.getenv('AIBA_AUTO_UPDATE','true').lower() in {'1','true','yes','on'}:result=self.manager.stage(result['manifest'])
            self.last_error=None;return result
        except Exception as exc:self.last_error=str(exc);return {'error':self.last_error}
    def start(self):
        if not self.manager.manifest_url:return self
        def loop():
            while not self.stop_event.is_set():self.run_once();self.stop_event.wait(self.interval)
        self.thread=threading.Thread(target=loop,daemon=True,name='aiba-updater');self.thread.start();return self
    def stop(self):self.stop_event.set();self.thread and self.thread.join(timeout=3)
