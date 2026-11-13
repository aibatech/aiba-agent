"""Explicit whole-file attribution for legacy sources/exports; never infer an owner."""
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from operations.maintenance import ProfileLease

CATALOG='privacy-files.json'


def safe_file(root, name):
    if not isinstance(name,str) or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('Use a profile-relative file path')
    parts=PurePosixPath(name).parts
    if not parts or any(p in {'','.', '..'} for p in name.split('/')) or parts[0]=='backups':
        raise ValueError('Unsafe or shared backup path')
    if parts[-1].endswith(('.db','-wal','-shm')) or any(p.startswith('.') or p.startswith('privacy-') for p in parts):
        raise ValueError('Databases and control files require their dedicated lifecycle')
    path=root.joinpath(*parts)
    for node in (path,*path.parents):
        if node==root.parent:break
        if node.is_symlink():raise ValueError('Symlink attribution is forbidden')
    path.resolve().relative_to(root)
    if path.exists() and (not path.is_file() or path.stat().st_nlink!=1):raise ValueError('Regular singly linked file required')
    return path


def read_catalog(root):
    path=root/CATALOG
    if path.is_symlink():raise ValueError('Unsafe file attribution catalog')
    data=json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data,dict):raise ValueError('Invalid file attribution catalog')
    from privacy.erasure import OwnerErasure
    for name,row in data.items():
        safe_file(root,name)
        if not isinstance(row,dict) or not isinstance(row.get('hashes'),list) or not row['hashes']:raise ValueError('Invalid file attribution')
        OwnerErasure._validate_owner(row.get('owner'))
        if any(not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for h in row['hashes']):raise ValueError('Invalid file content fingerprint')
    return data


def selected(root, owner):
    result=[]
    for name,row in read_catalog(root).items():
        if row['owner']!=owner:continue
        path=safe_file(root,name)
        if not path.exists():continue
        if hashlib.sha256(path.read_bytes()).hexdigest() not in row['hashes']:
            raise ValueError('Attributed file changed; review its current ownership/content before erasure')
        result.append(path)
    return result


class FileOwnershipReview:
    def __init__(self,data_dir):self.root=Path(data_dir).resolve()

    def _preview(self,assignments,include_backups=False):
        from privacy.erasure import OwnerErasure
        if not isinstance(assignments,dict) or not assignments:raise ValueError('Explicit file-to-owner mapping required')
        current=read_catalog(self.root);files=[]
        for name,owner in sorted(assignments.items()):
            OwnerErasure._validate_owner(owner)
            if name in current and current[name]['owner']!=owner:raise ValueError('Ownership conflicts require a separate reviewed migration; use a new path')
            path=safe_file(self.root,name)
            if not path.is_file():raise ValueError('Attribution requires an existing file')
            if path.suffix=='.json':
                try:metadata=json.loads(path.read_text(encoding='utf-8'))
                except (ValueError,UnicodeError):metadata=None
                if isinstance(metadata,dict) and any(metadata[k]!=owner for k in ('owner','user_id') if k in metadata):
                    raise ValueError('Explicit file provenance disagrees; resolve it before whole-file attribution')
            files.append({'path':name,'owner':owner,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        plan={'profile':str(self.root),'files':files,'catalog':current,
              'warning':'Attest that each entire file belongs exclusively to the selected owner; never assign shared or mixed-owner files.'}
        if include_backups:
            from privacy.backup_redaction import inventory, manager
            plan['backups']=inventory(self.root)
            for backup in plan['backups']:
                _,manifest=manager(self.root)._manifest(backup['backup_id'])
                for item in manifest['files']:
                    for entry in files:
                        if item['name']=='data/'+entry['path']:
                            entry.setdefault('historical_hashes',[]).append(item['sha256'])
        plan['confirmation']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
        return plan

    def preview(self,assignments,include_backups=False):
        with ProfileLease(self.root):return self._preview(assignments,include_backups)

    def assign(self,assignments,confirmation,include_backups=False):
        with ProfileLease(self.root):
            plan=self._preview(assignments,include_backups)
            if confirmation!=plan['confirmation']:raise ValueError('Review the current file ownership inventory')
            catalog=plan['catalog']
            for item in plan['files']:
                row=catalog.setdefault(item['path'],{'owner':item['owner'],'hashes':[]})
                for sha in [item['sha256'],*item.get('historical_hashes',[])]:
                    if sha not in row['hashes']:row['hashes'].append(sha)
            fd,temporary=tempfile.mkstemp(prefix='.file-ownership-',dir=self.root)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream:
                    json.dump(catalog,stream);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,self.root/CATALOG)
            finally:Path(temporary).unlink(missing_ok=True)
            return {'attributed_files':len(plan['files'])}
