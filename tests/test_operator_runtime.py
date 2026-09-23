import tempfile
import unittest
from pathlib import Path

from runtime.operator import OperatorRuntime
from integrations.connectors import ConnectorRegistry


class OperatorRuntimeTests(unittest.TestCase):
    def test_lifecycle_steering_cancel_and_verification(self):
        with tempfile.TemporaryDirectory() as td:
            op=OperatorRuntime(Path(td)/"operator.db")
            task=op.create("research competitors", owner="u1")
            op.set_status(task,"running")
            op.steer(task,"focus on privacy")
            self.assertEqual(op.consume_steering(task),["focus on privacy"])
            self.assertEqual(op.consume_steering(task),[])
            op.verify(task,"report saved","workspace/report.md exists",True)
            status=op.status(task,owner="u1")
            self.assertEqual(status["status"],"running")
            self.assertTrue(status["verifications"][0]["passed"])
            op.cancel(task)
            self.assertEqual(op.status(task)["status"],"cancelled")

    def test_owner_scope(self):
        with tempfile.TemporaryDirectory() as td:
            op=OperatorRuntime(Path(td)/"operator.db")
            task=op.create("private", owner="u1")
            with self.assertRaises(KeyError):
                op.status(task,owner="u2")

    def test_connector_catalog_defaults_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"connectors.json"
            p.write_text('{"version":1,"connectors":{"gmail":{"enabled":false,"kind":"mcp","server":"google","tools":{}}}}')
            reg=ConnectorRegistry(p)
            self.assertFalse(reg.list()[0]["enabled"])
            with self.assertRaises(ValueError):
                reg.call("gmail","send",{})


if __name__ == "__main__":
    unittest.main()
