class RetrievalEngine:
    def __init__(self,vault): self.vault=vault
    def retrieve(self,query:str,limit:int=5): self.vault.sync_markdown(); return self.vault.search(query,limit)
