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

if __name__=="__main__":unittest.main()
