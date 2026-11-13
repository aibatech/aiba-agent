import contextvars
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from approvals.manager import ApprovalManager
from approvals.store import ApprovalStore


class DurableApprovalTests(unittest.TestCase):
    def test_restart_principal_arguments_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'approvals.db'
            store = ApprovalStore(path)
            fp = ApprovalManager.action_fingerprint('run_shell', {'command': 'pwd'})
            token = store.issue('alice', fp)
            self.assertFalse(store.consume(token, 'bob', fp))
            self.assertFalse(store.consume(token, 'alice', 'different'))
            self.assertTrue(ApprovalStore(path).consume(token, 'alice', fp))
            self.assertFalse(ApprovalStore(path).consume(token, 'alice', fp))

    def test_concurrent_consumption_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApprovalStore(Path(tmp) / 'approvals.db')
            token = store.issue('alice', 'fp')
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: store.consume(token, 'alice', 'fp'), range(20)))
            self.assertEqual(sum(results), 1)

    def test_expiry_and_invalid_lifetimes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApprovalStore(Path(tmp) / 'approvals.db')
            with patch('approvals.store.time.time', return_value=100):
                token = store.issue('alice', 'fp', ttl=1)
            with patch('approvals.store.time.time', return_value=102):
                self.assertFalse(store.consume(token, 'alice', 'fp'))
            for ttl in (float('nan'), float('inf'), -1, 0):
                with self.assertRaises(ValueError):
                    store.issue('alice', 'fp', ttl)

    def test_copied_context_cannot_double_spend(self):
        manager = ApprovalManager(interactive=False)
        args = {'path': 'file'}
        fp = manager.action_fingerprint('host_read_file', args)
        with manager.request_scope([fp]):
            copied = contextvars.copy_context()
            self.assertTrue(manager.approve_exact('host_read_file', args))
            self.assertFalse(copied.run(manager.approve_exact, 'host_read_file', args))
