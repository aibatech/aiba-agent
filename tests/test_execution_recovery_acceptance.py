import tempfile
import unittest
from pathlib import Path
from runtime.queue import JobQueue
from runtime.worker import Worker

class ExecutionRecoveryTests(unittest.TestCase):
    def test_retry_then_success_and_cancel_survives_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue=JobQueue(Path(tmp)/'jobs.db');calls=[]
            def run(payload):
                calls.append(1)
                if len(calls)==1:raise TimeoutError('temporary failure')
                return {'verified':True}
            worker=Worker(queue,{'test':run});job=queue.enqueue('test',{},retry_policy='safe')
            worker.run_once();self.assertEqual(queue.get(job)['status'],'queued')
            worker.run_once();self.assertEqual(queue.get(job)['status'],'complete')
            cancelled=queue.enqueue('test',{},retry_policy='safe');self.assertTrue(queue.cancel(cancelled))
            self.assertFalse(worker.run_once())
            running=queue.enqueue('test',{},retry_policy='safe');queue.claim();queue.cancel(running);queue.complete(running,'late result')
            self.assertEqual(queue.get(running)['status'],'cancelled')

    def test_restart_recovery_respects_attempt_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'jobs.db';queue=JobQueue(path);job=queue.enqueue('test',{},max_attempts=1,retry_policy='safe')
            queue.claim();restarted=JobQueue(path);restarted.recover()
            self.assertEqual(restarted.get(job)['status'],'failed')
            self.assertIsNone(restarted.claim())
