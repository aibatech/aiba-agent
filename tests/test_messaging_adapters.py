from __future__ import annotations
import hashlib,hmac,json,time
import pytest
from connectors.base import MessagingAdapter
from connectors.discord import DiscordConnector
from connectors.slack import SlackConnector

class Agent:
    def __init__(self):self.calls=[];self.crashes=type("C",(),{"capture":lambda s,e,c:"x"})()
    def handle(self,text,user_id=None,onboard=False):self.calls.append((text,user_id,onboard));return "ok"

class Dummy(MessagingAdapter):
    channel="dummy"
    @classmethod
    def enabled(cls):return False
    def send(self,recipient,text):pass

def test_adapter_fails_closed_without_allowlist():
    with pytest.raises(ValueError):Dummy(Agent(),set())

def test_adapter_scopes_remote_identity():
    a=Agent();d=Dummy(a,{"7"})
    assert d.handle_text("8","no") is None
    assert d.handle_text("7","hi")=="ok"
    assert a.calls==[("hi","dummy:7",True)]

def test_discord_owner_allowlist_and_plain_send():
    sent=[];a=Agent();d=DiscordConnector(a,"token",{"7"},lambda m,p,payload=None:sent.append((m,p,payload)) or {})
    assert not d.process_event({"t":"MESSAGE_CREATE","d":{"author":{"id":"8"},"channel_id":"c","content":"x"}})
    assert d.process_event({"t":"MESSAGE_CREATE","d":{"author":{"id":"7"},"channel_id":"c","content":"hello"}})
    assert sent[-1][2]["content"]=="ok"

def test_slack_signature_and_owner_allowlist(monkeypatch):
    now=1700000000;monkeypatch.setattr(time,"time",lambda:now)
    body=b'{"x":1}';secret="secret";sig="v0="+hmac.new(secret.encode(),b"v0:"+str(now).encode()+b":"+body,hashlib.sha256).hexdigest()
    a=Agent();sent=[];s=SlackConnector(a,"xoxb",secret,{"U1"},lambda p:sent.append(p) or {"ok":True})
    assert s.valid_signature(body,str(now),sig)
    assert not s.valid_signature(body,str(now-600),sig)
    assert not s.process_event({"event":{"type":"message","user":"U2","channel":"C","text":"x"}})
    assert s.process_event({"event":{"type":"message","user":"U1","channel":"C","text":"hi"}})
    assert sent[-1]["mrkdwn"] is False
