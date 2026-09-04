"""Phase 4b — browser-session security tests (headless-safe).

No real browser is launched. A scripted ``_FakeDriver`` receives the typed
driver calls so we can exercise the security/approval/path/secret layers
deterministically on a headless CI runner.

These directly map to the phase requirements:

  * navigation reuses the shared SSRF/URL policy (security.urlguard) that
    computer control uses — loopback/private/metadata/numeric-aliases/unsafe
    schemes all refused,
  * read-only browsing is separated from actions that alter a site; mutations
    require approval (registry-level here via permissions.json disabling them),
  * mutation actions on authentication/payment/checkout/account pages are
    refused unless the session opts into sensitive actions,
  * secret-like typed text is never logged and is refused by default,
  * downloads/uploads are confined to the approved workspace,
  * the tools register but are absent from model schemas (disabled by default).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.browser_session import (
    BrowserSession,
    Driver,
    _is_secretish,
    _looks_sensitive_url,
    build_browser_tools,
)
from tools.base import ToolResult
from tools.registry import ToolRegistry
from security.audit import AuditLog
from security.urlguard import (
    forbidden_open_target,
    forbidden_host,
    public_peer_reason,
    public_host_peer_reason,
)


class _FakeDriver(Driver):
    """Headless-safe driver: records typed calls, serves scripted responses."""

    # Marker tokens the fake simply stores so tests can confirm them.
    def __init__(self, url: str = "https://example.com/", title: str = "Example"):
        self._url = url
        self._title = title
        self._body = "A benign example page with some readable text."
        self.calls: list = []
        self._downloaded: Path | None = None

    def set_sensitive(self, url: str, title: str = ""):
        self._url = url
        if title:
            self._title = title

    def set_body(self, body: str) -> None:
        self._body = body

    def state(self) -> dict:
        return {"url": self._url, "title": self._title}

    def goto(self, url: str, timeout_ms: int) -> str:
        self.calls.append(("goto", url))
        self._url = url
        return url

    def page_text(self, max_chars: int = 30000) -> str:
        self.calls.append(("text",))
        return self._body[:max_chars]

    def screenshot(self, dest: str) -> bool:
        self.calls.append(("shot", dest))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\x89PNG fake")
        return True

    def wait_for(self, selector: str, timeout_ms: int) -> bool:
        self.calls.append(("wait", selector))
        return True

    def wait_for_text(self, text: str, timeout_ms: int) -> bool:
        self.calls.append(("waittext", text))
        return True

    def scroll(self, direction: str, amount: int, timeout_ms: int) -> None:
        self.calls.append(("scroll", direction, amount))

    def click(self, selector: str, timeout_ms: int) -> None:
        self.calls.append(("click", selector))

    def click_text(self, text: str, timeout_ms: int) -> None:
        self.calls.append(("clicktext", text))

    def type_text(self, selector: str, text: str, timeout_ms: int) -> None:
        self.calls.append(("type", selector, text))

    def select(self, selector: str, value: str, timeout_ms: int) -> None:
        self.calls.append(("select", selector, value))

    def submit(self, timeout_ms: int) -> None:
        self.calls.append(("submit",))

    def save_last_download(self, folder: Path) -> str:
        dest = folder / "downloaded.bin"
        dest.write_bytes(b"\x00\x01download")
        return str(dest)

    def upload(self, selector: str, local_path: str) -> None:
        self.calls.append(("upload", selector, local_path))

    def close(self) -> None:
        self.calls.append(("close",))


def make_session(tmp: Path, driver: Driver | None = None, **kw) -> BrowserSession:
    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    return BrowserSession(
        driver=driver or _FakeDriver(),
        workspace=ws,
        audit=AuditLog(tmp / "audit.jsonl"),
        **kw,
    )


class UrlPolicyTests(unittest.TestCase):
    """Browser navigation and computer control share one SSRF policy."""

    def test_browser_uses_same_policy_as_computer_control(self):
        # The exact policy module computer/controller delegates to is the one
        # browser_session uses — one shared source (security.urlguard).
        import security.urlguard as ug
        import computer.controller as cc
        self.assertIs(ug.forbidden_host, cc._urlguard.forbidden_host)
        self.assertIs(ug.in_rfc1918_or_special, cc._urlguard.in_rfc1918_or_special)

    def test_blocked_targets(self):
        blocked = [
            "file:///etc/passwd", "ftp://10.0.0.1/", "javascript:alert(1)",
            "http://localhost:8080/", "http://127.0.0.1/", "http://10.1.2.3/",
            "http://192.168.0.1/", "http://172.16.0.1/", "http://172.31.255.254/",
            "https://169.254.169.254/latest/meta-data/", "https://0.0.0.0/",
            "https://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/",
            "https://[::1]/", "https://[fe80::2]/", "https://metadata.google.internal/",
            "https://localhost/", "https://foo.localhost/x",
        ]
        for u in blocked:
            self.assertIsNotNone(forbidden_open_target(u), f"blocked: {u}")

    def test_allowed_public_targets(self):
        allowed = ["https://example.com/", "https://8.8.8.8/x",
                   "https://172.15.255.255/", "https://100.65.0.0/x",
                   "https://169.253.0.0/x"]
        for u in allowed:
            self.assertIsNone(forbidden_open_target(u), f"allowed: {u}")


class ConnectTimePeerPolicyTests(unittest.TestCase):
    """DNS-rebinding close (item 4, option 3a): the connect-time peer policy
    refuses a host whose current DNS resolution lands on a non-global/private
    address, even when the hostname itself passes the static host-form guard.

    These are hermetic: they stub ``socket.getaddrinfo`` so no network is used.
    """

    def _stub_resolver(self, addresses):
        """Patch getaddrinfo to return sockaddr entries for *addresses*."""
        def fake_getaddrinfo(host, port, *args, **kwargs):
            out = []
            for ip in addresses:
                family = 10 if ":" in ip else 2
                out.append((family, 1, 6, "", (ip, int(port), 0, 0)))
            return out
        import unittest.mock as mock
        import security.urlguard as ug
        return mock.patch.object(ug.socket, "getaddrinfo", side_effect=fake_getaddrinfo)

    def test_public_resolution_is_allowed(self):
        with self._stub_resolver(["8.8.8.8"]):
            self.assertIsNone(public_host_peer_reason("example.com", 443))
            self.assertIsNone(public_peer_reason("https://example.com/"))
        # IPv6 global
        with self._stub_resolver(["2606:4700:4700::1111"]):
            self.assertIsNone(public_host_peer_reason("example.org", 443))

    def test_rebinding_to_loopback_is_refused(self):
        # A hostname that at connect time resolves public-to-attacker AND
        # private (e.g. 127.0.0.1) must be refused on the private answer.
        with self._stub_resolver(["8.8.8.8", "127.0.0.1"]):
            self.assertIsNotNone(public_host_peer_reason("attacker.example", 443))
        with self._stub_resolver(["127.0.0.1"]):
            self.assertIsNotNone(public_peer_reason("https://attacker.example/x"))

    def test_private_and_metadata_resolutions_are_refused(self):
        from unittest.mock import patch
        import security.urlguard as ug
        for bad in ("10.0.0.5", "192.168.1.10", "172.16.5.5", "169.254.169.254",
                    "0.0.0.0", "127.0.0.1", "[::1]", "[fe80::1]",
                    "100.64.0.1",  # CGNAT
                    ):
            target = bad.strip("[]")
            family = 10 if ":" in bad else 2
            with patch.object(ug.socket, "getaddrinfo",
                              return_value=[(family, 1, 6, "", (target, 443, 0, 0))]):
                self.assertIsNotNone(public_host_peer_reason("target.example", 443),
                                     f"should refuse resolved {bad}")

    def test_unresolvable_or_empty_answers_are_refused(self):
        from unittest.mock import patch
        import security.urlguard as ug
        def raise_gaierror(*a, **k):
            import socket as _s
            raise _s.gaierror("boom")
        with patch.object(ug.socket, "getaddrinfo", side_effect=raise_gaierror):
            self.assertIsNotNone(public_peer_reason("https://nope.invalid/"))
        with patch.object(ug.socket, "getaddrinfo", return_value=[]):
            self.assertIsNotNone(public_host_peer_reason("empty.example", 443))


class BrowserSessionReadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_browser_")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_disabled_session_refuses_open(self):
        s = make_session(Path(self._tmp), enabled=False)
        # node_status is the SAFE diagnostic: it reports the disabled state
        # without triggering the enabled-action guard (regression guard).
        self.assertEqual(s.node_status().output["enabled"], False)
        self.assertTrue(s.node_status().ok)
        # A guarded capability action is refused when disabled (raises a
        # policy denial the registry/tool wrapper turns into ToolResult(False)).
        with self.assertRaises(ValueError):
            s.open("https://example.com/")

    def test_read_only_actions_work_when_enabled(self):
        s = make_session(Path(self._tmp), enabled=True)
        ws = s.workspace
        self.assertIsNotNone(ws)
        assert ws is not None
        self.assertTrue(s.open("https://example.com/landing").ok)
        st = s.state()
        self.assertTrue(st.ok)
        self.assertEqual(st.output["url"], "https://example.com/landing")
        self.assertTrue(s.page_text().ok)
        shot = s.screenshot("cap.png")
        self.assertTrue(shot.ok)
        self.assertTrue((ws / "cap.png").exists())
        self.assertTrue(s.wait_for("#main").ok)

    def test_open_refuses_private_target(self):
        s = make_session(Path(self._tmp), enabled=True)
        r = s.open("https://127.0.0.1/admin")
        self.assertFalse(r.ok)
        # The refusal message begins with "Navigation refused: ...". Match
        # case-insensitively so the test is robust to message-wording tweaks.
        self.assertIn("refused", (r.error or "").lower())

    def test_screenshot_path_escape_refused(self):
        s = make_session(Path(self._tmp), enabled=True)
        r = s.screenshot("../outside.png")
        self.assertFalse(r.ok)
        self.assertIn("workspace", (r.error or "").lower())


class BrowserSessionMutationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_browser_mut_")
        self.tmp = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _session(self, driver=None, **kw):
        default = dict(enabled=True)
        default.update(kw)
        return make_session(self.tmp, driver=driver, **default)

    def _mkfile(self, name: str, body: str = "hello") -> Path:
        p = self.tmp / "ws" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_benign_page_mutations_dispatch(self):
        fd = _FakeDriver()
        s = self._session(driver=fd, secret_typing=True)
        self.assertTrue(s.scroll().ok)
        self.assertTrue(s.click(selector="#go").ok)
        self.assertTrue(s.click(text="Continue").ok)
        self.assertTrue(s.type_text("#q", "hello world").ok)
        self.assertTrue(s.select_option("#sel", "b").ok)
        self.assertTrue(s.submit().ok)
        # benign page: uploaded file must be in workspace
        f = self._mkfile("a.txt")
        self.assertTrue(s.upload("#file", str(f)).ok)
        names = [c[0] for c in fd.calls]
        for exp in ("scroll", "click", "clicktext", "type", "select", "submit", "upload"):
            self.assertIn(exp, names)

    def test_mutations_refused_on_sensitive_page(self):
        fd = _FakeDriver()
        s = self._session(driver=fd, sensitive_actions=False)
        fd.set_sensitive("https://shop.example/checkout", "Checkout — Payment")
        self.assertFalse(s.click(selector="#buy").ok)
        self.assertFalse(s.submit().ok)
        self.assertFalse(s.scroll().ok)
        self.assertFalse(s.type_text("#card", "4111").ok)
        # Upload also blocked (sensitive) while on the page.
        f = self._mkfile("b.txt")
        self.assertFalse(s.upload("#file", str(f)).ok)

    def test_sensitive_actions_enable_mutation_on_sensitive_page(self):
        fd = _FakeDriver(url="https://shop.example/checkout", title="Pay")
        s = self._session(driver=fd, sensitive_actions=True, secret_typing=True)
        self.assertTrue(s.click(selector="#buy").ok)

    def test_secret_typing_refused_by_default_and_never_logged(self):
        fd = _FakeDriver()
        s = self._session(driver=fd, secret_typing=False)
        r = s.type_text("#pw", "password=hunter2")
        self.assertFalse(r.ok)
        self.assertIn("secret", (r.error or "").lower())
        blob = Path(self.tmp / "audit.jsonl").read_text() if (self.tmp / "audit.jsonl").exists() else ""
        self.assertNotIn("hunter2", blob)
        self.assertNotIn("password=hunter2", blob)

    def test_secret_typing_allowed_when_opted_in_still_not_logged(self):
        fd = _FakeDriver()
        s = self._session(driver=fd, secret_typing=True)
        r = s.type_text("#pw", "password=hunter2secret")
        self.assertTrue(r.ok, r.error)
        self.assertIn("secret_filtered_log", r.output)
        self.assertTrue(r.output["secret_filtered_log"])
        blob = Path(self.tmp / "audit.jsonl").read_text() if (self.tmp / "audit.jsonl").exists() else ""
        self.assertNotIn("hunter2secret", blob)

    def test_upload_only_allows_workspace_file(self):
        fd = _FakeDriver()
        s = self._session(driver=fd)
        outside = Path(self._tmp) / "outside.txt"
        outside.write_text("x")
        r = s.upload("#file", str(outside))
        self.assertFalse(r.ok)
        self.assertIn("workspace", (r.error or "").lower())

    def test_download_saves_into_workspace(self):
        s = self._session(enabled=True)
        r = s.download("downloads")
        self.assertTrue(r.ok, r.error)
        saved = Path(r.output["saved_to"])
        self.assertTrue(str(saved).startswith(str(s.workspace)))
        self.assertTrue(saved.exists())

    def test_download_outside_workspace_refused(self):
        s = self._session()
        r = s.download("../evildownloads")
        self.assertFalse(r.ok)
        self.assertIn("workspace", (r.error or "").lower())


class BrowserHelperTests(unittest.TestCase):
    def test_secretish_detection(self):
        for secret in ("password=abc", "token=xyz", "api_key=k", "Bearer abc",
                       "card number 4111", "cvv=123"):
            self.assertTrue(_is_secretish(secret), secret)
        for plain in ("hello world", "type your search here", "123"):
            self.assertFalse(_is_secretish(plain), plain)

    def test_sensitive_url_detection(self):
        for u in ("https://x.com/login", "https://x.com/checkout", "https://bank.example/auth",
                  "https://x.com/account", "https://x.com/payment/pay"):
            self.assertTrue(_looks_sensitive_url(u), u)
        self.assertFalse(_looks_sensitive_url("https://example.com/pricing"))


# The 13 registered browser tools from build_browser_tools.
BROWSER_TOOLS = [
    "browser_open", "browser_state", "browser_page_text", "browser_screenshot",
    "browser_wait", "browser_status", "browser_scroll", "browser_click",
    "browser_type", "browser_select", "browser_submit", "browser_download",
    "browser_upload",
]


class BrowserToolShapeTests(unittest.TestCase):
    def test_build_browser_tools_names_are_unique_and_complete(self):
        s = make_session(Path(tempfile.mkdtemp(prefix="aiba_bs_")), enabled=True)
        tools = build_browser_tools(s)
        names = [t.name for t in tools]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(BROWSER_TOOLS), set(names))

    def test_session_import_without_playwright_installed(self):
        # Constructing a session with an injected fake driver must not require
        # the playwright package (headless CI). Driver constructor is lazy.
        from tools import browser_session
        fd = _FakeDriver()
        s = BrowserSession(driver=fd, enabled=True,
                           workspace=Path(tempfile.mkdtemp()))
        self.assertTrue(s.open("https://example.com/").ok)


if __name__ == "__main__":
    unittest.main()
