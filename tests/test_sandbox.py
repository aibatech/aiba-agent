"""Tests for Phase 6 additions: patch, archive, extract (sandbox tools)."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.sandbox import Sandbox
from tools.base import ToolResult


class _Policy:
    def __init__(self, workspace):
        self.workspace = workspace

    def check_path(self, path):
        from pathlib import Path
        try:
            Path(path).resolve().relative_to(self.workspace)
        except ValueError:
            return type("D", (), {"allowed": False, "reason": "outside"})()
        return type("D", (), {"allowed": True, "reason": ""})()

    def check_command(self, c):
        return type("D", (), {"allowed": True, "requires_approval": False, "reason": ""})()


class SandboxFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.policy = _Policy(self.ws)
        self.sb = Sandbox(self.ws, timeout=10, policy=self.policy, mode="local")

    def tearDown(self):
        self.tmp.cleanup()


class PatchFileTests(SandboxFixture):
    def test_patch_applies_and_returns_diff(self):
        f = self.ws / "a.txt"
        f.write_text("hello brave world\nhappy world\n")
        res = self.sb.patch_file("a.txt", "brave world", "cruel world")
        self.assertTrue(res.ok)
        self.assertEqual(res.output["replacements"], 1)
        self.assertIn("hello cruel world", f.read_text())
        self.assertIn("-hello brave world", res.output["diff"])

    def test_patch_multiple_requires_replace_all(self):
        f = self.ws / "b.txt"
        f.write_text("x x x\n")
        res = self.sb.patch_file("b.txt", "x", "y")
        self.assertFalse(res.ok)
        self.assertIn("replace_all", res.error or "")

    def test_patch_replace_all(self):
        f = self.ws / "c.txt"
        f.write_text("x x x\n")
        res = self.sb.patch_file("c.txt", "x", "y", replace_all=True)
        self.assertTrue(res.ok)
        self.assertEqual(res.output["replacements"], 3)
        self.assertEqual(f.read_text(), "y y y\n")

    def test_patch_not_found(self):
        self.sb.write_file("d.txt", "abc")
        res = self.sb.patch_file("d.txt", "zzz", "y")
        self.assertFalse(res.ok)
        self.assertIn("not found", res.error or "")

    def test_patch_empty_old_rejected(self):
        self.sb.write_file("e.txt", "abc")
        res = self.sb.patch_file("e.txt", "", "y")
        self.assertFalse(res.ok)

    def test_patch_blocks_outside_workspace(self):
        outside = Path(tempfile.gettempdir()) / "aiba_outside_test.txt"
        outside.write_text("hello")
        try:
            # _safe raises before any read/write for paths outside the workspace.
            with self.assertRaises(PermissionError):
                self.sb.patch_file("../" + outside.name, "hello", "bye")
        finally:
            outside.unlink(missing_ok=True)


class ArchiveTests(SandboxFixture):
    def test_archive_zip_roundtrip(self):
        (self.ws / "data").mkdir(parents=True)
        (self.ws / "data" / "f1.txt").write_text("one")
        (self.ws / "data" / "f2.txt").write_text("two")
        res = self.sb.archive("data", format="zip", name="snapshot")
        self.assertTrue(res.ok)
        archive_rel = res.output["archive"]
        archive = self.ws / archive_rel
        self.assertTrue(archive.exists())
        # Archive is inside workspace
        try:
            archive.resolve().relative_to(self.ws)
        except ValueError:
            self.fail("archive written outside workspace")

    def test_archive_invalid_format(self):
        (self.ws / "data").mkdir()
        (self.ws / "data" / "f").write_text("x")
        res = self.sb.archive("data", format="rar")
        self.assertFalse(res.ok)

    def test_extract_roundtrip(self):
        (self.ws / "pkg").mkdir()
        (self.ws / "pkg" / "m.txt").write_text("mod")
        res = self.sb.archive("pkg", format="zip", name="pk")
        archive = self.ws / res.output["archive"]
        ex = self.sb.extract_archive(str(res.output["archive"]), ".out")
        self.assertTrue(ex.ok)
        self.assertTrue((self.ws / ".out" / "pkg" / "m.txt").exists())

    def test_extract_blocks_zip_slip(self):
        # Craft a malicious zip with a ../ member.
        evil = self.ws / "evil.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("../escape.txt", "pwned")
        res = self.sb.extract_archive("evil.zip", ".out")
        self.assertFalse(res.ok)
        self.assertFalse((self.ws.parent / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
