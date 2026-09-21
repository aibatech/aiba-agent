"""Security-first web discovery, research, and extraction tools.

AIBA intentionally exposes a small web surface instead of many overlapping
search tools. ``web_search`` can perform either lightweight discovery or a
bounded research pass that searches multiple query variants, diversifies
sources by domain, validates every URL through the shared SSRF policy, and
returns extracted evidence with stable source IDs. ``web_extract`` remains the
explicit page-reading primitive.
"""
from __future__ import annotations

import html as html_lib
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import ToolResult
from .browser import _public_url

_SEARCH_ENDPOINTS = (
    ("duckduckgo_html", "https://html.duckduckgo.com/html/"),
    ("duckduckgo_lite", "https://lite.duckduckgo.com/lite/"),
)
_MAX_QUERY = 240
_MAX_EXTRACT_CHARS = 20000
_MAX_RESEARCH_QUERIES = 5
_MAX_RESEARCH_SOURCES = 10
_TIMEOUT = 25
_TRACKING_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}

Fetch = Callable[[str, dict], tuple[int, str]]


def _default_fetch(url: str, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={**headers, "User-Agent": "Mozilla/5.0 (compatible; AIBA-Agent/1.6; +https://aibatech.com)", "Accept-Language": "en-US,en;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return int(resp.status), resp.read().decode("utf-8", errors="replace")


def _strip_html(raw: str) -> str:
    """Convert ordinary HTML to bounded readable text without executing it."""
    raw = re.sub(r"<!--.*?-->", " ", raw or "", flags=re.S)
    raw = re.sub(
        r"<(script|style|noscript|svg|canvas)[^>]*>.*?</\1>",
        " ",
        raw,
        flags=re.S | re.I,
    )
    raw = re.sub(r"<(br|p|div|li|h[1-6]|tr)[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(raw)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:_MAX_EXTRACT_CHARS]


def _canonical_url(url: str) -> str:
    """Normalize an HTTP(S) URL for deduplication without changing its target."""
    try:
        parsed = urllib.parse.urlsplit(url)
        clean_query = []
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            low = key.lower()
            if low.startswith("utm_") or low in _TRACKING_KEYS:
                continue
            clean_query.append((key, value))
        query = urllib.parse.urlencode(clean_query, doseq=True)
        path = parsed.path or "/"
        return urllib.parse.urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), path, query, "")
        )
    except Exception:
        return url


def _domain(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _parse_results(raw: str, limit: int) -> list[dict[str, str]]:
    """Parse supported DuckDuckGo HTML/Lite result markup without fabricating rows."""
    results: list[dict[str, str]] = []
    # HTML uses result__a; Lite uses result-link. Attribute order and quote style
    # are deliberately not assumed because both endpoints have changed markup.
    for match in re.finditer(r"<a\\b([^>]*)>(.*?)</a>", raw or "", re.S | re.I):
        attrs, title_html = match.group(1), match.group(2)
        cls_match = re.search(r"""class\s*=\s*["']([^"']+)["']""", attrs, re.I)
        classes = set((cls_match.group(1) if cls_match else "").split())
        if not ({"result__a", "result-link"} & classes):
            continue
        href_match = re.search(r"""href\s*=\s*["']([^"']+)["']""", attrs, re.I)
        if not href_match:
            continue
        href = href_match.group(1)
        url = html_lib.unescape(urllib.parse.unquote(href))
        wrapped = re.search(r"[?&]uddg=([^&]+)", url)
        if wrapped:
            url = urllib.parse.unquote(wrapped.group(1))
        title = _strip_html(title_html)
        if url.startswith(("http://", "https://")) and title:
            results.append({"title": title, "url": _canonical_url(url)})
            if len(results) >= limit:
                break
    snippets = re.findall(
        r"""class\s*=\s*["'][^"']*(?:result__snippet|result-snippet)[^"']*["'][^>]*>(.*?)(?:</a>|</td>|</div>)""",
        raw or "",
        re.S | re.I,
    )
    for index, snippet in enumerate(snippets[: len(results)]):
        results[index]["snippet"] = _strip_html(snippet)[:500]
    return results


class WebTools:
    def __init__(self, fetch: Fetch | None = None, search_enabled: bool = True):
        self._fetch = fetch or _default_fetch
        self._search_enabled = search_enabled

    def _search_once(self, query: str, limit: int) -> tuple[list[dict[str, str]], str | None]:
        errors: list[str] = []
        for provider, endpoint in _SEARCH_ENDPOINTS:
            url = f"{endpoint}?{urllib.parse.urlencode({'q': query[:_MAX_QUERY]})}"
            try:
                status, body = self._fetch(url, {})
                if status >= 400:
                    errors.append(f"{provider}: HTTP {status}")
                    continue
                results = _parse_results(body, limit)
                if results:
                    return results, None
                title = ""
                match = re.search(r"<title[^>]*>(.*?)</title>", body or "", re.S | re.I)
                if match:
                    title = _strip_html(match.group(1))[:80]
                detail = f", title={title!r}" if title else ""
                errors.append(f"{provider}: HTTP {status} but zero parseable results{detail}")
            except urllib.error.HTTPError as exc:
                errors.append(f"{provider}: HTTP {exc.code}")
            except Exception as exc:
                errors.append(f"{provider}: {type(exc).__name__}: {exc}")
        return [], " | ".join(errors) or "all search providers failed"

    @staticmethod
    def _domain_allowed(
        domain: str,
        include_domains: list[str] | None,
        exclude_domains: list[str] | None,
    ) -> bool:
        domain = domain.lower().strip(".")
        includes = [d.lower().strip(". ") for d in (include_domains or []) if d]
        excludes = [d.lower().strip(". ") for d in (exclude_domains or []) if d]
        if any(domain == d or domain.endswith("." + d) for d in excludes):
            return False
        if includes and not any(domain == d or domain.endswith("." + d) for d in includes):
            return False
        return True

    def web_search(
        self,
        query: str,
        limit: int = 8,
        deep: bool = False,
        queries: list[str] | None = None,
        max_sources: int = 6,
        max_per_domain: int = 2,
        extract_chars: int = 6000,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> ToolResult:
        """Search the public web, optionally returning a grounded evidence pack.

        ``deep=False`` is fast discovery. ``deep=True`` searches the primary
        query plus optional model-supplied query variants, deduplicates URLs,
        enforces domain diversity, and reads selected public pages. Every source
        gets a stable S1/S2/... ID so the model can attribute claims precisely.
        """
        if not self._search_enabled:
            return ToolResult(False, error="web_search is disabled")
        query = (query or "").strip()
        if not query:
            return ToolResult(False, error="query must not be empty")
        limit = int(limit) if isinstance(limit, int) else 8
        limit = min(max(limit, 1), 20)

        requested = [query]
        for extra in queries or []:
            extra = (extra or "").strip()
            if extra and extra not in requested:
                requested.append(extra)
            if len(requested) >= _MAX_RESEARCH_QUERIES:
                break
        if not deep:
            results, error = self._search_once(query, limit)
            if error:
                return ToolResult(False, error=f"Search failed: {error}")
            return ToolResult(True, {"query": query, "results": results})

        max_sources = min(max(int(max_sources), 1), _MAX_RESEARCH_SOURCES)
        max_per_domain = min(max(int(max_per_domain), 1), 5)
        extract_chars = min(max(int(extract_chars), 500), _MAX_EXTRACT_CHARS)
        discovered: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        query_errors: list[dict[str, str]] = []

        for q in requested:
            rows, error = self._search_once(q, limit)
            if error:
                query_errors.append({"query": q, "error": error})
                continue
            for row in rows:
                url = _canonical_url(row.get("url", ""))
                domain = _domain(url)
                if not url or url in seen_urls or not domain:
                    continue
                if not self._domain_allowed(domain, include_domains, exclude_domains):
                    continue
                if not _public_url(url):
                    continue
                seen_urls.add(url)
                discovered.append({**row, "url": url, "domain": domain, "query": q})

        selected: list[dict[str, Any]] = []
        domain_counts: dict[str, int] = {}
        for item in discovered:
            domain = str(item["domain"])
            if domain_counts.get(domain, 0) >= max_per_domain:
                continue
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            selected.append(item)
            if len(selected) >= max_sources:
                break

        sources: list[dict[str, Any]] = []
        for index, item in enumerate(selected, start=1):
            source: dict[str, Any] = {
                "source_id": f"S{index}",
                "title": item.get("title", ""),
                "url": item["url"],
                "domain": item["domain"],
                "snippet": item.get("snippet", ""),
                "discovered_by": item.get("query", query),
            }
            try:
                status, body = self._fetch(str(item["url"]), {})
                text = _strip_html(body)[:extract_chars]
                source.update({"status": int(status), "text": text, "text_chars": len(text)})
            except urllib.error.HTTPError as exc:
                source.update({"status": int(exc.code), "text": "", "error": f"HTTP {exc.code}"})
            except Exception as exc:
                source.update({"status": 0, "text": "", "error": f"{type(exc).__name__}: {exc}"})
            sources.append(source)

        return ToolResult(
            True,
            {
                "query": query,
                "mode": "research",
                "queries_run": requested,
                "sources": sources,
                "coverage": {
                    "discovered_urls": len(discovered),
                    "selected_sources": len(sources),
                    "unique_domains": len({s["domain"] for s in sources}),
                    "query_errors": query_errors,
                },
                "grounding": "Use source_id (S1, S2, ...) to attribute factual claims; distinguish source evidence from inference.",
            },
        )

    def web_extract(self, urls: list[str], limit_per_page: int | None = None) -> ToolResult:
        urls = urls or []
        if not urls or not isinstance(urls, list):
            return ToolResult(False, error="urls must be a non-empty list")
        for url in urls:
            if not isinstance(url, str) or not _public_url(url):
                return ToolResult(
                    False,
                    error=f"Only public HTTP(S) URLs are allowed (blocked SSRF target): {url}",
                )
        pages: list[dict[str, Any]] = []
        cap = _MAX_EXTRACT_CHARS
        if limit_per_page is not None:
            cap = min(max(int(limit_per_page), 1), _MAX_EXTRACT_CHARS)
        for index, raw_url in enumerate(urls[:5], start=1):
            url = _canonical_url(raw_url)
            try:
                status, body = self._fetch(url, {})
                text = _strip_html(body)[:cap]
                pages.append(
                    {
                        "source_id": f"S{index}",
                        "url": url,
                        "domain": _domain(url),
                        "status": int(status),
                        "text_chars": len(text),
                        "text": text,
                    }
                )
            except urllib.error.HTTPError as exc:
                pages.append({"source_id": f"S{index}", "url": url, "status": exc.code, "text": "", "error": f"HTTP {exc.code}"})
            except Exception as exc:
                pages.append({"source_id": f"S{index}", "url": url, "status": 0, "text": "", "error": f"{type(exc).__name__}: {exc}"})
        return ToolResult(True, {"pages": pages})


def build_web_tools(cls=WebTools, **kwargs) -> list:
    from .base import Tool

    web = cls(**kwargs)
    return [
        Tool(
            name="web_search",
            description=(
                "Search the public web. Set deep=true for grounded multi-query research: "
                "AIBA deduplicates/diversifies sources, reads selected pages, and returns "
                "stable source IDs for attribution. Prefer deep research for factual, current, "
                "comparative, or high-confidence answers."
            ),
            handler=web.web_search,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "results per search query, 1-20"},
                    "deep": {"type": "boolean", "description": "perform grounded research and source extraction"},
                    "queries": {"type": "array", "items": {"type": "string"}, "description": "optional alternate search queries, max 4 in addition to query"},
                    "max_sources": {"type": "integer", "description": "research sources to extract, 1-10"},
                    "max_per_domain": {"type": "integer", "description": "source-diversity cap per domain, 1-5"},
                    "extract_chars": {"type": "integer", "description": "max readable characters per research source"},
                    "include_domains": {"type": "array", "items": {"type": "string"}},
                    "exclude_domains": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="web_extract",
            description=(
                "Read bounded text from up to five PUBLIC HTTP(S) pages. Returns source IDs, "
                "domain, status, text length and readable text; private/loopback targets are blocked."
            ),
            handler=web.web_extract,
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
