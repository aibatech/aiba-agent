import tempfile,unittest
from pathlib import Path
from agent.sessions import SessionStore
class SessionSearchTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.s=SessionStore(Path(self.t.name)/"sessions.db")
    def tearDown(self):self.t.cleanup()
    def test_user_scope_and_bounds(self):
        for i in range(40):sid=self.s.open_session("alice",f"project alpha {i}");self.s.append(sid,summary=f"alpha result {i}")
        sid=self.s.open_session("bob","project alpha secret");self.s.append(sid,summary="alpha bob-only");rows=self.s.search("alice","alpha",9999)
        self.assertEqual(len(rows),25);self.assertTrue(all(x["user_key"]=="alice" for x in rows));self.assertTrue(all("bob-only" not in (x.get("summary") or "") for x in rows))
    def test_query_sanitized(self):
        sid=self.s.open_session("alice","needle");self.s.append(sid,summary="needle result");self.assertTrue(self.s.search("alice",'needle" OR *',10));self.assertEqual(self.s.search("alice","***",10),[])
    def test_history_bound(self):
        for i in range(80):self.s.open_session("alice",str(i))
        self.assertEqual(len(self.s.list_by_user("alice",100000)),50)
if __name__=="__main__":unittest.main()
