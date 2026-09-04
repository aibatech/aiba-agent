class RetrievalEngine:
    """Scoped memory retrieval used to inject 'Relevant memory' into the model
    context. The acting identity's scope is applied so a model prompt never sees
    memory owned by another principal or 'shared' rows unless it is acting as
    the authorized single-owner/admin (scope None => full operator view).
    ``scope`` is set by AgentLoop._handle from the authenticated connector/API
    user — NOT from any model-supplied argument."""
    def __init__(self,vault,scope=None): self.vault=vault; self.scope=scope
    def retrieve(self,query:str,limit:int=5):
        self.vault.sync_markdown(); return self.vault.search(query,limit,as_user=self.scope)
