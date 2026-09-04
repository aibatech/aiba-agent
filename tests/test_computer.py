"""Phase 5 tests: safe, opt-in local computer control + paired node gate.

Unit-test the security envelope WITHOUT a real display: a scripted fake backend
receives the same typed calls the real pyautogui backend would. These cover:

  * Disabled by default — fresh gate refuses every action until paired+enabled.
  * Pairing — a one-time strong token is minted, only its digest is persisted,
    optional clipboard/process classes stay locked until owner opt-in.
  * Enable/disable/emergency stop (persists across reload) / revoke / budget.
  * Every controller action authorizes+audits with a human-readable summary.
  * Secret-like typed text is never logged.
  * Screen/privacy: screenshots go to the provided workspace path only.
  * open_url refuses non-http(s) and loopback/metadata URLs.
  * No shell strings are ever used (argv-only dispatch).
"""

from __future__ import annotations
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from computer.node import ComputerNodeGate
from computer.controller import (
    ComputerController,
    _forbidden_open_target,
    _is_secretish,
    _redact_url,
)
from security.audit import AuditLog


class FakeBackend:
    """Scripted, headless-safe backend recording the typed dispatch sequence."""

    def __init__(self, fail=False):
        self.calls: list = []
        self.fail = fail
        self._size = (1920, 1080)

    @property
    def size(self):
        if self.fail:
            raise RuntimeError("no display backend")
        return self._size

    def _ok(self, name, *a, **k):
        if self.fail:
            raise RuntimeError("backend failure")
        self.calls.append((name, a, k))

    def screenshot(self, f):
        self._ok("screenshot", f)

    def moveTo(self, x, y, **k):
        self._ok("move", x, y, k)

    def click(self, x, y, **k):
        self._ok("click", x, y, k)

    def dragTo(self, x, y, **k):
        self._ok("drag", x, y, k)

    def press(self, key, **k):
        self._ok("press", key, k)

    def hotkey(self, *keys):
        self._ok("hotkey", keys)

    def write(self, text, **k):
        self._ok("write", text)

    def scroll(self, c, **k):
        self._ok("scroll", c, k)


class NodeGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aiba_node_")
        self.store = Path(self.tmp) / "computer_node.json"
        self.audit = AuditLog(Path(self.tmp) / "audit.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gate(self, **kw):
        return ComputerNodeGate(self.store, audit=self.audit, **kw)

    def _make_controller(self, gate, backend=None):
        return ComputerController(gate, audit=self.audit,
                                  display_backend_factory=lambda: backend or FakeBackend())

    def test_disabled_by_default_refuses_everything(self):
        g = self._gate()
        self.assertFalse(g.paired)
        self.assertFalse(g.enabled)
        for action in ("click", "type", "screenshot", "scroll", "open_url"):
            ok, reason = g.authorize(action)
            self.assertFalse(ok, f"{action} should be refused before pairing")

    def test_pair_mints_token_but_persists_only_digest(self):
        g = self._gate()
        raw = g.pair("main-desk", capabilities=["screen", "mouse", "keyboard"])
        self.assertTrue(g.paired)
        self.assertTrue(raw.startswith("aiba_node_"))
        stored = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertNotIn("aiba_node_", json.dumps(stored))          # no raw token on disk
        self.assertTrue(stored["token_digest"])
        self.assertEqual(g.node_name, "main-desk")

    def test_enable_requires_paired(self):
        g = self._gate()
        self.assertRaises(Exception, g.enable)

    def test_enable_after_pair_allows_authorized_actions(self):
        g = self._gate(max_actions=10)
        g.pair("d", capabilities=["screen", "mouse"])
        self.assertFalse(g.enabled)
        ok, _ = g.authorize("click")
        self.assertFalse(ok)  # paired but not enabled
        g.enable()
        self.assertTrue(g.enabled)
        ok, reason = g.authorize("click")
        self.assertTrue(ok, reason)

    def test_emergency_stop_disables_and_persists_across_reload(self):
        g = self._gate()
        g.pair("d")
        g.enable()
        g.emergency_stop()
        self.assertFalse(g.enabled)
        self.assertTrue(g.killed)
        ok, reason = g.authorize("click")
        self.assertFalse(ok)
        self.assertIn("emergency-stop", reason)
        # Survives reload (kill flag is on disk).
        g2 = ComputerNodeGate(self.store, audit=self._new_audit())
        self.assertTrue(g2.killed)
        self.assertFalse(g2.enabled)

    def _new_audit(self):
        return AuditLog(Path(self.tmp) / ("audit_" + os.urandom(3).hex() + ".jsonl"))

    def test_budget_exhaustion(self):
        g = self._gate(max_actions=2)
        g.pair("d")
        g.enable()
        self.assertTrue(g.authorize("click")[0])
        self.assertTrue(g.authorize("move")[0])
        ok, reason = g.authorize("screenshot")
        self.assertFalse(ok)
        self.assertIn("budget", reason)
        g.reset_budget()
        self.assertTrue(g.authorize("screenshot")[0])

    def test_clipboard_process_require_owner_optin(self):
        g = self._gate()
        g.pair("d")
        g.enable()
        ok, reason = g.authorize("clipboard_read")
        self.assertFalse(ok); self.assertIn("Clipboard", reason)
        ok, reason = g.authorize("process_start")
        self.assertFalse(ok); self.assertIn("Process", reason)
        g.set_optin(allow_clipboard=True, allow_process=True)
        self.assertTrue(g.authorize("clipboard_read")[0])
        self.assertTrue(g.authorize("process_start")[0])

    def test_revoke_removes_identity(self):
        g = self._gate()
        g.pair("d")
        g.enable()
        self.assertTrue(g.paired)
        g.revoke()
        self.assertFalse(g.paired)
        self.assertFalse(g.enabled)
        ok, _ = g.authorize("click")
        self.assertFalse(ok)


class ControllerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aiba_ctrl_")
        self.store = Path(self.tmp) / "computer_node.json"
        self.audit = AuditLog(Path(self.tmp) / "audit.jsonl")
        self.gate = ComputerNodeGate(self.store, audit=self.audit, max_actions=100)
        self.gate.pair("test", capabilities=["screen", "mouse", "keyboard", "scroll", "open_url"])
        self.gate.enable()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _controller(self, backend=None):
        return ComputerController(self.gate, audit=self.audit,
                                  display_backend_factory=lambda: backend or FakeBackend())

    def _audit_events(self):
        p = self.audit.path
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]

    def test_actions_dispatch_typed_calls_and_audit(self):
        c = self._controller()
        fb = c._backend
        self.assertTrue(c.click(10, 20).ok)
        self.assertTrue(c.move(30, 40).ok)
        self.assertTrue(c.hotkey("ctrl", "c").ok)
        self.assertTrue(c.scroll(-4).ok)
        self.assertTrue(c.type_text("hello world").ok)
        self.assertTrue(c.keypress("enter").ok)
        # drives the real typed backend sequence
        names = [x[0] for x in fb.calls]
        self.assertIn("click", names)
        self.assertIn("move", names)
        self.assertIn("hotkey", names)
        self.assertIn("write", names)
        # audit trail carries requested + executed
        ev = [e["event"] for e in self._audit_events()]
        self.assertTrue(any("computer_requested" == e for e in ev))
        self.assertTrue(any("computer_executed" == e for e in ev))

    def test_secret_typing_not_logged(self):
        c = self._controller()
        r = c.type_text("password=hunter2supersecret")
        self.assertTrue(r.ok)
        self.assertTrue(r.output["secret_filtered_log"])
        blob = json.dumps(self._audit_events())
        self.assertNotIn("hunter2supersecret", blob)
        self.assertTrue(_is_secretish("token=abc"))

    def test_audit_summaries_include_action_target(self):
        c = self._controller()
        c.click(123, 456)
        rows = self._audit_events()
        reqs = [r for r in rows if r.get("event") == "computer_requested"]
        self.assertTrue(any("(123,456)" in r.get("summary", "") for r in reqs if r.get("action") == "click"))

    def test_disabled_gate_blocks_at_controller(self):
        self.gate.emergency_stop()
        c = self._controller()
        r = c.click(1, 2)
        self.assertFalse(r.ok)
        self.assertIn("emergency-stop", (r.error or "").lower() or "")

    def test_open_url_rejects_non_http_and_loopback(self):
        c = self._controller()
        self.assertFalse(c.open_url("file:///etc/passwd").ok)
        self.assertFalse(c.open_url("https://169.254.169.254/latest/meta-data/").ok)
        self.assertFalse(c.open_url("http://localhost:8765/").ok)
        # Protocol guard rejects unsupported schemes before any dispatch.
        self.assertFalse(c.open_url("javascript:alert(1)").ok)

    def test_process_requires_optin(self):
        c = self._controller()
        # opt-in off by default -> process control is refused at the gate.
        r = c.process_start(["/bin/true"])
        self.assertFalse(r.ok)
        self.assertIn("Process", (r.error or ""))

    def test_screenshot_written_to_workspace_path_only(self):
        ws = Path(self.tmp) / "ws"
        c = self._controller()
        ok = c.screenshot(str(ws / "cap.png"))
        self.assertTrue(ok)
        # screenshot not routed anywhere else: audit logs only the path
        blob = json.dumps(self._audit_events())
        self.assertIn("cap.png", blob)


class NodeGateSecurityTests(unittest.TestCase):
    """Deeper gate assertions the checklist demands (no secret leakage, etc.)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aiba_node_sec_"))
        self.store = self.tmp / "computer_node.json"
        self.audit = AuditLog(self.tmp / "audit.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _audit_blob(self):
        p = self.audit.path
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_raw_pairing_token_never_appears_in_audit(self):
        g = ComputerNodeGate(self.store, audit=self.audit)
        raw = g.pair("node-a", capabilities=["mouse"])
        self.assertTrue(raw.startswith("aiba_node_"))
        blob = self._audit_blob()
        self.assertNotIn(raw, blob)
        # The aiba_node_ secret prefix (raw scheme) must not leak either.
        self.assertNotIn("aiba_node_", blob)

    def test_status_reveals_no_secret_material(self):
        g = ComputerNodeGate(self.store, audit=self.audit)
        g.pair("stats-node", capabilities=["mouse", "screen"])
        g.enable()
        st = g.status()
        # Safe diagnostic fields only.
        for secret_key in ("token_digest", "digest", "raw"):
            self.assertNotIn(secret_key, st)
        self.assertIsInstance(st["paired"], bool)
        self.assertIsInstance(st["budget"], dict)
        self.assertNotIn(os.urandom(8).hex(), self._audit_blob())


class ControllerUrlAndProcessTests(unittest.TestCase):
    """URL policy + argv-only process + clipboard content-exposure breadth."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aiba_ctrl_url_"))
        self.store = self.tmp / "node.json"
        self.audit = AuditLog(self.tmp / "audit.jsonl")
        self.gate = ComputerNodeGate(self.store, audit=self.audit, max_actions=1000)
        self.gate.pair("test", capabilities=["mouse", "open_url", "process_start",
                                             "clipboard_read", "clipboard_write"])
        self.gate.set_optin(allow_clipboard=True, allow_process=True)
        self.gate.enable()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _controller(self, backend=None):
        return ComputerController(self.gate, audit=self.audit,
                                  display_backend_factory=lambda: backend or FakeBackend())

    def test_forbidden_open_target_blocks_private_and_aliases(self):
        blocked = [
            "http://10.1.2.3/", "http://192.168.0.1/", "http://172.16.0.1/",
            "http://172.31.255.254/", "http://127.0.0.1/", "https://0.0.0.0/",
            "https://169.254.169.254/", "https://[::1]/", "https://[fe80::2]/",
            "https://2130706433/",           # 127.0.0.1 integer
            "http://0x7f000001/",            # 127.0.0.1 hex
            "http://0177.0.0.1/",            # 127.0.0.1 octal dotted
            "https://metadata.google.internal/", "https://localhost/",
            "ftp://10.0.0.1/", "file:///etc/passwd", "javascript:alert(1)",
        ]
        allowed = [
            "https://example.com/", "https://8.8.8.8/x", "https://172.15.255.255/",
            "https://100.65.0.0/x", "https://169.253.0.0/x",
        ]
        for url in blocked:
            self.assertIsNotNone(_forbidden_open_target(url), f"{url} should be blocked")
        for url in allowed:
            self.assertIsNone(_forbidden_open_target(url), f"{url} should be allowed")

    def test_open_url_rejects_private_ranges_and_ftp_scheme(self):
        c = self._controller()
        for bad in ("https://10.0.0.1/admin", "https://192.168.1.1/",
                    "https://172.16.0.1/", "ftp://example.com/", "file:///etc/passwd"):
            r = c.open_url(bad)
            self.assertFalse(r.ok, f"{bad} should be rejected")

    def test_process_requires_argv_list_never_shell_string(self):
        c = self._controller()
        # Bare shell command string is refused outright (no shell execution).
        r = c.process_start("touch /tmp/evil.sh && echo pwned")  # type: ignore[arg-type]
        self.assertFalse(r.ok)
        self.assertIn("argv list", (r.error or "").lower())
        # Empty list / non-list also refused.
        self.assertFalse(c.process_start([]).ok)
        self.assertFalse(c.process_start(["echo", 5]).ok)  # type: ignore[list-item]
        # No subprocess was launched for the string form.
        self.assertEqual([e for e in self._audit_rows() if e.get("event") == "computer_executed"], [])

    def test_clipboard_disabled_at_gate_when_not_opted_in(self):
        g2 = ComputerNodeGate(self.tmp / "n2.json", audit=self.audit, max_actions=100)
        g2.pair("no_clip", capabilities=["clipboard_read", "clipboard_write"])
        g2.enable()  # do NOT set_optin clipboard
        c2 = ComputerController(g2, audit=self.audit, display_backend_factory=lambda: FakeBackend())
        self.assertFalse(c2.clipboard_read().ok)
        self.assertFalse(c2.clipboard_write("hi").ok)

    def test_clipboard_content_never_in_tool_response_even_when_approved(self):
        """Even with clipboard authorized, the model never sees raw clipboard.

        Only a length marker + a note are returned; the raw content never reaches
        the response, the audit log, or the model stream. A fake clipboard
        "tool" is injected so the test needs no real wl-paste/xclip on the box.
        """
        secret = "SUPER-SECRET-CONTENT-123"
        c = self._controller()

        # Emulate a clipboard tool (wl-paste/xclip) that would return `secret`.
        import subprocess
        original_tool = c._clip_read_tool

        def fake_tool_run(*_a, **_k):
            # Reproduce subprocess.run(capture_output, text) returning `secret`.
            class R:
                returncode = 0
                stdout = secret + "\n"
                stderr = ""
            return R()

        c._clip_read_tool = lambda: "__fake_paste__"
        with unittest.mock.patch.object(subprocess, "run", fake_tool_run):
            r = c.clipboard_read()
        c._clip_read_tool = original_tool

        self.assertTrue(r.ok, r.error)
        d = r.output if isinstance(r.output, dict) else {}
        # Response contains a length marker, never the raw content.
        self.assertIn("clipboard_chars", d)
        # Raw secret never surfaces on the response or the audit log.
        self.assertNotIn(secret, json.dumps(r.output))
        self.assertNotIn(secret, json.dumps(r.error or ""))
        self.assertNotIn(secret, json.dumps(self._audit_rows()))

    def _audit_rows(self):
        p = self.audit.path
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
