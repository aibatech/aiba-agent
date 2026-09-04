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
        # Mirror the production SecurityPolicy: resolve the workspace ONCE so
        # comparisons are symmetric with the already-resolved path the sandbox
        # produces. Not resolving this is a real bug on macOS (/var -> /private/var
        # symlink) and Windows (drive/UNC/long-path canonicalization) where the
        # temp dir's unresolved form differs from Path.resolve(); unresolved vs
        # resolved then falsely reject legitimate in-workspace files as "outside".
        self.workspace = Path(workspace).resolve()

    def check_path(self, path):
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
        # Archive is inside workspace. Resolve the workspace root the same way
        # the sandbox/`_Policy` do (macOS /var -> /private/var, Windows
        # RUNNER~1 -> full name) so unresolved-vs-resolved forms don't falsely
        # reject a legitimate in-workspace path as "outside".
        ws_root = self.ws.resolve()
        try:
            archive.resolve().relative_to(ws_root)
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

    def test_extract_blocks_absolute_tar_member(self):
        # A tar member with an absolute path must not write outside dest.
        import io, tarfile
        escape = self.ws.parent / "abs_escape.txt"
        evil = self.ws / "abs.tar"
        with tarfile.open(evil, "w") as t:
            info = tarfile.TarInfo(str(escape))
            info.size = len(b"pwned")
            t.addfile(info, io.BytesIO(b"pwned"))
        res = self.sb.extract_archive("abs.tar", ".out")
        self.assertFalse(res.ok)
        self.assertFalse(escape.exists())

    def test_extract_blocks_tar_symlink_escape(self):
        # A symlink member pointing outside dest must be rejected, not followed.
        import io, tarfile
        escape = self.ws.parent / "link_escape.txt"
        escape.write_text("target")
        evil = self.ws / "link.tar"
        with tarfile.open(evil, "w") as t:
            info = tarfile.TarInfo(".out/escape.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = str(escape)  # absolute symlink -> outside
            t.addfile(info)
        res = self.sb.extract_archive("link.tar", ".out2")
        self.assertFalse(res.ok)
        self.assertFalse((self.ws / ".out2" / "escape.txt").resolve().exists())

    def test_extract_blocks_zip_windows_drive_path(self):
        # A drive-qualified member (Windows) must be rejected on every OS.
        evil = self.ws / "drive.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("C:/pwned.txt", "x")
        res = self.sb.extract_archive("drive.zip", ".out")
        self.assertFalse(res.ok)
        self.assertFalse((self.ws / ".out" / "C:" / "pwned.txt").exists())

    def test_extract_blocks_zip_backslash_traversal(self):
        # Windows-style backslash traversal must be rejected even on POSIX.
        evil = self.ws / "bs.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("..\\..\\escape.txt", "x")
        res = self.sb.extract_archive("bs.zip", ".out")
        self.assertFalse(res.ok)
        self.assertFalse((self.ws.parent.parent / "escape.txt").exists())

    def test_extract_does_not_follow_preexisting_dest_symlink(self):
        # A pre-seeded symlink at the destination must not redirect the write out.
        evil = self.ws / "sym.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("escape.txt", "pwned")
        outdir = self.ws / ".out"
        outdir.mkdir(exist_ok=True)
        escape = self.ws.parent / "destsym_escape.txt"
        (outdir / "escape.txt").symlink_to(escape)  # dest is a symlink to outside
        res = self.sb.extract_archive("sym.zip", ".out")
        self.assertFalse(res.ok)
        self.assertFalse(escape.exists())  # write must NOT land on the target

    def test_extract_rejects_tar_fifo_member(self):
        # A FIFO (mkfifo) special member must be rejected, not created.
        import io, tarfile
        evil = self.ws / "fifo.tar"
        with tarfile.open(evil, "w") as t:
            info = tarfile.TarInfo("fifo")
            info.type = tarfile.FIFOTYPE
            t.addfile(info)
        res = self.sb.extract_archive("fifo.tar", ".out")
        self.assertFalse(res.ok)
        self.assertIn("special member", res.error or "")

    def test_extract_rejects_oversized_tar_member(self):
        # A member exceeding the configured per-file size limit must be rejected
        # before writing (archive-bomb per-file protection), with no file left.
        import io, tarfile
        sb_small = Sandbox(self.ws, timeout=10, policy=self.policy, mode="local",
                           max_archive_bytes_per_file=100)  # tight per-file bound
        evil = self.ws / "huge.tar"
        with tarfile.open(evil, "w") as t:
            info = tarfile.TarInfo("big.bin")
            info.size = 300  # > 100-byte configured limit
            t.addfile(info, io.BytesIO(b"x" * 300))
        res = sb_small.extract_archive("huge.tar", ".out")
        self.assertFalse(res.ok)
        self.assertIn("per-file", res.error or "")
        self.assertFalse((self.ws / ".out" / "big.bin").exists())

    def test_extract_rejects_total_archive_bomb(self):
        # Sum of members exceeding the configured total size limit must reject.
        import io, tarfile
        sb_small = Sandbox(self.ws, timeout=10, policy=self.policy, mode="local",
                           max_archive_total_bytes=200)  # tight total bound
        evil = self.ws / "bomb.tar"
        with tarfile.open(evil, "w") as t:
            for i in range(3):
                info = tarfile.TarInfo(f"f{i}.bin")
                info.size = 100
                t.addfile(info, io.BytesIO(b"x" * 100))
        res = sb_small.extract_archive("bomb.tar", ".out")
        self.assertFalse(res.ok)
        self.assertIn("total expanded", res.error or "")
        # Partial state rolled back: nothing from this call remains.
        self.assertFalse((self.ws / ".out" / "f0.bin").exists())

    def test_extract_rejects_excess_member_count(self):
        # More members than the configured count limit must reject.
        import io, tarfile
        sb_small = Sandbox(self.ws, timeout=10, policy=self.policy, mode="local",
                           max_archive_members=5)  # tight member-count bound
        evil = self.ws / "many.tar"
        with tarfile.open(evil, "w") as t:
            for i in range(10):
                info = tarfile.TarInfo(f"m{i}.bin")
                info.size = 1
                t.addfile(info, io.BytesIO(b"z"))
        res = sb_small.extract_archive("many.tar", ".out")
        self.assertFalse(res.ok)
        self.assertIn("member count", res.error or "")
        self.assertFalse((self.ws / ".out" / "m0.bin").exists())

    def test_extract_rolls_back_partial_on_rejection(self):
        # Files written before an unsafe member must be removed (no partial state).
        evil = self.ws / "mix.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("good.bin", "ok")
            z.writestr("../escape.txt", "bad")  # appears after a good member
        res = self.sb.extract_archive("mix.zip", ".out")
        self.assertFalse(res.ok)
        self.assertIn("rolled back", res.error or "")
        self.assertFalse((self.ws / ".out" / "good.bin").exists())
        self.assertFalse((self.ws.parent / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
