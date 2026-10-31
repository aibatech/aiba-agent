"""Verified full-profile snapshots. Restore is an explicitly offline operation."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from sqlite_utils import connect
from operations.maintenance import ProfileLeases, LOCK_NAME, PENDING_RESTORE


class BackupError(RuntimeError):pass


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):h.update(chunk)
    return h.hexdigest()


class BackupManager:
    def __init__(self,data_dir:Path,skills_dir:Path|None=None):
        self.data_dir=data_dir.resolve();self.skills_dir=skills_dir.resolve() if skills_dir else None
        self.root=self.data_dir/'backups';self.root.mkdir(parents=True,exist_ok=True)

    def _sources(self):
        for path in sorted(self.data_dir.rglob('*')):
            rel=path.relative_to(self.data_dir)
            if rel.parts[0]=='backups' or path.name in {'approvals.db','privacy-erasure.json','privacy-deletions.db',LOCK_NAME,PENDING_RESTORE} or path.name.endswith(('-wal','-shm')):continue
            if path.is_symlink():raise BackupError('Profile symlinks cannot be backed up')
            if path.is_file():yield 'data/'+rel.as_posix(),path
        if self.skills_dir:
            for folder in sorted(self.skills_dir.iterdir()):
                if folder.is_symlink():raise BackupError('Skill symlinks cannot be backed up')
                if folder.is_dir() and ((folder/'skill.json').is_file() or (folder/'SKILL.md').is_file()):
                    for path in sorted(folder.rglob('*')):
                        if path.is_symlink():raise BackupError('Skill symlinks cannot be backed up')
                        if path.is_file():yield 'skills/'+path.relative_to(self.skills_dir).as_posix(),path

    def create(self,label=None):
        with ProfileLeases(self.data_dir,self.skills_dir):return self._create(label)

    def _create(self,label=None):
        if (self.data_dir/PENDING_RESTORE).exists():raise BackupError("Recover the interrupted restore before creating another backup")
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');bid=f'{stamp}-{uuid.uuid4().hex[:8]}'
        with tempfile.TemporaryDirectory(prefix='aiba-backup-',dir=self.root) as temp:
            stage=Path(temp);files=[]
            for name,source in self._sources():
                target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                if source.suffix=='.db':
                    with connect(source) as src,connect(target) as dst:src.backup(dst)
                    with connect(target) as db:
                        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise BackupError('Database integrity failed')
                else:shutil.copy2(source,target)
                files.append({'name':name,'sha256':digest(target),'bytes':target.stat().st_size})
            manifest={'format':2,'backup_id':bid,'created_at':datetime.now(timezone.utc).isoformat(),'label':label,'files':files}
            (stage/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            os.replace(stage,self.root/bid)
        return manifest

    def _target(self,name,version):
        if not isinstance(name,str) or '\\' in name or ':' in name:raise BackupError('Unsafe backup entry')
        parts=PurePosixPath(name).parts
        if not parts or name.startswith('/') or any(x in {'.','..'} for x in name.split('/')):raise BackupError('Unsafe backup entry')
        if version==1:
            if len(parts)!=1 or (not name.endswith('.db') and name!='setup.json'):raise BackupError('Invalid legacy entry')
            root=self.data_dir;relative=parts
        elif version==2:
            if len(parts)<2:raise BackupError('Invalid backup entry')
            if parts[0]=='data':root=self.data_dir
            elif parts[0]=='skills' and self.skills_dir is not None:root=self.skills_dir
            else:raise BackupError('Unknown or unconfigured backup root')
            relative=parts[1:]
            if parts[0]=='skills' and len(relative)<2:raise BackupError('Only installed skill directories may be restored')
        else:raise BackupError('Unsupported backup format')
        if relative[0]=='backups' or relative[-1] in {'approvals.db','privacy-erasure.json','privacy-deletions.db',LOCK_NAME,PENDING_RESTORE} or relative[-1].endswith(('-wal','-shm')):raise BackupError('Forbidden restore entry')
        target=root.joinpath(*relative)
        for node in (target,*target.parents):
            if node==root.parent:break
            if node.is_symlink():raise BackupError('Restore symlinks are forbidden')
        target.resolve().relative_to(root.resolve())
        return target

    def _manifest(self,bid):
        folder=self._folder(bid);path=folder/'manifest.json'
        if path.is_symlink():raise BackupError('Manifest symlinks are forbidden')
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data.get('files'),list):raise BackupError('Invalid backup manifest')
        return folder,data

    def verify(self,bid):
        folder,manifest=self._manifest(bid);seen=set()
        for item in manifest['files']:
            name=item['name'];target=self._target(name,manifest.get('format'))
            if str(target) in seen:raise BackupError('Duplicate restore target')
            seen.add(str(target));path=folder/name
            for node in (path,*path.parents):
                if node==folder.parent:break
                if node.is_symlink():raise BackupError('Backup symlinks are forbidden')
            if not path.is_file() or digest(path)!=item['sha256']:raise BackupError(f'Backup verification failed: {name}')
            if path.suffix=='.db':
                with connect(path) as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise BackupError('Database is corrupt')
        return {'verified':True,'backup_id':bid,'files':len(seen)}

    def restore(self,bid,confirm):
        with ProfileLeases(self.data_dir,self.skills_dir):return self._restore(bid,confirm)

    def _restore(self,bid,confirm):
        if confirm!=bid:raise BackupError('Restore confirmation must exactly match backup_id')
        self.verify(bid);folder,manifest=self._manifest(bid)
        pending=self.data_dir/PENDING_RESTORE
        if pending.is_symlink():raise BackupError('Unsafe restore marker')
        was_pending=pending.exists()
        safety={'backup_id':None} if was_pending else self._create('automatic pre-restore safety backup')
        # Stage every replacement before changing live files. Roll back any
        # replacements if an OS error interrupts the commit. Stop all writers first.
        staged=[];committed=[]
        with tempfile.TemporaryDirectory(prefix='aiba-restore-',dir=self.root) as tmp:
            stage=Path(tmp)
            for index,item in enumerate(manifest['files']):
                target=self._target(item['name'],manifest['format']);source=folder/item['name']
                replacement=stage/f'{index}.new';old=stage/f'{index}.old'
                shutil.copy2(source,replacement)
                if digest(replacement)!=item['sha256']:raise BackupError('Backup changed during staging')
                existed=target.exists()
                if existed:shutil.copy2(target,old)
                staged.append((target,replacement,old,existed))
            with pending.open('w',encoding='utf-8') as marker:
                marker.write(bid);marker.flush();os.fsync(marker.fileno())
            try:
                for entry in staged:
                    target,replacement,old,existed=entry
                    target.parent.mkdir(parents=True,exist_ok=True)
                    # Different configured roots can be on different filesystems.
                    fd,temp=tempfile.mkstemp(prefix='.aiba-restore-',dir=target.parent)
                    try:
                        with os.fdopen(fd,'wb') as output,replacement.open('rb') as source:
                            shutil.copyfileobj(source,output);output.flush();os.fsync(output.fileno())
                        os.replace(temp,target)
                    finally:
                        if os.path.exists(temp):os.unlink(temp)
                    committed.append(entry)
            except Exception:
                for target,replacement,old,existed in reversed(committed):
                    if existed:shutil.copy2(old,target)
                    else:target.unlink(missing_ok=True)
                if not was_pending:pending.unlink(missing_ok=True)
                raise
        approval_db=self.data_dir/'approvals.db'
        if approval_db.exists():
            with connect(approval_db) as db:db.execute('DELETE FROM approval_challenges')
        from privacy.erasure import OwnerErasure
        OwnerErasure(self.data_dir).enforce_after_restore()
        from privacy.memory_deletions import enforce
        enforce(self.data_dir)
        pending.unlink(missing_ok=True)
        return {'restored':True,'backup_id':bid,'safety_backup_id':safety['backup_id']}

    def list(self):
        result=[]
        for path in sorted(self.root.iterdir(),reverse=True):
            try:result.append(self._manifest(path.name)[1])
            except (OSError,ValueError,BackupError):continue
        return result

    def _folder(self,bid):
        if not isinstance(bid,str) or not bid or '/' in bid or '\\' in bid or ':' in bid or bid in {'.','..'}:raise BackupError('Invalid backup id')
        folder=self.root/bid
        if folder.is_symlink() or not folder.is_dir():raise BackupError('Backup not found or unsafe')
        return folder
