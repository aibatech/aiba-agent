from __future__ import annotations
import hashlib,hmac,os,secrets,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from sqlite_utils import connect
class AuthStore:
    def __init__(self,path:Path):self.path=path;path.parent.mkdir(parents=True,exist_ok=True);self._init()
    def _init(self):
        with connect(self.path) as c:c.execute('CREATE TABLE IF NOT EXISTS api_tokens(id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)')
    def create(self,name:str)->str:
        token='aiba_'+secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
        with connect(self.path) as c:c.execute('INSERT INTO api_tokens VALUES(?,?,?,?,0)',(secrets.token_hex(8),name,digest,datetime.now(timezone.utc).isoformat()))
        return token
    def verify(self,token:str)->bool:
        digest=hashlib.sha256(token.encode()).hexdigest()
        with connect(self.path) as c:row=c.execute('SELECT token_hash FROM api_tokens WHERE token_hash=? AND revoked=0',(digest,)).fetchone()
        return bool(row and hmac.compare_digest(row[0],digest))
