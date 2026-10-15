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
                if source.is_symlink():raise BackupError('Database symlinks are forbidden')
                if source.name == 'approvals.db':continue  # grants must never be resurrected by a restore
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
            name=item['name']
            if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or name in {'.','..','approvals.db'}:
                raise BackupError('Unsafe backup entry')
            path=folder/name
            if path.is_symlink() or (self.data_dir/name).is_symlink():raise BackupError('Backup symlinks are forbidden')
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
            source=folder/item['name'];target=self.data_dir/item['name']
            fd, temporary = tempfile.mkstemp(prefix='.restore-', dir=self.data_dir)
            try:
                with os.fdopen(fd,'wb') as output, source.open('rb') as input_file:
                    shutil.copyfileobj(input_file, output)
                    output.flush();os.fsync(output.fileno())
                os.replace(temporary,target)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        approval_db=self.data_dir/'approvals.db'
        if approval_db.exists():
            with connect(approval_db) as db:db.execute('DELETE FROM approval_challenges')
        return {'restored':True,'backup_id':backup_id,'safety_backup_id':safety['backup_id']}
    def list(self):
        result=[]
        for path in sorted(self.root.iterdir(),reverse=True) if self.root.exists() else []:
            try:result.append(json.loads((path/'manifest.json').read_text()))
            except Exception:continue
        return result
    def _folder(self,backup_id):
        if not backup_id or Path(backup_id).name!=backup_id:raise BackupError('Invalid backup id')
        if '/' in backup_id or '\\' in backup_id or backup_id in {'.','..'}:raise BackupError('Invalid backup id')
        folder=self.root/backup_id
        if folder.is_symlink():raise BackupError('Backup symlinks are forbidden')
        if not folder.is_dir():raise BackupError('Backup not found')
        return folder
