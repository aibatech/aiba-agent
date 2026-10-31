import tempfile
import unittest
from pathlib import Path
from memory.vault import MemoryVault
from memory.learner import AutoLearner
from operations.backup import BackupManager, BackupError
from approvals.store import ApprovalStore
import json


class MemoryRecoveryTests(unittest.TestCase):
    def test_correction_deletion_restart_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'vault'; source.mkdir()
            (source/'project.md').write_text('Project Atlas launches in June')
            vault=MemoryVault(root/'memory.db',source)
            mid=vault.search('Atlas')[0]['id']
            vault.update(mid,content='Project Atlas launches in July')
            vault=MemoryVault(root/'memory.db',source)
            self.assertIn('July',vault.get(mid)['content'])
            vault.add('private project',owner='alice')
            self.assertEqual(vault.search('private',as_user='bob'),[])
            backup=BackupManager(root)
            created=backup.create()
            vault.remove(mid)
            self.assertEqual(MemoryVault(root/'memory.db',source).search('Atlas'),[])
            backup.restore(created['backup_id'],created['backup_id'])
            self.assertIsNone(MemoryVault(root/'memory.db',source).get(mid))

    def test_changed_fact_is_not_silently_discarded_as_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault');learner=AutoLearner(vault)
            self.assertTrue(learner.learn('My goal is to grow the business to $20M.', 'alice', 'alice'))
            self.assertTrue(learner.learn('My goal is to grow the business to $30M.', 'alice', 'alice'))
            self.assertEqual(learner.learn('My goal is to grow the business to $30M.', 'alice', 'alice'),[])

    def test_restore_invalidates_approvals_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=ApprovalStore(root/'approvals.db');token=store.issue('alice','fp')
            backup=BackupManager(root);created=backup.create();bid=created['backup_id']
            backup.restore(bid,bid)
            self.assertFalse(store.consume(token,'alice','fp'))
            path=backup.root/bid/'manifest.json';manifest=json.loads(path.read_text())
            manifest['files']=[{'name':'../outside','sha256':'x'}];path.write_text(json.dumps(manifest))
            with self.assertRaises(BackupError):backup.verify(bid)
