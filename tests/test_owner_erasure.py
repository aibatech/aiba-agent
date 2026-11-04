import json
import tempfile
import unittest
from pathlib import Path
from memory.vault import MemoryVault
from agent.conversation_store import ConversationStore
from agent.tasks import TaskStore
from operations.backup import BackupManager
from privacy.erasure import OwnerErasure


class OwnerErasureTests(unittest.TestCase):
    def test_scoped_erasure_survives_restore_and_keeps_other_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            for owner in ('alice','bob'):
                vault.add(owner+' confidential fact',owner=owner,fact_key='fact')
            conversations=ConversationStore(root/'conversations.db')
            for owner in ('alice','bob'):
                cid=conversations.ensure(owner);conversations.append(owner,cid,'user','private text')
            tasks=TaskStore(root/'tasks.db');tid=tasks.create('private task',owner='alice');tasks.finish(tid,'private result')
            profiles=root/'profiles';profiles.mkdir()
            (profiles/'alice.json').write_text(json.dumps({'user_id':'alice','name':'private'}))
            (profiles/'alice-USER.md').write_text('private profile')
            (profiles/'bob.json').write_text(json.dumps({'user_id':'bob','name':'other'}))
            backups=BackupManager(root);bid=backups.create()['backup_id']
            operation=OwnerErasure(root);preview=operation.preview('alice')
            with self.assertRaises(ValueError):operation.erase('bob',preview['confirmation'])
            result=operation.erase('alice',preview['confirmation'])
            self.assertFalse(result['complete_account_erasure'])
            self.assertEqual(vault.list(as_user='alice'),[])
            self.assertEqual(conversations.list_by_user('alice'),[])
            self.assertIsNone(tasks.get(tid))
            self.assertFalse((profiles/'alice.json').exists())
            self.assertFalse((profiles/'alice-USER.md').exists())
            self.assertTrue((profiles/'bob.json').exists())
            self.assertTrue(vault.list(as_user='bob'))
            backups.restore(bid,bid)
            self.assertEqual(vault.list(as_user='alice'),[])
            self.assertEqual(conversations.list_by_user('alice'),[])
            self.assertIsNone(tasks.get(tid))
            self.assertFalse((profiles/'alice.json').exists())
            self.assertFalse((profiles/'alice-USER.md').exists())
            self.assertTrue((profiles/'bob.json').exists())
            self.assertTrue(vault.list(as_user='bob'))

    def test_changed_preview_requires_new_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            operation=OwnerErasure(root);preview=operation.preview('alice')
            vault.add('new fact',owner='alice')
            with self.assertRaises(ValueError):operation.erase('alice',preview['confirmation'])
            self.assertTrue(vault.list(as_user='alice'))
