"""Uniform security contract for external messaging surfaces."""
from __future__ import annotations
from abc import ABC,abstractmethod

class MessagingAdapter(ABC):
    channel="unknown"
    def __init__(self,agent,allowed_principals:set[str]):
        self.agent=agent
        self.allowed_principals={str(x) for x in allowed_principals if str(x)}
        if not self.allowed_principals:
            raise ValueError(f"{self.channel} owner allowlist must not be empty")
    def authorized(self,principal:str)->bool:return str(principal) in self.allowed_principals
    def user_id(self,principal:str)->str:return f"{self.channel}:{principal}"
    def handle_text(self,principal:str,text:str)->str|None:
        if not self.authorized(principal) or not str(text).strip():return None
        # External adapters deliberately use the ordinary remote/non-interactive
        # path. They never auto-approve approval-requiring tools.
        return self.agent.handle(str(text).strip(),user_id=self.user_id(principal),onboard=True)
    @classmethod
    @abstractmethod
    def enabled(cls)->bool: ...
    @abstractmethod
    def send(self,recipient:str,text:str)->None: ...
