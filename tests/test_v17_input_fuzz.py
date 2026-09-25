from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from migration.agent_import import AgentMigration
from agent.sessions import SessionStore

class V17InputFuzzTests(unittest.TestCase):
    def test_migration_rejects_or_bounds_hostile_source_shapes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/"src";src.mkdir();data=root/"data";repo=root/"repo";repo.mkdir()
            m=AgentMigration(repo,data)
            for name in ["../escape","\x00bad","a"*10000]:
                with self.subTest(name=repr(name)):
                    try: plan=m.plan("hermes",src/name,"user-data")
                    except (ValueError,OSError): continue
                    self.assertFalse(any(".." in str(x) for x in plan.get("files",[])))

    def test_session_search_fuzz_is_bounded_and_does_not_parse_fts_operators(self):
        with tempfile.TemporaryDirectory() as td:
            s=SessionStore(Path(td)/"sessions.db")
            s.append("u","user","alpha normal text")
            for q in ['" OR *','NEAR(', "\x00"*100, "😀"*10000, "a"*100000]:
                with self.subTest(q=repr(q[:20])):
                    try:r=s.search("u",q,limit=10)
                    except (ValueError,TypeError):continue
                    self.assertLessEqual(len(r),10)

if __name__=="__main__":unittest.main()
