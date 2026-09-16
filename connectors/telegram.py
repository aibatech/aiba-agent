from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from connectors.ux.render import TYPING_INTERVAL_SECONDS, InlineKeyboard, InlineKey, TypingSender, prepare_message


def _ids(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            result.add(int(item))
    return result


class TelegramConnector:
    """Telegram Bot API connector using long polling (no public port required)."""

    def __init__(self, agent, token: str | None = None, allowed_users: set[int] | None = None, transport=None):
        self.agent = agent
        self.token = (token or os.getenv("AIBA_TELEGRAM_BOT_TOKEN", "")).strip()
        self.allowed_users = allowed_users if allowed_users is not None else _ids(os.getenv("AIBA_TELEGRAM_ALLOWED_USERS", ""))
        if not self.token: raise ValueError("AIBA_TELEGRAM_BOT_TOKEN is required")
        if not self.allowed_users: raise ValueError("AIBA_TELEGRAM_ALLOWED_USERS must contain at least one numeric owner ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.transport = transport or self._request
        self.stop_event = threading.Event();self.thread: threading.Thread | None = None;self.offset = 0
        self._typing_threads: dict[int, threading.Thread] = {};self._last_hb: dict[int, float] = {};self._hb_lock = threading.Lock()
        self._update_prompted_version: str | None = None

    @classmethod
    def enabled(cls) -> bool:return os.getenv("AIBA_TELEGRAM_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _request(self, method: str, data: dict | None = None) -> dict:
        payload=urllib.parse.urlencode(data or {}).encode();request=urllib.request.Request(f"{self.base_url}/{method}",data=payload)
        with urllib.request.urlopen(request,timeout=40) as response:body=json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):raise RuntimeError(f"Telegram API rejected {method}")
        return body

    def send(self,chat_id:int,text:str)->None:
        if text is None or not str(text).strip():return
        self.send_payload(chat_id,prepare_message(str(text)))

    def send_keyboard(self,chat_id:int,text:str,keyboard:InlineKeyboard)->None:self.send_payload(chat_id,prepare_message(text,keyboard=keyboard))

    def send_payload(self,chat_id:int,rendered)->None:
        for i,chunk in enumerate(rendered.sends):
            data={"chat_id":chat_id,"text":chunk,"parse_mode":"HTML"}
            if i==0 and rendered.reply_markup is not None:data["reply_markup"]=json.dumps(rendered.reply_markup)
            self.transport("sendMessage",data)

    def _start_typing(self,chat_id:int)->None:
        with self._hb_lock:
            if chat_id in self._typing_threads:return
            sender=TypingSender(self.transport,chat_id);stop=threading.Event();self._typing_stops=getattr(self,"_typing_stops",{});self._typing_stops[chat_id]=stop
            def beat():
                try:
                    while not stop.is_set():sender.heartbeat();time.sleep(TYPING_INTERVAL_SECONDS)
                except Exception:pass
                finally:
                    with self._hb_lock:self._typing_threads.pop(chat_id,None)
            t=threading.Thread(target=beat,name=f"aiba-typing-{chat_id}",daemon=True);self._typing_threads[chat_id]=t;t.start()

    def _stop_typing(self,chat_id:int)->None:
        with self._hb_lock:stop=getattr(self,"_typing_stops",{}).pop(chat_id,None);self._typing_threads.pop(chat_id,None)
        if stop:stop.set()

    def _maybe_prompt_update(self,chat_id:int)->None:
        """Render one native update prompt per discovered version."""
        updates=getattr(self.agent,"updates",None)
        if updates is None:return
        try:state=updates.status()
        except Exception:return
        version=str(state.get("latest_version") or "")
        if not state.get("available") or not version or state.get("staged_version") or version==self._update_prompted_version:return
        current=str(state.get("current_version") or "current")
        kb=InlineKeyboard([[InlineKey("Update",f"update:install:{version}"),InlineKey("Later",f"update:later:{version}")]])
        self.send_keyboard(chat_id,f"AIBA {version} is available. You're running {current}. Update now?",kb)
        self._update_prompted_version=version

    def handle_update(self,update:dict)->bool:
        if "callback_query" in update:self.handle_callback(update["callback_query"]);return True
        message=update.get("message") or {};sender=message.get("from") or {};chat=message.get("chat") or {};text=message.get("text")
        if not text or chat.get("type")!="private" or sender.get("id") not in self.allowed_users:return False
        chat_id=int(chat["id"])
        if text.strip()=="/start":self.send(chat_id,self.agent.start_conversation(f"telegram:{sender['id']}"));self._maybe_prompt_update(chat_id);return True
        try:self._start_typing(chat_id);answer=self.agent.handle(text.strip(),user_id=f"telegram:{sender['id']}",onboard=True)
        except Exception as exc:crash_id=self.agent.crashes.capture(exc,{"connector":"telegram"});answer=f"AIBA could not complete that request. Crash ID: {crash_id}"
        finally:self._stop_typing(chat_id)
        self.send(chat_id,answer);self._maybe_prompt_update(chat_id);return True

    def poll_once(self)->int:
        body=self.transport("getUpdates",{"timeout":30,"offset":self.offset,"allowed_updates":json.dumps(["message","callback_query"])});processed=0
        for update in body.get("result",[]):self.offset=max(self.offset,int(update.get("update_id",0))+1);processed+=int(self.handle_update(update))
        return processed

    def handle_callback(self,callback_query:dict)->str|None:
        data=callback_query.get("data") or "";user=(callback_query.get("from") or {}).get("id");chat_id=((callback_query.get("message") or {}).get("chat") or {}).get("id")
        if user not in self.allowed_users or not chat_id:return None
        answer=self.on_callback(int(chat_id),data)
        try:
            payload={"callback_query_id":callback_query.get("id","")}
            if answer is not None:payload["text"]=answer
            self.transport("answerCallbackQuery",payload)
        except Exception:pass
        return data

    def on_callback(self,chat_id:int,data:str)->str|None:
        if data.startswith("update:"):
            parts=data.split(":",2);action=parts[1] if len(parts)>1 else "";version=parts[2] if len(parts)>2 else ""
            if action=="later":self._update_prompted_version=version or self._update_prompted_version;return "Okay — later."
            if action=="install":
                updates=getattr(self.agent,"updates",None)
                if updates is None:return "Updater unavailable."
                try:
                    state=updates.status();manifest=state.get("manifest")
                    if version and state.get("latest_version")!=version:return "That update is no longer current."
                    result=updates.stage(manifest)
                    if result.get("staged"):
                        self.send(chat_id,f"AIBA {result.get('staged_version',version)} is verified and ready. It will be applied safely on the next AIBA restart; your .env, memory/data, virtual environment, and Git metadata are preserved.")
                        return "Update ready."
                    return str(result.get("reason") or "No update available.")[:180]
                except Exception as exc:
                    try:crash_id=self.agent.crashes.capture(exc,{"connector":"telegram","action":"stage_update"});self.send(chat_id,f"AIBA could not prepare the update. Crash ID: {crash_id}")
                    except Exception:pass
                    return "Update failed."
        if data.startswith("clar:") and getattr(self.agent,"clarify",None) is not None:
            parts=data.split(":",2)
            if len(parts)==3:
                _,qid,choice=parts
                try:
                    get_question=getattr(self.agent.clarify,"get",None);q=get_question(qid) if callable(get_question) else None
                    if not self.agent.clarify.answer(qid,choice):return None
                    selected=choice
                    if q is not None:
                        for opt in q.options:
                            if str(opt.get("id"))==choice:selected=str(opt.get("text") or choice);break
                    self._start_typing(chat_id)
                    try:response=self.agent.handle(selected,user_id=f"telegram:{chat_id}",onboard=True)
                    finally:self._stop_typing(chat_id)
                    self.send(chat_id,response);return "Got it."
                except Exception as exc:
                    try:crash_id=self.agent.crashes.capture(exc,{"connector":"telegram","action":"clarify_callback"});self.send(chat_id,f"AIBA could not continue that choice. Crash ID: {crash_id}")
                    except Exception:pass
                    return None
        return f"AIBA noted: {data[:80]}"

    def _render_clarify(self,chat_id:int,question_id:str,question:str,options:list)->None:
        qid=question_id or "";keys=[]
        for opt in options or []:
            oid=opt.get("id") if isinstance(opt,dict) else str(opt);text=opt.get("text") if isinstance(opt,dict) else str(opt)
            if oid:keys.append([InlineKey(text=str(text),callback_data=f"clar:{qid}:{oid}")])
        if keys:
            try:self.send_keyboard(chat_id,question,InlineKeyboard(keys))
            except Exception:pass

    def connect_clarify(self)->None:
        events=getattr(self.agent,"events",None)
        if events is None:return
        def handler(event):
            if not event:return
            owner_id=next(iter(self.allowed_users),None)
            if owner_id is not None:self._render_clarify(int(owner_id),event.get("question_id",""),event.get("question",""),event.get("options",[]))
        try:events.subscribe("clarify.pending",handler)
        except Exception:pass

    def run(self)->None:
        delay=1
        while not self.stop_event.is_set():
            try:self.poll_once();delay=1
            except (OSError,RuntimeError,ValueError,urllib.error.URLError):
                if self.stop_event.wait(delay):break
                delay=min(delay*2,30)

    def start(self)->None:
        if self.thread and self.thread.is_alive():return
        self.connect_clarify();self.thread=threading.Thread(target=self.run,name="aiba-telegram",daemon=True);self.thread.start()

    def stop(self)->None:
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
