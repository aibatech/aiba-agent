"""Resumable owner-scoped backup replacement; preserve other owners and manifests."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from operations.backup import BackupManager, digest
from operations.maintenance import PENDING_PRIVACY


def write_journal(root, value):
    fd, temporary = tempfile.mkstemp(prefix='.privacy-journal-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, root/PENDING_PRIVACY)
    finally:Path(temporary).unlink(missing_ok=True)


def read_journal(root):
    path=root/PENDING_PRIVACY
    if path.is_symlink():raise ValueError('Unsafe privacy journal')
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('backups'),list):raise ValueError('Invalid privacy journal')
    from privacy.erasure import OwnerErasure
    OwnerErasure._validate_owner(data.get('owner'))
    return data


def manager(root):
    # The skills root here is used only to validate backup names, never restore them.
    return BackupManager(root,root/'skills')


def inventory(root):
    service=manager(root);result=[]
    for folder in sorted(service.root.iterdir()):
        if folder.name.startswith('.'):continue
        source,manifest=service._manifest(folder.name)
        service._verify_folder(source,manifest,folder.name)
        result.append({'backup_id':folder.name,'manifest_sha256':digest(source/'manifest.json')})
    return result


def resume_backup(root):
    """Commit or finish cleanup for the already prepared, approved replacement."""
    journal=read_journal(root);transaction=journal.get('transaction')
    if not transaction:return
    service=manager(root)
    if not isinstance(transaction,str) or not transaction.startswith('.privacy-backup-') or Path(transaction).name!=transaction or '\\' in transaction or ':' in transaction:
        raise ValueError('Invalid backup transaction path')
    if not journal['backups']:raise ValueError('Missing pending backup identity')
    bid=journal['backups'][0]['backup_id']
    if not isinstance(bid,str) or Path(bid).name!=bid or bid.startswith('.') or ':' in bid or '\\' in bid:
        raise ValueError('Invalid backup identity')
    stage=service.root/transaction;new=stage/'new';old=stage/'old';target=service.root/bid
    if stage.is_symlink() or any(p.is_symlink() for p in (new,old,target)):raise ValueError('Unsafe backup transaction')
    candidate=new if new.exists() else target
    manifest=json.loads((candidate/'manifest.json').read_text())
    if digest(candidate/'manifest.json')!=journal.get('prepared_sha256'):raise ValueError('Prepared backup changed')
    service._verify_folder(candidate,manifest,bid)
    if new.exists():
        if target.exists():
            if old.exists():raise ValueError('Ambiguous backup transaction')
            os.replace(target,old)
        os.replace(new,target)
    # New snapshot is complete and verified before removing the private old copy.
    if old.exists():shutil.rmtree(old)
    journal['backups']=journal['backups'][1:]
    journal.pop('transaction',None);journal.pop('prepared_sha256',None)
    write_journal(root,journal)
    shutil.rmtree(stage)


def redact_next(root):
    journal=read_journal(root)
    if journal.get('building'):
        building=journal['building']
        if not isinstance(building,str) or not building.startswith('.privacy-backup-') or Path(building).name!=building or '\\' in building or ':' in building:
            raise ValueError('Invalid pending backup staging path')
        stage=manager(root).root/building
        if stage.is_symlink():raise ValueError('Unsafe staging path')
        if stage.exists():shutil.rmtree(stage)
        journal.pop('building');write_journal(root,journal)
        return
    if journal.get('transaction'):
        resume_backup(root);return
    backup=journal['backups'][0];bid=backup['backup_id'];service=manager(root)
    source,manifest=service._manifest(bid)
    if digest(source/'manifest.json')!=backup['manifest_sha256']:raise ValueError('Backup changed since erasure review')
    service._verify_folder(source,manifest,bid)
    if manifest.get('format')!=2:raise ValueError('Migrate legacy backup format before owner redaction')
    stage=Path(tempfile.mkdtemp(prefix='.privacy-backup-',dir=service.root));prepared=False
    journal['building']=stage.name;write_journal(root,journal)
    try:
        new=stage/'new';shutil.copytree(source,new)
        from privacy.erasure import OwnerErasure
        from privacy.files import CATALOG, read_catalog
        catalog=read_catalog(root)
        if catalog:
            (new/'data').mkdir(exist_ok=True)
            (new/'data'/CATALOG).write_text(json.dumps(catalog),encoding='utf-8')
        OwnerErasure(new/'data')._erase_records(journal['owner'])
        (new/'data'/CATALOG).unlink(missing_ok=True)
        files=[]
        for item in manifest['files']:
            path=new/item['name']
            if path.exists():files.append({'name':item['name'],'sha256':digest(path),'bytes':path.stat().st_size})
        manifest['files']=files
        manifest.setdefault('redacted_owner_sha256',[])
        owner_hash=hashlib.sha256(journal['owner'].encode()).hexdigest()
        if owner_hash not in manifest['redacted_owner_sha256']:manifest['redacted_owner_sha256'].append(owner_hash)
        (new/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        service._verify_folder(new,manifest,bid)
        journal.pop('building',None)
        journal.update(transaction=stage.name,prepared_sha256=digest(new/'manifest.json'))
        write_journal(root,journal);prepared=True
        resume_backup(root)
    finally:
        if not prepared:shutil.rmtree(stage)
