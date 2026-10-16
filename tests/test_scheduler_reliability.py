import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from runtime.queue import JobQueue
from runtime.scheduler import Scheduler
from sqlite_utils import connect

class SchedulerReliabilityTests(unittest.TestCase):
    def fixture(self, root):
        queue=JobQueue(root/'jobs.db');scheduler=Scheduler(root/'schedules.db',queue)
        sid=scheduler.add_interval('daily','test',{'value':1},60)
        with connect(scheduler.path) as db:db.execute("UPDATE schedules SET next_run='2000-01-01T00:00:00+00:00'")
        return queue,scheduler

    def test_concurrent_ticks_enqueue_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue,scheduler=self.fixture(Path(tmp))
            with ThreadPoolExecutor(max_workers=8) as pool:
                counts=list(pool.map(lambda _:scheduler.tick(),range(16)))
            self.assertEqual(sum(counts),1);self.assertEqual(len(queue.list()),1)

    def test_crash_after_enqueue_before_schedule_commit_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue,scheduler=self.fixture(Path(tmp));enqueue=queue.enqueue
            def interrupted(*args,**kwargs):
                enqueue(*args,**kwargs)
                raise RuntimeError('simulated crash before schedule commit')
            with patch.object(queue,'enqueue',side_effect=interrupted):
                with self.assertRaises(RuntimeError):scheduler.tick()
            scheduler.tick();self.assertEqual(len(queue.list()),1)

    def test_stale_worker_cannot_complete_new_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue=JobQueue(Path(tmp)/'jobs.db');job=queue.enqueue('test',{})
            first=queue.claim();self.assertEqual(queue.recover(stale_seconds=60),0)
            queue.recover();second=queue.claim()
            queue.complete(job,'stale',claim_token=first['claim_token'])
            self.assertEqual(queue.get(job)['status'],'running')
            queue.complete(job,'fresh',claim_token=second['claim_token'])
            self.assertEqual(queue.get(job)['result'],'"fresh"')

    def test_idempotency_key_cannot_change_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue=JobQueue(Path(tmp)/'jobs.db')
            one=queue.enqueue('test',{'a':1},idempotency_key='same')
            self.assertEqual(one,queue.enqueue('test',{'a':1},idempotency_key='same'))
            with self.assertRaises(ValueError):queue.enqueue('test',{'a':2},idempotency_key='same')
