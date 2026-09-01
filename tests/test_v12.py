import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from onboarding.setup import SetupManager
from updates.manager import UpdateError, UpdateManager


class SetupTests(unittest.TestCase):
    def test_secure_configuration_is_generated_once(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            manager = SetupManager(root, root / "data")
            first = manager.ensure_configuration()
            token = os.environ["AIBA_API_TOKEN"]
            master = os.environ["AIBA_MASTER_KEY"]
            second = manager.ensure_configuration()
            self.assertEqual(set(first["generated"]), {"AIBA_API_TOKEN", "AIBA_MASTER_KEY"})
            self.assertEqual(second["generated"], [])
            self.assertGreaterEqual(len(token), 48)
            self.assertGreaterEqual(len(master), 48)
            self.assertNotEqual(token, master)
            if os.name != "nt":
                self.assertEqual(root.joinpath(".env").stat().st_mode & 0o777, 0o600)

    def test_setup_completion_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = SetupManager(root, root / "data")
            self.assertFalse(manager.status()["complete"])
            manager.complete()
            self.assertTrue(manager.status(provider_count=1)["complete"])


class UpdateTests(unittest.TestCase):
    @staticmethod
    def archive(version="1.2.1", unsafe=False):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("../escape" if unsafe else "aiba/VERSION", version)
            if not unsafe:
                archive.writestr("aiba/marker.txt", "updated")
        return data.getvalue()

    def test_verified_update_stages_and_applies_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("1.2.0")
            (root / "marker.txt").write_text("old")
            (root / ".env").write_text("SECRET=preserved")
            payload = self.archive()
            manifest = {"version": "1.2.1", "url": "https://example.test/aiba.zip", "sha256": hashlib.sha256(payload).hexdigest()}
            manager = UpdateManager(root, root / "agent_system")
            with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                self.assertTrue(manager.stage(manifest)["staged"])
            result = manager.apply_staged()
            self.assertTrue(result["applied"])
            self.assertEqual((root / "VERSION").read_text(), "1.2.1")
            self.assertEqual((root / "marker.txt").read_text(), "updated")
            self.assertEqual((root / ".env").read_text(), "SECRET=preserved")
            self.assertEqual((root / "agent_system/update-backups/1.2.0/marker.txt").read_text(), "old")

    def test_unsafe_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("1.2.0")
            payload = self.archive(unsafe=True)
            manifest = {"version": "1.2.1", "url": "https://example.test/aiba.zip", "sha256": hashlib.sha256(payload).hexdigest()}
            manager = UpdateManager(root, root / "data")
            with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaises(UpdateError):
                    manager.stage(manifest)

    def test_non_https_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"AIBA_UPDATE_MANIFEST_URL": "http://example.test/manifest.json"}):
            root = Path(tmp)
            (root / "VERSION").write_text("1.2.0")
            with self.assertRaises(UpdateError):
                UpdateManager(root, root / "data").check()


if __name__ == "__main__":
    unittest.main()
