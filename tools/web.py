"""Phase 4 — web_search and web_extract tools (SSRF-safe).

Two registrable tools that let AIBA read the public web without opening a
browser and without allowing Server-Side Request Forgery:

* ``web_search(query)`` — queries a configured search backend (default:
  DuckDuckGo's no-API-key HTML endpoint). The backend host is a fixed,
  allowlisted public domain — user input never selects the base URL, so there
  is no SSRF surface from the query.
* ``web_extract(urls)`` — fetches text from *public* HTTP(S) pages. Every URL
  is passed through the same ``_public_url`` guard the existing ``browser_fetch``
  uses, which rejects private/loopback/link-local destinations and URLs with
  embedded credentials.

Both accept an injected ``_fetch`` callable for hermetic testing.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .base import ToolResult
from .browser import _public_url

# Fixed, allowlisted search endpoint. This is the ONLY host web_search ever
# contacts; user query text is encoded into it but never selects a hostname.
_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
_MAX_QUERY = 200
_MAX_EXTRACT_CHARS = 20000
_TIMEOUT = 25

Fetch = Callable[[str, dict], tuple[int, str]]


def _default_fetch(url: str, headers: dict) -> tuple[int, str]:
    """Plain urllib fetch returning (status, body). Exists so tests can stub it."""
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "aiba-web/1.6"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    """Very light HTML-to-text: drop scripts/styles/tags, collapse whitespace."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    text = re.sub(r"\s+", " ", html).strip()
    return text[:_MAX_EXTRACT_CHARS]


def _parse_results(html: str, limit: int) -> list[dict]:
    """Parse DuckDuckGo HTML results into {title, url, snippet} dicts.

    Parsing real search HTML is intentionally conservative: if the structure
    does not match, we return what we can rather than fabricate results.
    """
    results: list[dict] = []
    # DDG result blocks contain an <a class="result__a" href="...">Title</a> and
    # a sibling snippet element. Anchor hrefs carry a redirect wrapper.
    for m in re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, title_html = m.group(1), m.group(2)
        url = urllib.parse.unquote(href)
        # Strip DDG redirect wrapper: https://duckduckgo.com/l/?uddg=<encoded>&rut=...
        um = re.search(r"[?&]uddg=([^&]+)", url)
        if um:
            url = urllib.parse.unquote(um.group(1))
        title = _strip_html(title_html)
        if url.startswith(("http://", "https://")) and title:
            results.append({"title": title, "url": url})
            if len(results) >= limit:
                break
    # Snippets are harder to attribute reliably; attach a generic snippet field
    # from text bodies if available.
    snips = re.findall(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.S)
    for i, sn in enumerate(snips[: len(results)]):
        results[i]["snippet"] = _strip_html(sn)[:300]
    return results


class WebTools:
    def __init__(self, fetch: Fetch | None = None, search_enabled: bool = True):
        self._fetch = fetch or _default_fetch
        self._search_enabled = search_enabled

    def web_search(self, query: str, limit: int = 5) -> ToolResult:
        if not self._search_enabled:
            return ToolResult(False, error="web_search is disabled")
        query = (query or "").strip()
        if not query:
            return ToolResult(False, error="query must not be empty")
        query = query[:_MAX_QUERY]
        if not (1 <= int(limit) <= 20):
            limit = 5
        url = f"{_SEARCH_ENDPOINT}?{urllib.parse.urlencode({'q': query})}"
        try:
            status, body = self._fetch(url, {})
        except urllib.error.HTTPError as exc:
            return ToolResult(False, error=f"Search backend error HTTP {exc.code}")
        except Exception as exc:
            return ToolResult(False, error=f"Search failed: {type(exc).__name__}: {exc}")
        results = _parse_results(body, int(limit))
        if not results:
            return ToolResult(True, {"results": [], "note": "No parseable results returned by search backend"})
        return ToolResult(True, {"results": results})

    def web_extract(self, urls: list[str], limit_per_page: int | None = None) -> ToolResult:
        urls = urls or []
        if not urls or not isinstance(urls, list):
            return ToolResult(False, error="urls must be a non-empty list")
        for u in urls:
            if not isinstance(u, str) or not _public_url(u):
                return ToolResult(False, error=f"Only public HTTP(S) URLs are allowed (blocked SSRF target): {u}")
        pages = []
        for u in urls[:5]:
            try:
                # Respect robots.txt is out of scope for a tool; just fetch with a
                # normal UA and cap size.
                status, body = self._fetch(u, {})
                text = _strip_html(body)
                if limit_per_page:
                    text = text[: int(limit_per_page)]
                pages.append({"url": u, "status": status, "text": text})
            except urllib.error.HTTPError as exc:
                pages.append({"url": u, "status": exc.code, "text": f"HTTP {exc.code}"})
            except Exception as exc:
                pages.append({"url": u, "status": 0, "text": f"Error: {type(exc).__name__}: {exc}"})
        return ToolResult(True, {"pages": pages})


def build_web_tools(cls=WebTools, **kwargs) -> list:
    """Build the (web_search, web_extract) Tool pair for a registry."""
    from .base import Tool

    wt = cls(**kwargs)
    return [
        Tool(
            name="web_search",
            description="Search the public web for a topic and return title/url/snippet results. Prefer before web_extract when you need to discover sources.",
            handler=wt.web_search,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "max results, 1-20"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="web_extract",
            description="Fetch readable text from one or more PUBLIC http(s) pages (up to 5). Blocks private/loopback targets (SSRF-safe).",
            handler=wt.web_extract,
            parameters={
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}},
                    "limit_per_page": {"type": "integer"},
                },
                "required": ["urls"],
                "additionalProperties": False,
            },
        ),
    ]
