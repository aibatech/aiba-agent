from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
@dataclass
class ToolResult:
    ok: bool; output: Any=None; error: str|None=None
    verified: bool|None=None
@dataclass
class Tool:
    name: str; description: str; handler: Callable[...,ToolResult]; parameters: dict[str,Any]
    verifier: Callable[[dict[str,Any], ToolResult], bool]|None = None
    def run(self,**kwargs:Any)->ToolResult:
        try:return self.handler(**kwargs)
        except Exception as exc:return ToolResult(False,error=f'{type(exc).__name__}: {exc}')
