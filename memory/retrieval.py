from __future__ import annotations
import os
from memory.semantic import LocalEmbedder, SemanticIndex


class RetrievalEngine:
    """Identity-scoped, bounded hybrid memory selection. Local semantic model is opt-in."""
    def __init__(self,vault,scope=None,embedder=None,char_budget=12000):
        self.vault=vault;self.scope=scope;self.char_budget=char_budget
        model=os.getenv('AIBA_MEMORY_EMBEDDING_MODEL','').strip()
        self.semantic=SemanticIndex(vault,embedder or LocalEmbedder(model)) if embedder is not None or model else None

    def retrieve(self,query:str,limit:int=5):
        if limit <= 0 or self.char_budget <= 0:return []
        self.vault.sync_markdown()
        lexical=self.vault.search(query,max(limit*3,10),as_user=self.scope)
        semantic=self.semantic.search(query,max(limit*3,10),as_user=self.scope) if self.semantic else []
        candidates={};scores={}
        # Reciprocal-rank fusion avoids comparing incompatible BM25 and cosine scales.
        for results in (lexical,semantic):
            for rank,row in enumerate(results):
                mid=row['id'];candidates[mid]=row;scores[mid]=scores.get(mid,0)+1/(60+rank)
        selected=[];used=0;seen=set()
        for mid in sorted(scores,key=lambda mid:(scores[mid],float(candidates[mid]['importance'])),reverse=True):
            row=candidates[mid];normalized=' '.join(row['content'].casefold().split())
            if normalized in seen:continue
            cost=len(row['content'])
            if cost>self.char_budget-used:continue
            selected.append(row);seen.add(normalized);used+=cost
            if len(selected)>=limit:break
        return selected
