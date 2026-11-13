import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.tasks import TaskStore
from memory.vault import MemoryVault
from operations.backup import BackupManager, BackupError
from operations.maintenance import ProfileLease, MaintenanceBusy, PENDING_PRIVACY
from privacy.erasure import OwnerErasure
from sqlite_utils import connect


class PrivacyBackupLifecycleTests(unittest.TestCase):
    def profile(self, root):
        vault=MemoryVault(root/'memory.db',root/'vault');tasks=TaskStore(root/'tasks.db')
        ids={}
        for owner in ('alice','bob'):
            vault.add(owner+' private fact',owner=owner)
            ids[owner]=tasks.create(owner+' private task',owner=owner)
        logs=root/'logs';logs.mkdir()
        rows=[{'task_id_sha256':hashlib.sha256(ids[owner].encode()).hexdigest(),'payload':owner+' diagnostic'} for owner in ids]
        rows += [{'context':{'task_id':ids['alice']},'detail':'alice crash'}, {'owner':'bob','task_id':ids['alice'],'detail':'conflicting shared context'}]
        (logs/'audit.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows)+'malformed legacy line\n')
        return vault,tasks

    def test_redacts_active_and_retained_backup_without_deleting_other_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault,tasks=self.profile(root);backups=BackupManager(root)
            bid=backups.create()['backup_id'];operation=OwnerErasure(root,include_backups=True)
            preview=operation.preview('alice');self.assertEqual(len(preview['backups']),1)
            result=operation.erase('alice',preview['confirmation'])
            self.assertTrue(result['backup_records_redacted'])
            self.assertTrue(backups.verify(bid)['verified'])
            with connect(root/'backups'/bid/'data'/'memory.db') as db:
                self.assertEqual(db.execute('SELECT owner FROM memories').fetchall(),[('bob',)])
            for log in (root/'logs'/'audit.jsonl',root/'backups'/bid/'data'/'logs'/'audit.jsonl'):
                text=log.read_text();self.assertNotIn('alice diagnostic',text);self.assertNotIn('alice crash',text)
                self.assertIn('bob diagnostic',text);self.assertIn('conflicting shared context',text);self.assertIn('malformed legacy',text)
            backups.restore(bid,bid)
            self.assertFalse(vault.list(as_user='alice'));self.assertTrue(vault.list(as_user='bob'))
            self.assertFalse((root/PENDING_PRIVACY).exists())
            self.assertFalse(list((root/'backups').glob('.privacy-backup-*')))

    def test_changed_backup_inventory_requires_new_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.profile(root);backups=BackupManager(root);backups.create()
            operation=OwnerErasure(root,include_backups=True);preview=operation.preview('alice')
            backups.create()
            with self.assertRaises(ValueError):operation.erase('alice',preview['confirmation'])
            self.assertFalse((root/PENDING_PRIVACY).exists())

    def test_interrupted_swap_blocks_runtime_and_restore_then_resumes(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault,_=self.profile(root);backups=BackupManager(root);bid=backups.create()['backup_id']
            operation=OwnerErasure(root,include_backups=True);preview=operation.preview('alice');replace=os.replace
            def crash(source,target,*args,**kwargs):
                replace(source,target,*args,**kwargs)
                if Path(target).name=='old':raise KeyboardInterrupt('simulated process termination after old snapshot moved')
            with patch('privacy.backup_redaction.os.replace',side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):operation.erase('alice',preview['confirmation'])
            with self.assertRaises(MaintenanceBusy):ProfileLease(root,runtime=True)
            with self.assertRaises(BackupError):backups.restore(bid,bid)
            with self.assertRaises(ValueError):operation.resume('bob')
            operation.resume('alice')
            self.assertTrue(backups.verify(bid)['verified'])
            self.assertTrue(vault.list(as_user='bob'));self.assertFalse(vault.list(as_user='alice'))
            with ProfileLease(root,runtime=True):pass

    def test_interrupted_staging_is_tracked_and_cleaned_on_resume(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.profile(root);backups=BackupManager(root);backups.create()
            operation=OwnerErasure(root,include_backups=True);preview=operation.preview('alice');copy=shutil.copytree
            def crash(*args,**kwargs):
                copy(*args,**kwargs)
                raise KeyboardInterrupt('simulated staging termination')
            with patch('privacy.backup_redaction.shutil.copytree',side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):operation.erase('alice',preview['confirmation'])
            self.assertTrue((root/PENDING_PRIVACY).exists())
            operation.resume('alice')
            self.assertFalse(list((root/'backups').glob('.privacy-backup-*')))

    def test_reviewed_sources_exports_and_historical_versions_erased_across_restore(self):
        from privacy.files import FileOwnershipReview, CATALOG
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.profile(root)
            source=root/'vault'/'notes.md';source.write_text('alice old source')
            export=root/'export.txt';export.write_text('alice export')
            shared=root/'shared.txt';shared.write_text('genuinely shared')
            backups=BackupManager(root);bid=backups.create()['backup_id']
            source.write_text('alice corrected source')
            review=FileOwnershipReview(root);mapping={'vault/notes.md':'alice','export.txt':'alice'}
            plan=review.preview(mapping,include_backups=True)
            review.assign(mapping,plan['confirmation'],include_backups=True)
            operation=OwnerErasure(root,include_backups=True)
            operation.erase('alice',operation.preview('alice')['confirmation'])
            self.assertFalse(source.exists());self.assertFalse(export.exists());self.assertTrue(shared.exists())
            self.assertFalse((root/'backups'/bid/'data'/CATALOG).exists())
            backups.restore(bid,bid)
            self.assertFalse(source.exists());self.assertFalse(export.exists());self.assertEqual(shared.read_text(),'genuinely shared')
            self.assertTrue((root/CATALOG).exists())

    def test_file_review_rejects_changes_conflicts_and_unsafe_paths(self):
        from privacy.files import FileOwnershipReview
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/'source.md';file.write_text('old');review=FileOwnershipReview(root)
            mapping={'source.md':'alice'};plan=review.preview(mapping);file.write_text('changed')
            with self.assertRaises(ValueError):review.assign(mapping,plan['confirmation'])
            review.assign(mapping,review.preview(mapping)['confirmation'])
            with self.assertRaises(ValueError):review.preview({'source.md':'bob'})
            for name in ('../source.md','/source.md','privacy-erasure.json','memory.db','backups/old'):
                with self.assertRaises(ValueError):review.preview({name:'alice'})
            file.write_text('unreviewed content')
            with self.assertRaises(ValueError):OwnerErasure(root).preview('alice')

    def test_unmanifested_backup_content_is_rejected_before_erasure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.profile(root);backups=BackupManager(root);bid=backups.create()['backup_id']
            (root/'backups'/bid/'unreviewed.txt').write_text('unknown private copy')
            with self.assertRaises(BackupError):OwnerErasure(root,include_backups=True).preview('alice')
            self.assertFalse((root/PENDING_PRIVACY).exists())

    def test_process_death_and_corrupt_prepared_snapshot_fail_closed(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault,_=self.profile(root);backups=BackupManager(root)
            bid=backups.create()['backup_id']
            script='''
import os,sys
from pathlib import Path
from privacy.erasure import OwnerErasure
import privacy.backup_redaction as module
root=Path(sys.argv[1]);operation=OwnerErasure(root,include_backups=True)
original=module.os.replace
def terminate(source,target,*args,**kwargs):
    original(source,target,*args,**kwargs)
    if Path(target).name=='old':os._exit(73)
module.os.replace=terminate
operation.erase('alice',operation.preview('alice')['confirmation'])
'''
            child=subprocess.run([sys.executable,'-c',script,str(root)],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=30)
            self.assertEqual(child.returncode,73,child.stderr.decode())
            journal=json.loads((root/PENDING_PRIVACY).read_text())
            stage=root/'backups'/journal['transaction']
            prepared=stage/'new'/'data'/'memory.db';original=prepared.read_bytes()
            prepared.write_bytes(b'corrupt')
            with self.assertRaises(BackupError):OwnerErasure(root).resume('alice')
            self.assertTrue((stage/'old').is_dir())
            with self.assertRaises(MaintenanceBusy):ProfileLease(root,runtime=True)
            # Restore only the known exact prepared bytes; approval is not bypassed.
            prepared.write_bytes(original)
            OwnerErasure(root).resume('alice')
            self.assertTrue(backups.verify(bid)['verified'])
            self.assertFalse(vault.list(as_user='alice'));self.assertTrue(vault.list(as_user='bob'))
            with ProfileLease(root,runtime=True):pass

    def test_explicit_file_provenance_cannot_be_reassigned(self):
        from privacy.files import FileOwnershipReview
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'record.json').write_text(json.dumps({'owner':'bob','value':'private'}))
            with self.assertRaises(ValueError):FileOwnershipReview(root).preview({'record.json':'alice'})
