"""Pinned outbound HTTP proxy for Chromium browser sessions.

The proxy resolves each destination once, rejects non-global addresses, and opens
the upstream socket to that exact approved IP while preserving the original Host
header / TLS SNI. Chromium never resolves the destination hostname itself. This
makes the network connection enforce the same DNS decision AIBA reviewed,
closing the browser DNS-rebinding gap left by Python preflight checks.
"""
from __future__ import annotations
import ipaddress, select, socket, socketserver, ssl, threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

class EgressDenied(PermissionError): pass

def resolve_pinned(host:str,port:int,resolver=socket.getaddrinfo)->str:
    infos=resolver(host,port,type=socket.SOCK_STREAM)
    if not infos: raise EgressDenied("destination did not resolve")
    ips=[]
    for info in infos:
        ip=info[4][0]; addr=ipaddress.ip_address(ip)
        if not addr.is_global: raise EgressDenied(f"non-public destination refused: {ip}")
        ips.append(ip)
    return ips[0]

def _connect_ip(ip:str,port:int,timeout:float=15):
    family=socket.AF_INET6 if ":" in ip else socket.AF_INET
    s=socket.socket(family,socket.SOCK_STREAM); s.settimeout(timeout)
    s.connect((ip,port)); return s

def _relay(a,b):
    sockets=[a,b]
    while True:
        readable,_,_=select.select(sockets,[],[],30)
        if not readable: break
        for src in readable:
            data=src.recv(65536)
            if not data:return
            (b if src is a else a).sendall(data)

class _Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*_): pass
    def _deny(self,msg):
        self.send_response(403); self.send_header("Content-Length",str(len(msg))); self.end_headers(); self.wfile.write(msg.encode())
    def do_CONNECT(self):
        try:
            host,port_s=self.path.rsplit(":",1); port=int(port_s)
            ip=resolve_pinned(host,port,self.server.resolver)
            upstream=_connect_ip(ip,port)
            self.send_response(200,"Connection Established"); self.end_headers()
            _relay(self.connection,upstream)
        except Exception as exc:
            try:self._deny(f"AIBA egress denied: {exc}")
            except Exception:pass
        finally:
            try:upstream.close()
            except Exception:pass
    def _http(self):
        try:
            p=urlsplit(self.path)
            host=p.hostname or self.headers.get("Host","").split(":")[0]
            port=p.port or 80
            ip=resolve_pinned(host,port,self.server.resolver)
            upstream=_connect_ip(ip,port)
            path=(p.path or "/")+("?" + p.query if p.query else "")
            headers="".join(f"{k}: {v}\r\n" for k,v in self.headers.items() if k.lower() not in {"proxy-connection","connection"})
            length=int(self.headers.get("Content-Length","0") or 0)
            if length < 0 or length > 10*1024*1024: raise EgressDenied("request body too large")
            body=self.rfile.read(length) if length else b""
            request=f"{self.command} {path} HTTP/1.1\r\n{headers}Connection: close\r\n\r\n".encode()+body
            upstream.sendall(request)
            while True:
                data=upstream.recv(65536)
                if not data:break
                self.connection.sendall(data)
        except Exception as exc:self._deny(f"AIBA egress denied: {exc}")
        finally:
            try:upstream.close()
            except Exception:pass
    do_GET=_http; do_POST=_http; do_PUT=_http; do_DELETE=_http; do_HEAD=_http; do_OPTIONS=_http; do_PATCH=_http

class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True; daemon_threads=True
    def __init__(self,addr,resolver):self.resolver=resolver;super().__init__(addr,_Handler)

class PinnedEgressProxy:
    def __init__(self,resolver=socket.getaddrinfo):self.resolver=resolver;self.server=None;self.thread=None
    def start(self):
        if self.server:return self.url
        self.server=_Server(("127.0.0.1",0),self.resolver)
        self.thread=threading.Thread(target=self.server.serve_forever,name="aiba-egress-proxy",daemon=True);self.thread.start()
        return self.url
    @property
    def url(self):
        if not self.server:raise RuntimeError("proxy not started")
        return f"http://127.0.0.1:{self.server.server_address[1]}"
    def close(self):
        if self.server:self.server.shutdown();self.server.server_close()
        if self.thread:self.thread.join(timeout=2)
        self.server=None;self.thread=None
