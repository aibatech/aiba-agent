"""Authenticated remote computer-node control transport.

This module supplies a narrow HTTPS JSON transport. The AIBA server signs each
request with an HMAC node token; the remote node verifies timestamp, nonce and
signature before dispatch. TLS certificate verification is mandatory and may be
pinned to an operator-provided SHA-256 certificate fingerprint. This transport
is disabled unless explicitly configured by the operator.
"""
from __future__ import annotations
import hashlib,hmac,json,secrets,ssl,time,urllib.request
from dataclasses import dataclass

class RemoteNodeAuthError(PermissionError):pass

def sign_request(token:str,method:str,path:str,body:bytes,timestamp:int,nonce:str)->str:
    digest=hashlib.sha256(body).hexdigest()
    canonical=f"{timestamp}\n{nonce}\n{method.upper()}\n{path}\n{digest}".encode()
    return hmac.new(token.encode(),canonical,hashlib.sha256).hexdigest()

def verify_request(token:str,method:str,path:str,body:bytes,timestamp:int,nonce:str,signature:str,now:int|None=None,max_skew:int=60)->bool:
    current=int(time.time() if now is None else now)
    if abs(current-int(timestamp))>max_skew:return False
    expected=sign_request(token,method,path,body,int(timestamp),nonce)
    return hmac.compare_digest(expected,signature or "")


class RemoteNodeRequestVerifier:
    """Server-side signed-request verifier with bounded nonce replay cache."""
    def __init__(self,token:str,max_skew:int=60,max_nonces:int=4096):
        if len(token)<32: raise ValueError("remote computer node token is too short")
        self.token=token;self.max_skew=int(max_skew);self.max_nonces=int(max_nonces);self._seen={};self._lock=__import__("threading").Lock()
    def verify(self,method:str,path:str,body:bytes,timestamp:str,nonce:str,signature:str,now:int|None=None)->bool:
        try: ts=int(timestamp)
        except (TypeError,ValueError): return False
        current=int(time.time() if now is None else now)
        if not nonce or len(nonce)>256 or not verify_request(self.token,method,path,body,ts,nonce,signature,now=current,max_skew=self.max_skew): return False
        with self._lock:
            cutoff=current-self.max_skew
            self._seen={n:t for n,t in self._seen.items() if t>=cutoff}
            if nonce in self._seen:return False
            if len(self._seen)>=self.max_nonces:
                oldest=min(self._seen,key=self._seen.get);self._seen.pop(oldest,None)
            self._seen[nonce]=current
        return True

@dataclass
class RemoteNodeTransport:
    base_url:str
    token:str
    cert_sha256:str=""
    timeout_s:float=20
    def __post_init__(self):
        if not self.base_url.startswith("https://"):raise ValueError("remote computer node requires https")
        if len(self.token)<32:raise ValueError("remote computer node token is too short")
    def call(self,action:str,arguments:dict)->dict:
        path="/v1/action"; body=json.dumps({"action":action,"arguments":arguments},separators=(",",":")).encode()
        ts=int(time.time()); nonce=secrets.token_urlsafe(18); sig=sign_request(self.token,"POST",path,body,ts,nonce)
        req=urllib.request.Request(self.base_url.rstrip("/")+path,data=body,method="POST",headers={
          "Content-Type":"application/json","X-AIBA-Timestamp":str(ts),"X-AIBA-Nonce":nonce,"X-AIBA-Signature":sig})
        ctx=ssl.create_default_context()
        with urllib.request.urlopen(req,timeout=self.timeout_s,context=ctx) as response:
            if self.cert_sha256:
                sock=getattr(getattr(response,"fp",None),"raw",None)
                sock=getattr(sock,"_sock",None)
                cert=sock.getpeercert(binary_form=True) if sock else None
                actual=hashlib.sha256(cert or b"").hexdigest()
                if not hmac.compare_digest(actual.lower(),self.cert_sha256.lower().replace(":","")):
                    raise RemoteNodeAuthError("remote node TLS certificate pin mismatch")
            data=response.read(1024*1024)
        result=json.loads(data.decode("utf-8"))
        if not isinstance(result,dict):raise RemoteNodeAuthError("invalid remote node response")
        return result
