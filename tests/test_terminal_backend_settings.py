import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from config.settings import Settings,SettingsError

class TerminalBackendSettingsTests(unittest.TestCase):
    def test_ssh_backend_requires_second_feature_gate(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"AIBA_ROOT":td,"AIBA_SANDBOX_MODE":"ssh","AIBA_TERMINAL_BACKENDS_ENABLED":"false"},clear=False):
            with self.assertRaises(SettingsError):Settings.load()

if __name__=="__main__":unittest.main()
