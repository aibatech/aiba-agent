from pathlib import Path
import json

def test_session_retrieval_is_default_off_and_explicit_query_only():
    root=Path(__file__).resolve().parents[1]
    permissions=json.loads((root/"config"/"permissions.json").read_text())
    manifest=json.loads((root/"config"/"capability_manifest.json").read_text())
    assert permissions["tools"]["session_search"]["enabled"] is False
    assert permissions["tools"]["session_history"]["enabled"] is False
    assert manifest["tools"]["session_search"]["feature_flag"]=="AIBA_SESSION_SEARCH_ENABLED"
    loop=(root/"agent"/"loop.py").read_text()
    assert "self.sessions.search" in loop
    # Session FTS is exposed as a tool; it is not injected into RetrievalEngine.
    assert "RetrievalEngine(self.vault)" in loop
    assert "RetrievalEngine(self.sessions)" not in loop
