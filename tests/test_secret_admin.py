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

if __name__=="__main__":unittest.main()
