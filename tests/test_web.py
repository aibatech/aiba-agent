"""Tests for security-first web discovery, research, and extraction."""
from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from tools.registry import ToolRegistry
from tools.web import WebTools, _canonical_url, _parse_results, _strip_html, build_web_tools


class _Policy:
    config = {"tools": {}}

    def check_tool(self, name):
        return type("D", (), {"allowed": True, "requires_approval": False, "reason": ""})()


class _Approvals:
    def approve(self, *a):
        return True


class _Audit:
    def record(self, *a, **k):
        pass


_DDG_SAMPLE = """
<div class="result">
  <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F%3Futm_source%3Dtest&rut=abc">Example Title</a>
  <a class="result__snippet" href="#">A short snippet.</a>
</div>
<div class="result">
  <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fsecond.example.org%2Freport&rut=def">Second Source</a>
  <a class="result__snippet" href="#">Independent evidence.</a>
</div>
"""


_DDG_LITE_SAMPLE = """
<table>
  <tr><td><a rel="nofollow" class='result-link' href='https://example.com/lite'>Lite Result</a></td></tr>
  <tr><td class='result-snippet'>Lite search snippet.</td></tr>
</table>
"""

def _fake_fetch(url, headers):
    if "duckduckgo.com" in url:
        return 200, _DDG_SAMPLE
    if "example.com" in url:
        return 200, "<html><body><h1>Hello</h1><p>World &amp; more</p><script>var x=1;</script></body></html>"
    if "second.example.org" in url:
        return 200, "<html><body><main><h1>Report</h1><p>Corroborating source text.</p></main></body></html>"
    return 404, "not found"


def _fake_dns(host, port, **kwargs):
    public = {"example.com", "second.example.org"}
    address = "93.184.216.34" if host in public else "127.0.0.1"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        dns = patch("tools.browser.socket.getaddrinfo", side_effect=_fake_dns)
        dns.start()
        self.addCleanup(dns.stop)

    def test_search_returns_parsed_results(self):
        res = WebTools(fetch=_fake_fetch).web_search("test query")
        self.assertTrue(res.ok)
        self.assertGreaterEqual(len(res.output["results"]), 1)
        row = res.output["results"][0]
        self.assertEqual(row["title"], "Example Title")
        self.assertEqual(row["url"], "https://example.com/")

    def test_deep_research_returns_grounded_diverse_sources(self):
        res = WebTools(fetch=_fake_fetch).web_search(
            "test query",
            deep=True,
            queries=["test query official", "test query independent"],
            max_sources=4,
            max_per_domain=1,
        )
        self.assertTrue(res.ok)
        self.assertEqual(res.output["mode"], "research")
        sources = res.output["sources"]
        self.assertEqual([s["source_id"] for s in sources], ["S1", "S2"])
        self.assertEqual(len({s["domain"] for s in sources}), 2)
        self.assertIn("Hello", sources[0]["text"])
        self.assertIn("Corroborating", sources[1]["text"])
        self.assertEqual(res.output["coverage"]["unique_domains"], 2)
        self.assertIn("source_id", res.output["grounding"])

    def test_deep_research_domain_filters(self):
        res = WebTools(fetch=_fake_fetch).web_search(
            "x", deep=True, include_domains=["example.org"], max_sources=5
        )
        self.assertTrue(res.ok)
        self.assertEqual(len(res.output["sources"]), 1)
        self.assertEqual(res.output["sources"][0]["domain"], "second.example.org")

    def test_search_disabled(self):
        res = WebTools(fetch=_fake_fetch, search_enabled=False).web_search("x")
        self.assertFalse(res.ok)
        self.assertIn("disabled", res.error or "")

    def test_search_empty_query(self):
        self.assertFalse(WebTools(fetch=_fake_fetch).web_search("  ").ok)

    def test_search_200_with_zero_results_is_failure(self):
        def empty_search(url, headers):
            return 200, "<html><head><title>Challenge</title></head><body></body></html>"

        res = WebTools(fetch=empty_search).web_search("weather today")
        self.assertFalse(res.ok)
        self.assertIn("zero parseable results", res.error or "")
        self.assertIn("duckduckgo_html", res.error or "")
        self.assertIn("duckduckgo_lite", res.error or "")

    def test_search_falls_back_after_empty_primary(self):
        def fallback(url, headers):
            if "html.duckduckgo.com" in url:
                return 200, "<html><body>challenge</body></html>"
            return 200, _DDG_LITE_SAMPLE

        res = WebTools(fetch=fallback).web_search("test query")
        self.assertTrue(res.ok)
        self.assertEqual(res.output["results"][0]["title"], "Lite Result")
        self.assertEqual(res.output["results"][0]["url"], "https://example.com/lite")
        self.assertEqual(res.output["results"][0]["snippet"], "Lite search snippet.")

    def test_search_backend_error(self):
        def boom(url, headers):
            raise RuntimeError("down")

        self.assertFalse(WebTools(fetch=boom).web_search("x").ok)

    def test_strip_html_decodes_entities_and_drops_executable_content(self):
        text = _strip_html("<p>keep &amp; <b>this</b></p><script>drop</script><style>css</style>")
        self.assertIn("keep & this", text)
        self.assertNotIn("drop", text)
        self.assertNotIn("css", text)

    def test_canonical_url_removes_tracking_and_fragment(self):
        url = _canonical_url("HTTPS://Example.COM/path?utm_source=x&a=1&fbclid=z#part")
        self.assertEqual(url, "https://example.com/path?a=1")


class WebExtractTests(unittest.TestCase):
    def setUp(self):
        dns = patch("tools.browser.socket.getaddrinfo", side_effect=_fake_dns)
        dns.start()
        self.addCleanup(dns.stop)
        self.wt = WebTools(fetch=_fake_fetch)

    def test_extract_public_urls_with_source_metadata(self):
        res = self.wt.web_extract(["https://example.com/pg"])
        self.assertTrue(res.ok)
        page = res.output["pages"][0]
        self.assertEqual(page["source_id"], "S1")
        self.assertEqual(page["domain"], "example.com")
        self.assertEqual(page["status"], 200)
        self.assertIn("Hello", page["text"])
        self.assertGreater(page["text_chars"], 0)

    def test_extract_blocks_private_urls(self):
        res = self.wt.web_extract(["http://127.0.0.1/secret", "http://localhost/x"])
        self.assertFalse(res.ok)
        self.assertIn("blocked SSRF", res.error or "")

    def test_extract_blocks_url_with_credentials(self):
        self.assertFalse(self.wt.web_extract(["https://user:pass@example.com/"]).ok)

    def test_public_hostname_resolving_to_private_is_denied(self):
        self.assertFalse(self.wt.web_extract(["https://internal.example/"]).ok)

    def test_extract_empty_list(self):
        self.assertFalse(self.wt.web_extract([]).ok)

    def test_extract_up_to_five(self):
        res = self.wt.web_extract(["https://example.com"] * 8)
        self.assertEqual(len(res.output["pages"]), 5)


class WebToolRegistrationTests(unittest.TestCase):
    def setUp(self):
        dns = patch("tools.browser.socket.getaddrinfo", side_effect=_fake_dns)
        dns.start()
        self.addCleanup(dns.stop)
        self.reg = ToolRegistry(_Audit(), _Approvals(), _Policy())
        for tool in build_web_tools(fetch=_fake_fetch):
            self.reg.register(tool)

    def test_tools_registered(self):
        names = [schema["name"] for schema in self.reg.schemas()]
        self.assertIn("web_search", names)
        self.assertIn("web_extract", names)

    def test_deep_search_executes_through_registry(self):
        res = self.reg.execute(
            "web_search", {"query": "hello", "deep": True, "max_sources": 2}
        )
        self.assertTrue(res.ok)
        self.assertEqual(res.output["mode"], "research")
        self.assertEqual(len(res.output["sources"]), 2)

    def test_web_extract_executes_through_registry(self):
        res = self.reg.execute("web_extract", {"urls": ["https://example.com/"]})
        self.assertTrue(res.ok)
        self.assertIn("Hello", res.output["pages"][0]["text"])


if __name__ == "__main__":
    unittest.main()
