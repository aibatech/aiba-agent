from __future__ import annotations
from dataclasses import dataclass
@dataclass
class Memory:
    id: int|None
    content: str
    category: str='general'
    importance: float=0.5
    created_at: str|None=None
    metadata: str='{}'
