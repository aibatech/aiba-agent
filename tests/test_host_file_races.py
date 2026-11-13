import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.host_files import HostFiles, _safe_host_path, _DESCRIPTOR_PATHS


class HostFileRaceTests(unittest.TestCase):
    def test_bounded_read_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'nested'/'note.txt'
            files = HostFiles()
            self.assertTrue(files.write(str(path), 'abcdef').ok)
            result = files.read(str(path), max_chars=3)
            self.assertEqual(result.output['text'], 'abc')
            self.assertTrue(result.output['truncated'])
            self.assertTrue(files.delete(str(path)).ok)
            self.assertFalse(path.exists())

    @unittest.skipUnless(_DESCRIPTOR_PATHS, 'POSIX descriptor-relative path guarantee')
    def test_replaced_parent_cannot_redirect_read_write_or_delete(self):
        for operation in ('read', 'write', 'delete'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); parent=root/'allowed'; parent.mkdir()
                outside=root/'secrets'; outside.mkdir()
                (parent/'note.txt').write_text('approved')
                victim=outside/'note.txt'; victim.write_text('confidential')
                def swap(raw):
                    validated = _safe_host_path(raw)
                    parent.rename(root/'original')
                    parent.symlink_to(outside, target_is_directory=True)
                    return validated
                with patch('tools.host_files._safe_host_path', side_effect=swap):
                    args=[str(parent/'note.txt')]+(['changed'] if operation=='write' else [])
                    result=getattr(HostFiles(),operation)(*args)
                self.assertFalse(result.ok)
                self.assertEqual(victim.read_text(),'confidential')
                self.assertEqual((root/'original'/'note.txt').read_text(),'approved')

    @unittest.skipUnless(_DESCRIPTOR_PATHS, 'POSIX hard-link regression')
    def test_write_does_not_mutate_hard_link_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'original';target.write_text('private')
            alias=root/'alias';os.link(target,alias)
            self.assertTrue(HostFiles().write(str(alias),'new').ok)
            self.assertEqual(target.read_text(),'private')
            self.assertEqual(alias.read_text(),'new')
