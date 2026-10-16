import tempfile,unittest
from pathlib import Path
from tools.secret_admin import SecretAdmin

class SecretAdminTests(unittest.TestCase):
    def test_lists_names_without_values_and_copies_redacted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/"hermes.env";dst=root/"aiba.env"
            src.write_text("GEMINI_API_KEY=super-secret-value\nOTHER_KEY=other-secret\n")
            admin=SecretAdmin();names=admin.list_names(str(src))
            self.assertTrue(names.ok);self.assertIn("GEMINI_API_KEY",names.output["keys"]);self.assertNotIn("super-secret-value",str(names.output))
            copied=admin.copy_env_secret(str(src),str(dst),"GEMINI_API_KEY")
            self.assertTrue(copied.ok);self.assertEqual(copied.output["secret_value"],"[REDACTED]");self.assertNotIn("super-secret-value",str(copied.output))
            self.assertIn("GEMINI_API_KEY=super-secret-value",dst.read_text())
            self.assertNotIn("OTHER_KEY",dst.read_text())

    def test_preserves_unrelated_config_and_comments(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/"source.env";dst=root/"target.env"
            src.write_text("API_KEY=new-value\n")
            dst.write_text("# preserve this\nOTHER_KEY=keep\nAPI_KEY=old-value\n")
            result=SecretAdmin().copy_env_secret(str(src),str(dst),"API_KEY")
            self.assertTrue(result.ok)
            self.assertEqual(dst.read_text(),"# preserve this\nOTHER_KEY=keep\nAPI_KEY=new-value\n")
    def test_refuses_same_file_and_destination_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/"source.env";src.write_text("API_KEY=secret\n")
            self.assertFalse(SecretAdmin().copy_env_secret(str(src),str(src),"API_KEY").ok)
            link=root/"link.env"
            try: link.symlink_to(src)
            except (OSError,NotImplementedError): return
            self.assertFalse(SecretAdmin().copy_env_secret(str(src),str(link),"API_KEY").ok)

    def test_export_spacing_and_quoted_value_replace_existing_assignment(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td)/"src.env", Path(td)/"dst.env"
            src.write_text('export API_KEY = "secret with # spaces" # comment\n')
            dst.write_text('export API_KEY = old\nOTHER_KEY=keep\n')
            result = SecretAdmin().copy_env_secret(str(src), str(dst), "API_KEY")
            self.assertTrue(result.ok)
            self.assertEqual(dst.read_text(), 'API_KEY="secret with # spaces" # comment\nOTHER_KEY=keep\n')
            self.assertNotIn('secret with', str(result))

    def test_ambiguous_or_multiline_source_leaves_destination_untouched(self):
        cases = ['API_KEY="private\ncontinued"\n', 'API_KEY=one\nAPI_KEY=two\n',
                 'API_KEY="private" trailing\n', 'API_KEY=private\x00value\n']
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td)/"src.env", Path(td)/"dst.env"
            for content in cases:
                with self.subTest(content=content):
                    src.write_text(content)
                    dst.write_text('API_KEY=original\n')
                    result = SecretAdmin().copy_env_secret(str(src), str(dst), "API_KEY")
                    self.assertFalse(result.ok)
                    self.assertEqual(dst.read_text(), 'API_KEY=original\n')
                    self.assertNotIn('private', str(result))

    def test_invalid_utf8_does_not_silently_corrupt_secret(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td)/"src.env", Path(td)/"dst.env"
            src.write_bytes(b'API_KEY=private\xff\n')
            result = SecretAdmin().copy_env_secret(str(src), str(dst), "API_KEY")
            self.assertFalse(result.ok)
            self.assertFalse(dst.exists())
            self.assertNotIn('private', str(result))

    def test_oversized_input_is_rejected_without_destination_mutation(self):
        from tools.secret_admin import _MAX_ENV_BYTES
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td)/"src.env", Path(td)/"dst.env"
            src.write_text('API_KEY=' + 'x' * _MAX_ENV_BYTES)
            dst.write_text('API_KEY=original\n')
            self.assertFalse(SecretAdmin().copy_env_secret(str(src), str(dst), 'API_KEY').ok)
            self.assertEqual(dst.read_text(), 'API_KEY=original\n')

    @unittest.skipUnless(__import__('os').name == 'posix', 'POSIX descriptor guarantee')
    def test_replacement_source_symlink_is_refused(self):
        from unittest.mock import patch
        from tools import secret_admin
        with tempfile.TemporaryDirectory() as td:
            src, dst, outside = (Path(td)/name for name in ['src.env','dst.env','outside.env'])
            src.write_text('API_KEY=approved\n');outside.write_text('API_KEY=unapproved\n')
            original = secret_admin._read_env
            def swap(path, parent=None):
                src.unlink();src.symlink_to(outside)
                return original(path, parent)
            with patch.object(secret_admin, '_read_env', side_effect=swap):
                self.assertFalse(SecretAdmin().copy_env_secret(str(src),str(dst),'API_KEY').ok)
            self.assertFalse(dst.exists())

    @unittest.skipUnless(__import__('os').name == 'posix', 'POSIX descriptor guarantee')
    def test_destination_parent_swap_cannot_redirect_secret(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        from tools import secret_admin
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'src.env';src.write_text('API_KEY=approved\n')
            destdir=root/'destination';destdir.mkdir();outside=root/'outside';outside.mkdir()
            moved=root/'original';dest=destdir/'target.env'
            original=secret_admin._parent_descriptor
            @contextmanager
            def swap(path, create=False):
                with original(path,create=create) as fd:
                    if create:
                        destdir.rename(moved);destdir.symlink_to(outside,target_is_directory=True)
                    yield fd
            with patch.object(secret_admin,'_parent_descriptor',side_effect=swap):
                result=SecretAdmin().copy_env_secret(str(src),str(dest),'API_KEY')
            self.assertTrue(result.ok)
            self.assertFalse((outside/'target.env').exists())
            self.assertEqual((moved/'target.env').read_text(),'API_KEY=approved\n')
            self.assertEqual((moved/'target.env').stat().st_mode & 0o777,0o600)

    @unittest.skipUnless(__import__('os').name == 'posix', 'POSIX FIFO fixture')
    def test_destination_fifo_is_refused_without_blocking(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            src,dst=Path(td)/'src.env',Path(td)/'dst.env'
            src.write_text('API_KEY=approved\n');os.mkfifo(dst)
            self.assertFalse(SecretAdmin().copy_env_secret(str(src),str(dst),'API_KEY').ok)

if __name__=="__main__":unittest.main()
