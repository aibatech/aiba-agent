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

    def test_confirmation_binds_content_not_only_row_count(self):
        from sqlite_utils import connect
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            vault.add('original private fact',owner='alice')
            operation=OwnerErasure(root);preview=operation.preview('alice')
            self.assertNotIn('original private fact',json.dumps(preview))
            with connect(root/'memory.db') as db:
                db.execute("UPDATE memories SET content='corrected private fact' WHERE owner='alice'")
            with self.assertRaises(ValueError):operation.erase('alice',preview['confirmation'])
            self.assertTrue(vault.list(as_user='alice'))
            self.assertFalse((root/'privacy-erasure.json').exists())
            operation.erase('alice',operation.preview('alice')['confirmation'])
            self.assertFalse(vault.list(as_user='alice'))

    def test_plan_changes_require_review_even_when_task_unchanged(self):
        from sqlite_utils import connect
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=TaskStore(root/'tasks.db');tid=tasks.create('task',owner='alice')
            tasks.set_plan(tid,['old step'])
            operation=OwnerErasure(root);preview=operation.preview('alice')
            with connect(root/'tasks.db') as db:
                db.execute('UPDATE task_plans SET steps=? WHERE task_id=?',(json.dumps([{'description':'new step','status':'pending'}]),tid))
            with self.assertRaises(ValueError):operation.erase('alice',preview['confirmation'])
            self.assertEqual(tasks.plan(tid)[0]['description'],'new step')

    def test_shared_identity_and_malformed_ledger_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            vault.add('shared fact');vault.add('owner fact',owner='alice')
            operation=OwnerErasure(root)
            with self.assertRaises(ValueError):operation.preview('shared')
            preview=operation.preview('alice')
            self.assertGreater(preview['unattributed_rows'],0)
            for ledger in ({'owners':'alice'},{'owners':['shared']},{'owners':[None]}):
                (root/'privacy-erasure.json').write_text(json.dumps(ledger))
                with self.assertRaises(ValueError):operation.erase('alice',preview['confirmation'])
                with self.assertRaises(ValueError):operation.enforce_after_restore()
            self.assertTrue(vault.list(as_user='alice'))

    def test_malformed_job_payload_is_retained_without_blocking_attributed_erasure(self):
        from sqlite_utils import connect
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with connect(root/'jobs.db') as db:
                db.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,payload TEXT)')
                db.executemany('INSERT INTO jobs VALUES (?,?)',[(1,'broken legacy json'),(2,json.dumps({'user_id':'alice'})),(3,json.dumps({'user_id':'bob'}))])
            operation=OwnerErasure(root);preview=operation.preview('alice')
            self.assertEqual(preview['unattributed_rows'],1)
            operation.erase('alice',preview['confirmation'])
            with connect(root/'jobs.db') as db:self.assertEqual([r[0] for r in db.execute('SELECT id FROM jobs ORDER BY id')],[1,3])

    def test_embedding_cleanup_does_not_depend_on_current_version_triggers(self):
        from sqlite_utils import connect
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            alice=vault.add('alice fact',owner='alice');bob=vault.add('bob fact',owner='bob')
            with connect(root/'memory.db') as db:
                db.execute('CREATE TABLE memory_embeddings(memory_id INTEGER,vector TEXT)')
                db.executemany('INSERT INTO memory_embeddings VALUES (?,?)',[(alice,'alice vector'),(bob,'bob vector')])
            operation=OwnerErasure(root);operation.erase('alice',operation.preview('alice')['confirmation'])
            with connect(root/'memory.db') as db:self.assertEqual(db.execute('SELECT memory_id FROM memory_embeddings').fetchall(),[(bob,)])

    def test_explicit_foreign_or_conflicting_file_ownership_is_never_inferred_from_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=TaskStore(root/'tasks.db');tid=tasks.create('task',owner='alice')
            folder=root/'vault'/'reflections';folder.mkdir(parents=True)
            records=[{'owner':'bob','task_id':tid},{'owner':'alice','user_id':'bob','task_id':tid},
                     {'owner':None,'task_id':tid},{'owner':'alice','task_id':tid}]
            for i,record in enumerate(records):(folder/f'{i}.json').write_text(json.dumps(record))
            reviews=root/'vault'/'conversation_reviews';reviews.mkdir()
            journal=reviews/'mixed.jsonl';journal.write_text(''.join(json.dumps(r)+'\n' for r in records))
            operation=OwnerErasure(root);operation.erase('alice',operation.preview('alice')['confirmation'])
            self.assertEqual(sorted(p.name for p in folder.iterdir()),['0.json','1.json','2.json'])
            self.assertEqual([json.loads(line) for line in journal.read_text().splitlines()],records[:3])

    def test_confirmation_is_bound_to_profile(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'first';second=Path(tmp)/'second';first.mkdir();second.mkdir()
            MemoryVault(first/'memory.db',first/'vault').add('same fact',owner='alice')
            shutil.copyfile(first/'memory.db',second/'memory.db')
            preview=OwnerErasure(first).preview('alice')
            with self.assertRaises(ValueError):OwnerErasure(second).erase('alice',preview['confirmation'])
            self.assertFalse((second/'privacy-erasure.json').exists())
