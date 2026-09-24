from __future__ import annotations
import hashlib,hmac,time,unittest
from unittest.mock import patch
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
class MessagingTests(unittest.TestCase):
    def test_allowlist(self):
        with self.assertRaises(ValueError):Dummy(Agent(),set())
        a=Agent();d=Dummy(a,{"7"});self.assertIsNone(d.handle_text("8","no"));self.assertEqual(d.handle_text("7","hi"),"ok");self.assertEqual(a.calls,[("hi","dummy:7",True)])
    def test_discord(self):
        sent=[];d=DiscordConnector(Agent(),"token",{"7"},lambda m,p,payload=None:sent.append((m,p,payload)) or {})
        self.assertFalse(d.process_event({"t":"MESSAGE_CREATE","d":{"author":{"id":"8"},"channel_id":"c","content":"x"}}));self.assertTrue(d.process_event({"t":"MESSAGE_CREATE","d":{"author":{"id":"7"},"channel_id":"c","content":"hello"}}));self.assertEqual(sent[-1][2]["content"],"ok")
    def test_slack_signature_and_allowlist(self):
        now=1700000000;body=b'{"x":1}';secret="secret";sig="v0="+hmac.new(secret.encode(),b"v0:"+str(now).encode()+b":"+body,hashlib.sha256).hexdigest();sent=[];s=SlackConnector(Agent(),"xoxb",secret,{"U1"},lambda p:sent.append(p) or {"ok":True})
        with patch("time.time",return_value=now):self.assertTrue(s.valid_signature(body,str(now),sig));self.assertFalse(s.valid_signature(body,str(now-600),sig))
        self.assertFalse(s.process_event({"event":{"type":"message","user":"U2","channel":"C","text":"x"}}));self.assertTrue(s.process_event({"event":{"type":"message","user":"U1","channel":"C","text":"hi"}}));self.assertFalse(sent[-1]["mrkdwn"])
if __name__=="__main__":unittest.main()
