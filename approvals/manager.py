from __future__ import annotations
from typing import Callable

class ApprovalManager:
    def __init__(self, interactive: bool=True, auto_approve: bool=False, input_fn: Callable[[str],str]=input):
        self.interactive=interactive; self.auto_approve=auto_approve; self.input_fn=input_fn
    def approve(self, action: str, reason: str="") -> bool:
        if self.auto_approve: return True
        if not self.interactive: return False
        detail=f" ({reason})" if reason else ""
        return self.input_fn(f"Approve {action}{detail}? [y/N] ").strip().lower() in {"y","yes"}
