"""Owner-scoped semantic retrieval using an explicitly installed local model.

No automatic downloads, remote code, remote API calls, or unscoped index reads.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
from sqlite_utils import connect


class LocalEmbedder:
    def __init__(self, path: str):
        model_path=Path(path).expanduser().resolve()
        if not model_path.is_dir():raise ValueError('Install an embedding model locally before enabling semantic memory')
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError('Semantic memory requires the optional sentence-transformers package') from exc
        self.model=SentenceTransformer(str(model_path),local_files_only=True,trust_remote_code=False)
        # Model identity includes a user-supplied revision or deployment fingerprint.
        self.model_id=str(model_path)+':'+os.getenv('AIBA_MEMORY_EMBEDDING_REVISION','1')

    def encode(self,texts):
        return self.model.encode(texts,normalize_embeddings=True,show_progress_bar=False).tolist()


def unit(vector):
    if not isinstance(vector,(list,tuple)) or not vector or len(vector)>16384:
        raise ValueError('Invalid embedding dimension')
    values=[float(x) for x in vector]
    if not all(math.isfinite(x) for x in values):raise ValueError('Embedding must be finite')
    norm=math.sqrt(sum(x*x for x in values))
    if norm==0:raise ValueError('Embedding must be nonzero')
    return [x/norm for x in values]


class SemanticIndex:
    def __init__(self,vault,embedder):
        self.vault=vault;self.embedder=embedder
        with connect(vault.db_path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS memory_embeddings(memory_id INTEGER NOT NULL,model TEXT NOT NULL,content_hash TEXT NOT NULL,vector TEXT NOT NULL,PRIMARY KEY(memory_id,model))')
            db.execute('''CREATE TRIGGER IF NOT EXISTS memory_embedding_delete AFTER DELETE ON memories
                          BEGIN DELETE FROM memory_embeddings WHERE memory_id=old.id; END''')
            db.execute('''CREATE TRIGGER IF NOT EXISTS memory_embedding_update AFTER UPDATE OF content ON memories
                          BEGIN DELETE FROM memory_embeddings WHERE memory_id=old.id; END''')

    def search(self,query,limit=5,as_user=None):
        # Filter identities BEFORE passing text to the model or reading cached vectors.
        rows=self.vault.list(limit=10000,as_user=as_user)
        if not rows:return []
        query_vector=unit(self.embedder.encode([query])[0]);scored=[]
        with connect(self.vault.db_path) as db:
            for row in rows:
                content_hash=hashlib.sha256(row['content'].encode()).hexdigest()
                cached=db.execute('SELECT vector FROM memory_embeddings WHERE memory_id=? AND model=? AND content_hash=?',(row['id'],self.embedder.model_id,content_hash)).fetchone()
                vector=unit(json.loads(cached[0])) if cached else unit(self.embedder.encode([row['content']])[0])
                if len(vector)!=len(query_vector):raise ValueError('Embedding dimensions changed; update the configured model revision')
                if not cached:db.execute('INSERT OR REPLACE INTO memory_embeddings VALUES (?,?,?,?)',(row['id'],self.embedder.model_id,content_hash,json.dumps(vector)))
                similarity=sum(a*b for a,b in zip(query_vector,vector))
                if similarity>=.25:
                    # Importance breaks relevance ties; it cannot swamp relevance.
                    scored.append({**row,'semantic_score':similarity,'rank':similarity+.05*float(row['importance'])})
        return sorted(scored,key=lambda row:(row['rank'],row['id']),reverse=True)[:max(0,int(limit))]
