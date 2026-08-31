import json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from sqlite_utils import connect
from operations import BackupManager,CrashReporter,Metrics,MigrationManager
from runtime.queue import JobQueue
from skills.manager import SkillManager

class OperationsTests(unittest.TestCase):
    def test_backup_verify_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);db=data/'aiba.db'
            with connect(db) as c:c.execute('CREATE TABLE sample(value TEXT)');c.execute("INSERT INTO sample VALUES('before')")
            backups=BackupManager(data);created=backups.create('test');self.assertTrue(backups.verify(created['backup_id'])['verified'])
            with connect(db) as c:c.execute("UPDATE sample SET value='after'")
            restored=backups.restore(created['backup_id'],created['backup_id']);self.assertTrue(restored['restored'])
            with connect(db) as c:self.assertEqual(c.execute('SELECT value FROM sample').fetchone()[0],'before')
            self.assertNotEqual(restored['safety_backup_id'],created['backup_id'])
    def test_migrations_are_idempotent_and_checksummed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            with connect(data/'jobs.db') as c:c.execute('CREATE TABLE jobs(status TEXT,locked_at TEXT)')
            manager=MigrationManager(data);first=manager.apply();second=manager.apply();self.assertEqual(first,second);self.assertTrue(next(x for x in manager.status() if x['database']=='jobs.db')['ready'])
    def test_metrics_and_crash_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics=Metrics();metrics.increment('tasks_total',status='ok');self.assertIn('aiba_tasks_total',metrics.prometheus())
            reporter=CrashReporter(Path(tmp))
            try:raise RuntimeError('boom')
            except RuntimeError as exc:crash_id=reporter.capture(exc,{'safe':True})
            row=json.loads((Path(tmp)/'crashes.jsonl').read_text());self.assertEqual(row['id'],crash_id);self.assertNotIn('secret',row)

class ConcurrencyTests(unittest.TestCase):
    def test_queue_claim_is_single_owner_under_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue=JobQueue(Path(tmp)/'jobs.db');job=queue.enqueue('test',{});claims=[]
            threads=[threading.Thread(target=lambda:claims.append(queue.claim())) for _ in range(20)]
            [x.start() for x in threads];[x.join() for x in threads]
            claimed=[x for x in claims if x];self.assertEqual(len(claimed),1);self.assertEqual(claimed[0]['id'],job)

class CompatibilityTests(unittest.TestCase):
    def test_portable_markdown_skill_is_discovered_but_not_directly_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'incoming';source.mkdir();(source/'SKILL.md').write_text('---\nname: portable-test\ndescription: Safe instructions\nversion: 1.0.0\n---\nDo the reviewed task.')
            manager=SkillManager(root/'installed');skill=manager.import_markdown(source/'SKILL.md');self.assertEqual(skill.name,'portable-test');self.assertEqual(manager.list()[0]['format'],'portable-markdown');self.assertFalse(manager.instructions('portable-test')['executable'])
            with self.assertRaises(ValueError):manager.execute('portable-test',None)

if __name__=='__main__':unittest.main()
