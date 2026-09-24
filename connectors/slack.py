from __future__ import annotations
import hashlib,hmac,json,os,time,urllib.parse,urllib.request
from connectors.base import MessagingAdapter

def _ids(raw:str)->set[str]:return {x.strip() for x in raw.split(",") if x.strip()}

class SlackConnector(MessagingAdapter):
    channel="slack"
    def __init__(self,agent,bot_token=None,signing_secret=None,allowed_users=None,transport=None):
        self.bot_token=(bot_token or os.getenv("AIBA_SLACK_BOT_TOKEN","")).strip();self.signing_secret=(signing_secret or os.getenv("AIBA_SLACK_SIGNING_SECRET","")).strip()
        if not self.bot_token or not self.signing_secret:raise ValueError("Slack bot token and signing secret are required")
        super().__init__(agent,allowed_users if allowed_users is not None else _ids(os.getenv("AIBA_SLACK_ALLOWED_USERS","")))
        self.transport=transport or self._request
    @classmethod
    def enabled(cls):return os.getenv("AIBA_SLACK_ENABLED","false").lower() in {"1","true","yes","on"}
    def valid_signature(self,body:bytes,timestamp:str,signature:str)->bool:
        try:ts=int(timestamp)
        except Exception:return False
        if abs(int(time.time())-ts)>300:return False
        base=b"v0:"+str(ts).encode()+b":"+body
        expected="v0="+hmac.new(self.signing_secret.encode(),base,hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,signature or "")
    def _request(self,payload):
        req=urllib.request.Request("https://slack.com/api/chat.postMessage",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {self.bot_token}","Content-Type":"application/json; charset=utf-8"})
        with urllib.request.urlopen(req,timeout=30) as response:
            data=json.loads(response.read().decode())
        if not data.get("ok"):raise RuntimeError("Slack API rejected message")
        return data
    def send(self,recipient,text):
        for i in range(0,len(str(text)),3500):self.transport({"channel":recipient,"text":str(text)[i:i+3500],"mrkdwn":False})
    def process_event(self,event:dict)->bool:
        if event.get("type")=="url_verification":return False
        e=event.get("event") or {}
        if e.get("type")!="message" or e.get("subtype") or e.get("bot_id"):return False
        principal=str(e.get("user") or "");channel=str(e.get("channel") or "");text=str(e.get("text") or "")
        if not channel or not self.authorized(principal):return False
        try:answer=self.handle_text(principal,text)
        except Exception as exc:
            crash=self.agent.crashes.capture(exc,{"connector":"slack"});answer=f"AIBA could not complete that request. Crash ID: {crash}"
        if answer:self.send(channel,answer)
        return bool(answer)
