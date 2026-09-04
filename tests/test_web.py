"""Tests for Phase 4 web_search + web_extract tools (SSRF-safe)."""
from __future__ import annotations

import unittest
import socket
from unittest.mock import patch

from tools.web import WebTools, build_web_tools, _parse_results, _strip_html
from tools.registry import ToolRegistry


class _Policy:
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
  <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&rut=abc">Example Title</a>
  <a class="result__snippet" href="https://duckduckgo.com/l/?uddg=...&rut=abc">A short snippet.</a>
</div>
"""


def _fake_fetch(url, headers):
    if "html.duckduckgo.com" in url:
        return 200, _DDG_SAMPLE
    if "example.com" in url:
        return 200, "<html><body><h1>Hello</h1><p>World &amp; more</p><script>var x=1;</script></body></html>"
    return 404, "not found"


def _fake_dns(host, port, **kwargs):
    # Keep the actual URL/IP policy active, but make fixture tests independent
    # of external DNS and the host's network configuration.
    address = '93.184.216.34' if host == 'example.com' else '127.0.0.1'
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]


class WebSearchTests(unittest.TestCase):
    def test_search_returns_parsed_results(self):
        wt = WebTools(fetch=_fake_fetch)
        res = wt.web_search("test query")
        self.assertTrue(res.ok)
        self.assertGreaterEqual(len(res.output["results"]), 1)
        r = res.output["results"][0]
        self.assertEqual(r["title"], "Example Title")
        self.assertEqual(r["url"], "https://example.com/")

    def test_search_disabled(self):
        wt = WebTools(fetch=_fake_fetch, search_enabled=False)
        res = wt.web_search("x")
        self.assertFalse(res.ok)
        self.assertIn("disabled", res.error or "")

    def test_search_empty_query(self):
        wt = WebTools(fetch=_fake_fetch)
        self.assertFalse(wt.web_search("  ").ok)

    def test_search_backend_error(self):
        def boom(url, headers):
            raise RuntimeError("down")
        res = WebTools(fetch=boom).web_search("x")
        self.assertFalse(res.ok)

    def test_strip_html(self):
        text = _strip_html("<p>keep <b>this</b></p><script>drop</script><style>css</style>")
        self.assertIn("keep this", text)
        self.assertNotIn("script", text)
        self.assertNotIn("css", text)


class WebExtractTests(unittest.TestCase):
    def setUp(self):
        dns = patch('tools.browser.socket.getaddrinfo', side_effect=_fake_dns)
        dns.start()
        self.addCleanup(dns.stop)
        self.wt = WebTools(fetch=_fake_fetch)

    def test_extract_public_urls(self):
        res = self.wt.web_extract(["https://example.com/pg"])
        self.assertTrue(res.ok)
        page = res.output["pages"][0]
        self.assertEqual(page["status"], 200)
        self.assertIn("Hello", page["text"])

    def test_extract_blocks_private_urls(self):
        res = self.wt.web_extract(["http://127.0.0.1/secret", "http://localhost/x"])
        self.assertFalse(res.ok)
        self.assertIn("blocked SSRF", res.error or "")

    def test_extract_blocks_url_with_credentials(self):
        res = self.wt.web_extract(["https://user:pass@example.com/"])
        self.assertFalse(res.ok)

    def test_public_hostname_resolving_to_private_is_denied(self):
        result = self.wt.web_extract(['https://internal.example/'])
        self.assertFalse(result.ok)

    def test_extract_empty_list(self):
        self.assertFalse(self.wt.web_extract([]).ok)

    def test_extract_up_to_five(self):
        res = self.wt.web_extract(["https://example.com"] * 8)
        self.assertEqual(len(res.output["pages"]), 5)


class WebToolRegistrationTests(unittest.TestCase):
    def setUp(self):
        dns = patch('tools.browser.socket.getaddrinfo', side_effect=_fake_dns)
        dns.start()
        self.addCleanup(dns.stop)
        self.reg = ToolRegistry(_Audit(), _Approvals(), _Policy())
        for t in build_web_tools(fetch=_fake_fetch):
            self.reg.register(t)

    def test_tools_registered(self):
        names = [s["name"] for s in self.reg.schemas()]
        self.assertIn("web_search", names)
        self.assertIn("web_extract", names)

    def test_web_search_executes_through_registry(self):
        res = self.reg.execute("web_search", {"query": "hello"})
        self.assertTrue(res.ok)
        self.assertGreaterEqual(len(res.output.get("results", [])), 1)

    def test_web_extract_executes_through_registry(self):
        res = self.reg.execute("web_extract", {"urls": ["https://example.com/"]})
        self.assertTrue(res.ok)
        self.assertIn("Hello", res.output["pages"][0]["text"])


if __name__ == "__main__":
    unittest.main()
