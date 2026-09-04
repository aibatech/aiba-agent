"""Tests for SkillManager versioning/revision/rollback (Phase 9)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skills.manager import SkillManager


class SkillVersioningTests(unittest.TestCase):
    STEPS_V1 = [{"tool": "read_file", "arguments": {}}]
    STEPS_V2 = [{"tool": "read_file", "arguments": {}},
                {"tool": "write_file", "arguments": {}}]

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="aiba_skill_")
        self.mgr = SkillManager(Path(self._dir) / "skills")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_upgrade_snapshots_prior_version(self):
        self.mgr.create("fmt", "v1", self.STEPS_V1, version="0.1.0")
        self.mgr.create("fmt", "v2", self.STEPS_V2, version="0.2.0")
        revs = self.mgr.revisions("fmt")
        self.assertEqual([r["version"] for r in revs], ["0.1.0"])
        self.assertEqual(revs[0]["steps"], 1)
        self.assertEqual(self.mgr.get("fmt").version, "0.2.0")

    def test_recreate_same_version_does_not_duplicate_revision(self):
        self.mgr.create("fmt", "v1", self.STEPS_V1, version="0.1.0")
        # same-version rewrite must not snapshot itself onto revisions
        self.mgr.create("fmt", "v1b", self.STEPS_V1, version="0.1.0")
        self.assertEqual(self.mgr.revisions("fmt"), [])

    def test_rollback_restores_and_preserves_current(self):
        self.mgr.create("fmt", "v1", self.STEPS_V1, version="0.1.0")
        self.mgr.create("fmt", "v2", self.STEPS_V2, version="0.2.0")
        rolled = self.mgr.rollback("fmt", "0.1.0")
        self.assertEqual(rolled.version, "0.1.0")
        self.assertEqual(len(rolled.steps), 1)
        # the v2 snapshot is preserved after rollback
        versions = {r["version"] for r in self.mgr.revisions("fmt")}
        self.assertIn("0.2.0", versions)

    def test_rollback_missing_raises(self):
        self.mgr.create("fmt", "v1", self.STEPS_V1, version="0.1.0")
        with self.assertRaises(KeyError):
            self.mgr.rollback("fmt", "9.9.9")

    def test_revision_files_are_valid_records(self):
        self.mgr.create("fmt", "v1", self.STEPS_V1, version="0.1.0")
        self.mgr.create("fmt", "v2", self.STEPS_V2, version="0.2.0")
        revfile = (Path(self._dir) / "skills" / "fmt" / "revisions" / "0.1.0.json")
        data = json.loads(revfile.read_text())
        self.assertEqual(data["version"], "0.1.0")
        self.assertEqual(data["description"], "v1")


if __name__ == "__main__":
    unittest.main()
