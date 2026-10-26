import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from operations.maintenance import ProfileLease,MaintenanceBusy,LOCK_NAME
from operations.backup import BackupManager,BackupError
from memory.vault import MemoryVault
from memory.retrieval import RetrievalEngine
from privacy.erasure import OwnerErasure,LEDGER
from privacy.legacy import LegacyMemoryReview
from sqlite_utils import connect

class MemoryMaintenanceTests(unittest.TestCase):
    def test_live_runtime_lease_blocks_backup_restore_and_erasure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault');vault.add('private',owner='alice')
            backups=BackupManager(root);bid=backups.create()['backup_id'];eraser=OwnerErasure(root)
            preview=eraser.preview('alice')
            with ProfileLease(root,runtime=True):
                for action in (backups.create,lambda:backups.restore(bid,bid),lambda:eraser.erase('alice',preview['confirmation'])):
                    with self.assertRaises(MaintenanceBusy):action()
            self.assertTrue(backups.verify(backups.create()['backup_id'])['verified'])

    def test_lock_is_cross_process_and_released_after_process_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            script="from operations.maintenance import ProfileLease; import sys; lease=ProfileLease(sys.argv[1],runtime=True); print('ready',flush=True); sys.stdin.read()"
            child=subprocess.Popen([sys.executable,'-c',script,tmp],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                with self.assertRaises(MaintenanceBusy):BackupManager(Path(tmp)).create()
            finally:
                child.communicate('',timeout=10)
            self.assertTrue(BackupManager(Path(tmp)).create()['backup_id'])

    def test_recovery_to_clean_profile_with_external_erasure_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';new=root/'recovered';old.mkdir();new.mkdir()
            vault=MemoryVault(old/'memory.db',old/'vault')
            vault.add('Alice private project',owner='alice')
            vault.add('Bob launch June',owner='bob',fact_key='launch')
            current=vault.add('Bob launch July',owner='bob',fact_key='launch')
            source=old/'vault'/'note.md';source.write_text('outdated note');vault.sync_markdown()
            mid=vault.search('outdated')[0]['id'];vault.update(mid,content='corrected note')
            (old/'workspace').mkdir();(old/'workspace'/'draft.txt').write_text('verified backup payload')
            backups=BackupManager(old);bid=backups.create()['backup_id']
            eraser=OwnerErasure(old);eraser.erase('alice',eraser.preview('alice')['confirmation'])
            # Transfer the current independent deletion ledger, never the old backup's state.
            shutil.copy2(old/LEDGER,new/LEDGER)
            target=BackupManager(new);shutil.copytree(backups.root/bid,target.root/bid)
            self.assertTrue(target.verify(bid)['verified']);target.restore(bid,bid)
            restored=MemoryVault(new/'memory.db',new/'vault')
            self.assertEqual(restored.list(as_user='alice'),[])
            self.assertEqual(restored.search('launch',as_user='bob')[0]['id'],current)
            self.assertEqual(restored.get(mid)['content'],'corrected note')
            self.assertEqual((new/'workspace'/'draft.txt').read_text(),'verified backup payload')
            with connect(new/'memory.db') as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertFalse(any(item['name'].endswith(LOCK_NAME) for item in target._manifest(bid)[1]['files']))
            (target.root/bid/'data'/'workspace'/'draft.txt').write_text('corrupt')
            with self.assertRaises(BackupError):target.restore(bid,bid)
            self.assertEqual((new/'workspace'/'draft.txt').read_text(),'verified backup payload')

    def test_legacy_assignment_requires_fresh_review_and_preserves_other_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            selected=vault.add('reviewed legacy note');shared=vault.add('genuinely shared note')
            review=LegacyMemoryReview(root);preview=review.preview()
            with self.assertRaises(ValueError):review.assign({selected:'alice'},'wrong')
            review.assign({selected:'alice'},preview['confirmation'])
            self.assertEqual(vault.list(as_user='alice')[0]['id'],selected)
            self.assertEqual(vault.get(shared)['owner'],'shared')
            with self.assertRaises(ValueError):review.assign({shared:'bob'},preview['confirmation'])

    def test_context_budget_counts_serialized_rows_and_drops_unbounded_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            vault.add('Atlas project',owner='alice',metadata={'huge':'x'*20000})
            rows=RetrievalEngine(vault,scope='alice',char_budget=400).retrieve('Atlas')
            self.assertTrue(rows)
            self.assertLessEqual(len(json.dumps(rows,default=str)),400)
            self.assertNotIn('metadata',rows[0])

    def test_runtime_holds_lease_until_close(self):
        from agent.enhanced_loop import AgentLoop
        from test_phase9_loop import make_settings
        with tempfile.TemporaryDirectory() as tmp:
            loop=AgentLoop(settings=make_settings(Path(tmp)),interactive=False,start_worker=False)
            try:
                with self.assertRaises(MaintenanceBusy):loop.backups.create()
            finally:loop.close()
            self.assertTrue(loop.backups.create()['backup_id'])

    def test_temporary_intentions_and_credentials_are_not_durable(self):
        from memory.learner import AutoLearner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault');learner=AutoLearner(vault)
            self.assertEqual(learner.learn('I want to order lunch today.','alice','alice'),[])
            self.assertEqual(learner.learn('Remember that my password is synthetic-private.','alice','alice'),[])
            self.assertTrue(learner.learn('My goal is to open a neighborhood bakery.','alice','alice'))
            self.assertEqual(len(vault.list(as_user='alice')),1)

    def test_evaluation_harness_does_not_award_perfect_results_to_useless_embeddings(self):
        from scripts.evaluate_memory import evaluate
        corpus=json.loads((Path(__file__).resolve().parents[1]/'benchmarks/memory/v1.json').read_text())
        class UselessEmbedder:
            model_id='test-only-not-real-model'
            def encode(self,texts):return [[1.0,0.0] for _ in texts]
        report=evaluate(corpus,UselessEmbedder())
        self.assertFalse(report['passed'])
        self.assertEqual(report['metrics']['owner_leaks'],0)
        self.assertEqual(report['metrics']['stale_hits'],0)

    def test_individual_deletion_survives_old_backup_and_does_not_delete_reused_id(self):
        from privacy.memory_deletions import enforce
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault')
            mid=vault.add('private fact',owner='alice');backup=BackupManager(root);bid=backup.create()['backup_id']
            vault.remove(mid,as_user='alice');replacement=vault.add('different fact',owner='alice')
            enforce(root)
            self.assertIsNotNone(vault.get(replacement,as_user='alice'))
            backup.restore(bid,bid)
            self.assertIsNone(MemoryVault(root/'memory.db',root/'vault').get(mid,as_user='alice'))

    def test_process_death_during_restore_blocks_startup_until_recovered(self):
        from operations.maintenance import PENDING_RESTORE
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.txt').write_text('snapshot-a');(root/'b.txt').write_text('snapshot-b')
            backup=BackupManager(root);bid=backup.create()['backup_id']
            (root/'a.txt').write_text('live-a');(root/'b.txt').write_text('live-b')
            script="""import os,sys
from pathlib import Path
from operations.backup import BackupManager
root=Path(sys.argv[1]);bid=sys.argv[2];replace=os.replace
def crash(source,target):
    replace(source,target)
    if Path(target)==root/'a.txt':os._exit(73)
os.replace=crash
BackupManager(root).restore(bid,bid)
"""
            result=subprocess.run([sys.executable,'-c',script,str(root),bid],timeout=15)
            self.assertEqual(result.returncode,73)
            self.assertTrue((root/PENDING_RESTORE).exists())
            with self.assertRaises(MaintenanceBusy):ProfileLease(root,runtime=True)
            with self.assertRaises(BackupError):backup.create()
            backup.restore(bid,bid)
            self.assertFalse((root/PENDING_RESTORE).exists())
            self.assertEqual((root/'a.txt').read_text(),'snapshot-a')
            self.assertEqual((root/'b.txt').read_text(),'snapshot-b')
            with ProfileLease(root,runtime=True):pass

    def test_shared_skill_root_excludes_backup_from_other_profile(self):
        from operations.maintenance import ProfileLeases
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);skills=root/'skills'
            with ProfileLeases(root/'active',skills,runtime=True):
                with self.assertRaises(MaintenanceBusy):BackupManager(root/'offline',skills).create()
            self.assertTrue(BackupManager(root/'offline',skills).create()['backup_id'])

    def test_owner_erasure_rewrites_mixed_review_journal_without_guessing(self):
        from agent.tasks import TaskStore
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=TaskStore(root/'tasks.db')
            alice=tasks.create('private',owner='alice');bob=tasks.create('private',owner='bob')
            folder=root/'vault'/'conversation_reviews';folder.mkdir(parents=True)
            path=folder/'day.jsonl'
            path.write_text(json.dumps({'task_id':alice})+'\n'+json.dumps({'task_id':bob})+'\nunknown legacy line\n')
            eraser=OwnerErasure(root);preview=eraser.preview('alice')
            self.assertEqual(preview['review_records'][0]['records'],1)
            eraser.erase('alice',preview['confirmation'])
            self.assertNotIn(alice,path.read_text());self.assertIn(bob,path.read_text())
            self.assertIn('unknown legacy line',path.read_text())
