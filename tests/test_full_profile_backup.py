import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from operations.backup import BackupManager,BackupError
from memory.vault import MemoryVault
from skills.manager import SkillManager
import os

class FullProfileBackupTests(unittest.TestCase):
    def test_vault_workspace_skills_database_and_revisions_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();skills=root/'skills'
            vault=MemoryVault(data/'memory.db',data/'vault')
            vault.add('Atlas project',owner='alice')
            (data/'vault'/'owner.md').write_text('Owner preferences')
            workspace=data/'workspace';workspace.mkdir();(workspace/'work.txt').write_text('original')
            manager=SkillManager(skills);manager.create('test','original',[{'tool':'list_files','arguments':{}}])
            backup=BackupManager(data,skills);created=backup.create();bid=created['backup_id']
            (workspace/'work.txt').write_text('changed');(data/'vault'/'owner.md').write_text('changed')
            manager.create('test','changed',[],version='0.2.0')
            backup.restore(bid,bid)
            self.assertEqual((workspace/'work.txt').read_text(),'original')
            self.assertEqual((data/'vault'/'owner.md').read_text(),'Owner preferences')
            self.assertEqual(manager.get('test').description,'original')
            self.assertTrue(backup.verify(bid)['verified'])

    def test_restore_io_failure_rolls_back_prior_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);(data/'a.txt').write_text('old-a');(data/'b.txt').write_text('old-b')
            backup=BackupManager(data);bid=backup.create()['backup_id']
            (data/'a.txt').write_text('current-a');(data/'b.txt').write_text('current-b')
            replace=os.replace
            def fail(source,target):
                if Path(target)==data/'b.txt':raise OSError('simulated disk failure')
                return replace(source,target)
            with patch('operations.backup.os.replace',side_effect=fail):
                with self.assertRaises(OSError):backup.restore(bid,bid)
            self.assertEqual((data/'a.txt').read_text(),'current-a')
            self.assertEqual((data/'b.txt').read_text(),'current-b')
