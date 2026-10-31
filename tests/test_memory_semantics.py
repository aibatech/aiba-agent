import tempfile
import unittest
from pathlib import Path
from memory.vault import MemoryVault
from memory.retrieval import RetrievalEngine
from sqlite_utils import connect

class Embedder:
    model_id='deterministic-test-semantic-model'
    def __init__(self):self.seen=[]
    def encode(self,texts):
        self.seen+=texts
        return [[1,0] if any(w in t.lower() for w in ('automobile','vehicle','car')) else [0,1] for t in texts]

class MemorySemanticsTests(unittest.TestCase):
    def test_semantic_path_cache_update_delete_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'m.db',root/'vault')
            mid=vault.add('My automobile is electric',owner='alice')
            vault.add('Bob private vehicle',owner='bob')
            embedder=Embedder();engine=RetrievalEngine(vault,scope='alice',embedder=embedder)
            self.assertEqual(engine.retrieve('car')[0]['id'],mid)
            self.assertNotIn('Bob private vehicle',embedder.seen)
            embedder.seen=[];engine.retrieve('car');self.assertEqual(embedder.seen,['car'])
            vault.update(mid,content='I like swimming',as_user='alice')
            self.assertEqual(engine.retrieve('car'),[])
            vault.remove(mid,as_user='alice')
            with connect(vault.db_path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM memory_embeddings').fetchone()[0],0)

    def test_fact_replacement_is_atomic_scoped_persistent_and_auditable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'m.db',root/'vault')
            old=vault.add('Atlas deadline June',owner='alice',fact_key='atlas.deadline')
            new=vault.add('Atlas deadline July',owner='alice',fact_key='atlas.deadline')
            self.assertEqual(new,vault.add('Atlas deadline July',owner='alice',fact_key='atlas.deadline'))
            vault.add('Atlas deadline May',owner='bob',fact_key='atlas.deadline')
            restarted=MemoryVault(root/'m.db',root/'vault')
            self.assertEqual([r['id'] for r in restarted.search('Atlas',as_user='alice')],[new])
            self.assertEqual(len(restarted.fact_history('atlas.deadline','alice')),2)
            self.assertIsNone(restarted.get(old,as_user='alice'))
            self.assertFalse(restarted.remove(old,as_user="bob"))
            self.assertTrue(restarted.remove(old,as_user="alice"))
            self.assertEqual(len(restarted.fact_history("atlas.deadline","alice")),1)
            self.assertIn('May',restarted.search('Atlas',as_user='bob')[0]['content'])

    def test_context_budget_does_not_include_unbounded_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=MemoryVault(root/'m.db',root/'vault')
            vault.add('Atlas '+('x'*1000),owner='alice')
            vault.add('Atlas short goal',owner='alice')
            rows=RetrievalEngine(vault,scope='alice',char_budget=400).retrieve('Atlas')
            self.assertEqual([r['content'] for r in rows],['Atlas short goal'])
            self.assertEqual(RetrievalEngine(vault,scope='alice').retrieve('Atlas',0),[])
