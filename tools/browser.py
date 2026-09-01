from __future__ import annotations
from .base import ToolResult
from urllib.parse import urlparse
import ipaddress,socket
def _public_url(url:str)->bool:
    p=urlparse(url)
    if p.scheme not in {'http','https'} or not p.hostname:return False
    if p.username or p.password:return False
    try:
        for info in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
            ip=ipaddress.ip_address(info[4][0])
            if not ip.is_global:return False
    except (socket.gaierror,ValueError):return False
    return True
def browser_fetch(url:str)->ToolResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:return ToolResult(False,error='Install optional browser support: pip install playwright && playwright install chromium')
    if not _public_url(url):return ToolResult(False,error='Only public HTTP(S) URLs are allowed')
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True); page=b.new_page()
        def route_handler(route):
            if _public_url(route.request.url):route.continue_()
            else:route.abort()
        page.route('**/*',route_handler); page.goto(url,wait_until='domcontentloaded',timeout=30000); text=page.locator('body').inner_text()[:20000]; final=page.url; b.close()
    return ToolResult(True,{'url':final,'text':text})
