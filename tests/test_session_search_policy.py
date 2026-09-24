import json,unittest
from pathlib import Path
class SessionPolicyTests(unittest.TestCase):
    def test_default_off_explicit_only(self):
        root=Path(__file__).resolve().parents[1];p=json.loads((root/"config"/"permissions.json").read_text());m=json.loads((root/"config"/"capability_manifest.json").read_text());loop=(root/"agent"/"loop.py").read_text()
        self.assertFalse(p["tools"]["session_search"]["enabled"]);self.assertFalse(p["tools"]["session_history"]["enabled"]);self.assertEqual(m["tools"]["session_search"]["feature_flag"],"AIBA_SESSION_SEARCH_ENABLED");self.assertIn("self.sessions.search",loop);self.assertIn("RetrievalEngine(self.vault)",loop);self.assertNotIn("RetrievalEngine(self.sessions)",loop)
if __name__=="__main__":unittest.main()
