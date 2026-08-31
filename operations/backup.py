from __future__ import annotations
import hashlib,json,os,shutil,sqlite3,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from sqlite_utils import connect

class BackupError(RuntimeError):pass
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()

class BackupManager:
    def __init__(self,data_dir:Path):self.data_dir=data_dir;self.root=data_dir/'backups';self.root.mkdir(parents=True,exist_ok=True)
    def create(self,label=None):
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');backup_id=f'{stamp}-{uuid.uuid4().hex[:8]}';final=self.root/backup_id
        with tempfile.TemporaryDirectory(prefix='aiba-backup-',dir=self.root) as temp:
            stage=Path(temp);files=[]
            for source in sorted(self.data_dir.glob('*.db')):
                target=stage/source.name
                with connect(source) as src,connect(target) as dst:src.backup(dst)
                with connect(target) as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise BackupError(f'Integrity check failed for {source.name}')
                files.append({'name':source.name,'sha256':digest(target),'bytes':target.stat().st_size})
            for name in ('setup.json',):
                source=self.data_dir/name
                if source.is_file():shutil.copy2(source,stage/name);files.append({'name':name,'sha256':digest(stage/name),'bytes':(stage/name).stat().st_size})
            manifest={'format':1,'backup_id':backup_id,'created_at':datetime.now(timezone.utc).isoformat(),'label':label,'files':files}
            (stage/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');os.replace(stage,final)
        return manifest
    def verify(self,backup_id):
        folder=self._folder(backup_id);manifest=json.loads((folder/'manifest.json').read_text())
        for item in manifest['files']:
            path=folder/item['name']
            if not path.is_file() or digest(path)!=item['sha256']:raise BackupError(f"Backup verification failed: {item['name']}")
            if path.suffix=='.db':
                with connect(f'file:{path}?mode=ro',uri=True) as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise BackupError(f"Database is corrupt: {item['name']}")
        return {'verified':True,'backup_id':backup_id,'files':len(manifest['files'])}
    def restore(self,backup_id,confirm):
        if confirm!=backup_id:raise BackupError('Restore confirmation must exactly match backup_id')
        self.verify(backup_id);folder=self._folder(backup_id);safety=self.create('automatic pre-restore safety backup')
        manifest=json.loads((folder/'manifest.json').read_text())
        for item in manifest['files']:
            source=folder/item['name'];target=self.data_dir/item['name'];temporary=target.with_suffix(target.suffix+'.restore')
            shutil.copy2(source,temporary);os.replace(temporary,target)
        return {'restored':True,'backup_id':backup_id,'safety_backup_id':safety['backup_id']}
    def list(self):
        result=[]
        for path in sorted(self.root.iterdir(),reverse=True) if self.root.exists() else []:
            try:result.append(json.loads((path/'manifest.json').read_text()))
            except Exception:continue
        return result
    def _folder(self,backup_id):
        if not backup_id or Path(backup_id).name!=backup_id:raise BackupError('Invalid backup id')
        folder=self.root/backup_id
        if not folder.is_dir():raise BackupError('Backup not found')
        return folder
