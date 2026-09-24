from __future__ import annotations
import json,os,urllib.request
from connectors.base import MessagingAdapter

def _ids(raw:str)->set[str]:return {x.strip() for x in raw.split(",") if x.strip()}

class DiscordConnector(MessagingAdapter):
    channel="discord"
    def __init__(self,agent,token=None,allowed_users=None,transport=None):
        self.token=(token or os.getenv("AIBA_DISCORD_BOT_TOKEN","")).strip()
        if not self.token:raise ValueError("AIBA_DISCORD_BOT_TOKEN is required")
        super().__init__(agent,allowed_users if allowed_users is not None else _ids(os.getenv("AIBA_DISCORD_ALLOWED_USERS","")))
        self.transport=transport or self._request
    @classmethod
    def enabled(cls):return os.getenv("AIBA_DISCORD_ENABLED","false").lower() in {"1","true","yes","on"}
    def _request(self,method,path,payload=None):
        req=urllib.request.Request("https://discord.com/api/v10"+path,data=None if payload is None else json.dumps(payload).encode(),method=method,headers={"Authorization":f"Bot {self.token}","Content-Type":"application/json","User-Agent":"AIBA-Agent"})
        with urllib.request.urlopen(req,timeout=30) as response:return json.loads(response.read().decode() or "{}")
    def send(self,recipient,text):
        for i in range(0,len(str(text)),1900):self.transport("POST",f"/channels/{recipient}/messages",{"content":str(text)[i:i+1900]})
    def process_event(self,event:dict)->bool:
        # Gateway/webhook orchestration may feed MESSAGE_CREATE events here.
        if event.get("t")!="MESSAGE_CREATE":return False
        m=event.get("d") or {};author=m.get("author") or {}
        principal=str(author.get("id") or "");channel=str(m.get("channel_id") or "");text=str(m.get("content") or "")
        if author.get("bot") or not channel or not self.authorized(principal):return False
        try:answer=self.handle_text(principal,text)
        except Exception as exc:
            crash=self.agent.crashes.capture(exc,{"connector":"discord"});answer=f"AIBA could not complete that request. Crash ID: {crash}"
        if answer:self.send(channel,answer)
        return bool(answer)
