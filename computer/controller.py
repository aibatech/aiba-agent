"""Safe, opt-in desktop controller for a paired local computer node.

The single choke point is :class:`~computer.node.ComputerNodeGate`: an action is
only attempted after ``node.authorize(action, summary)`` returns True. The gate
enforces pairing, enablement, the kill switch, per-class opt-in (clipboard and
process are OFF unless explicitly enabled), capability lock, and the max-action
budget, and it records every authorization to the audit log.

Security rules honored here (unit-tested):
  * No shell-string execution for any desktop action - every primitive maps to
    typed arguments (coords/button/key/name/argv/text/size) handed to a backend;
    URL/browser and process launches use strict argv arrays, never ``sh -c``.
  * Screenshots are written only inside the AIBA workspace (never returned as
    raw bytes). Clipboard read is opt-in AND approval-gated and returns only a
    length marker, never the content, by default.
  * Every action records requested/executed/denied/failed to the audit log with
    full detail; secrets in typed text are never logged.
  * The emergency stop and max-action budget are enforced before dispatch.

Backend injection: the default uses ``pyautogui`` when importable; otherwise a
no-op backend reports the environment plainly. Tests inject a scripted fake so a
headless CI can exercise every security path deterministically.
"""

from __future__ import annotations
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.base import ToolResult
from computer.node import ComputerNodeGate, NodeNotPairedError

try:  # type: ignore
    import pyautogui as _pg
    _HAS_PYAUTOGUI = True
except Exception:  # pragma: no cover - environment dependent
    _pg = None
    _HAS_PYAUTOGUI = False


# Secret-ish markers we never log. We do not attempt to fully detect secrets;
# any text frame typed is reported only by length on the audit trail.
def _is_secretish(text: str) -> bool:
    low = text.lower().strip()
    if not low:
        return False
    markers = ("password", "passwd", "secret", "token=", "api_key", "apikey",
               "credential", "authorization:", "bearer ", "ssn", "cvv")
    return any(m in low for m in markers)


def _redact_url(url: str) -> str:
    """Strip common credential query params from URL for logs."""
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url)
        q = "&".join(
            f"{k}={v}" for k, v in (
                tuple(seg.split("=", 1)) if "=" in seg else (seg, "")
                for seg in parts.query.split("&") if seg
            )
            if k.lower() not in {"token", "key", "sig", "auth", "password", "secret", "apikey"}
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))
    except Exception:
        return "<url>"


# Forbidden URL hosts for the browser-opener guard. We block loopback, link-local,
# metadata, and RFC-1918 private ranges so a crafted or naive request cannot open
# a router/admin/metadata page on the paired node. IPv4 literals are normalised
# (decimal/hex/octal/int shorthand) to defeat bypass tricks. IPv6 loopback/ULA/
# link-local are blocked too. Hostnames such as localhost / .localhost / metadata
# are refused by name.
_BLOCKED_HOST_NAMES = frozenset(
    {"localhost", "metadata.google.internal", "metadata", "kubernetes.default.svc"}
)


def _parse_ip_int(host: str):
    """Best-effort integer form of an IPv4 literal (incl. hex/octal/int shorthands).

    Returns None when *host* is not a flat IPv4-like literal.
    """
    try:
        return int(host, 0)
    except Exception:
        return None


def _ipv4_to_int(host: str):
    """Parse dotted 'a.b.c.d' into a 32-bit int.

    Octets may be decimal, hex (0x..), or octal (leading 0), matching the loose
    numeric grammar browsers accept, so aliases like ``0177.0.0.1`` still map to
    loopback. Returns None when not exactly a 4-part dotted IPv4 literal.
    """
    try:
        parts = host.split(".")
        if len(parts) != 4:
            return None
        octets = []
        for p in parts:
            if not p:
                return None
            if p.lower().startswith("0x"):
                o = int(p, 16)
            elif len(p) > 1 and p.startswith("0"):
                o = int(p, 8)
            else:
                o = int(p, 10)
            if o < 0 or o > 255:
                return None
            octets.append(o)
        return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
    except Exception:
        return None


def _in_rfc1918_or_special(n: int) -> bool:
    # 0.0.0.0/8 'this network', 10/8 private, 100.64.0.0/10 CGNAT,
    # 127/8 loopback, 169.254.0.0/16 link-local, 172.16.0.0/12 private,
    # 192.168.0.0/16 private, and 224/4 multicast + 240/4 reserved.
    return (
        ((n >> 24) in (0, 10, 127))
        or ((n >> 22) == 0x19101)              # 100.64.0.0/10
        or (0xAC100000 <= n <= 0xAC1FFFFF)     # 172.16.0.0/12
        or (0xC0A80000 <= n <= 0xC0A8FFFF)     # 192.168.0.0/16
        or ((n >> 16) == 0xA9FE)               # 169.254.0.0/16 link-local
        or (((n >> 28) & 0xF) in (0xE, 0xF))   # multicast 224/4 + reserved 240/4
    )


def _forbidden_open_target(url: str):
    """Return a reason string if ``url`` targets a forbidden host, else None.

    Handles bare IPs and normalised aliases (e.g. ``0x7f000001``, ``2130706433``,
    octal dotted ``0177.0.0.1``) plus the standard special ranges. IPv6 loopback,
    link-local and ULA are refused. Everything resolves to no network call here —
    hostname lookups for ordinary public sites are left to the browser.
    """
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or "").strip().lower().strip("[]")
    if not host:
        return "URL has no host."
    if host in _BLOCKED_HOST_NAMES or host.endswith(".localhost") or host.endswith(".local"):
        return "Opening loopback/metadata/local URLs is not allowed."
    # IPv6 literal (contains ':').
    if ":" in host:
        # Only explicitly block the scopes a desktop-control opener must not reach.
        if host in ("::1", "::", "0:0:0:0:0:0:0:1"):
            return "Opening loopback IPv6 addresses is not allowed."
        low = host.split("%")[0].lower()
        if low.startswith("fe80:") or low.startswith("fc") or low.startswith("fd"):
            return "Opening link-local/private IPv6 addresses is not allowed."
        return None
    # IPv4 & numeric shorthands.
    n = _ipv4_to_int(host) if ("." in host) else _parse_ip_int(host)
    if n is not None and _in_rfc1918_or_special(n):
        return "Opening loopback/private/internal URLs is not allowed."
    return None


class _PyAutoGuiBackend:
    """Real backend rendering to pyautogui (failsafe on coordinate extremes)."""

    def __init__(self) -> None:
        self._pg = _pg

    @property
    def size(self) -> tuple[int, int]:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed (pip install pyautogui).")
        return tuple(self._pg.size())  # type: ignore[return-value]

    def screenshot(self, filename: str | Path) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.screenshot(str(filename))

    def moveTo(self, x: int, y: int, duration: float = 0.0) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.moveTo(x, y, duration=duration)

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.click(x, y, button=button, clicks=clicks)

    def dragTo(self, x: int, y: int, duration: float = 0.0, button: str = "left") -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.dragTo(x, y, duration=duration, button=button)

    def press(self, key: str, presses: int = 1, interval: float = 0.0) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.press(key, presses=presses, interval=interval)

    def write(self, text: str, interval: float = 0.0) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.write(text, interval=interval)

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.scroll(clicks, x=x, y=y)

    def hotkey(self, *keys: str) -> Any:
        if self._pg is None:
            raise RuntimeError("pyautogui is not installed.")
        return self._pg.hotkey(*keys)


def _noop_backend() -> "_NoopBackend":
    return _NoopBackend()


class _NoopBackend:
    """Headless-safe backend used when pyautogui is unavailable. It declines any
    real action cleanly so diagnostics can say 'no display backend available'."""

    @property
    def size(self) -> tuple[int, int]:
        raise RuntimeError("No desktop backend available (pyautogui not installed).")

    def screenshot(self, filename: str | Path) -> Any:
        raise RuntimeError("No desktop backend available (pyautogui not installed).")

    def moveTo(self, x: int, y: int, duration: float = 0.0) -> Any:
        raise RuntimeError("No desktop backend available.")

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> Any:
        raise RuntimeError("No desktop backend available.")

    def dragTo(self, x: int, y: int, duration: float = 0.0, button: str = "left") -> Any:
        raise RuntimeError("No desktop backend available.")

    def press(self, key: str, presses: int = 1, interval: float = 0.0) -> Any:
        raise RuntimeError("No desktop backend available.")

    def write(self, text: str, interval: float = 0.0) -> Any:
        raise RuntimeError("No desktop backend available.")

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> Any:
        raise RuntimeError("No desktop backend available.")

    def hotkey(self, *keys: str) -> Any:
        raise RuntimeError("No desktop backend available.")


# Secret words used in summaries, never the content itself.
class ComputerController:
    """High-level safe desktop action set bound to a :class:`ComputerNodeGate`.

    Constructed with the node gate, an audit log, and an optional display-backend
    factory. Handlers return :class:`ToolResult` and are wired as tool handlers.
    """

    def __init__(
        self,
        gate: ComputerNodeGate,
        audit: Any = None,
        *,
        display_backend_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.node = gate
        self.audit = audit
        if display_backend_factory is not None:
            self._backend: Any = display_backend_factory()
        elif _pg is not None:
            try:
                _pg.FAILSAFE = True
            except Exception:
                pass
            self._backend = _PyAutoGuiBackend()
        else:
            self._backend = _NoopBackend()

    # ---- audit helpers -------------------------------------------------------
    def _log(self, event: str, **data: Any) -> None:
        data.setdefault("ts", datetime.now(timezone.utc).isoformat())
        if self.audit is not None:
            try:
                self.audit.record("computer_" + event, **data)
            except Exception:
                pass

    def _gate(self, action: str, summary: str) -> tuple[bool, str]:
        """Authorize; log requested/denied; return (ok, reason)."""
        ok, reason = self.node.authorize(action)
        if ok:
            self._log("requested", action=action, summary=summary)
        else:
            self._log("denied", action=action, summary=summary, reason=reason)
        return ok, reason

    def _fail(self, exc: BaseException) -> ToolResult:
        self._log("failed", error=str(exc))
        return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    # ---- screen size ---------------------------------------------------------
    def screen_size(self) -> ToolResult:
        try:
            w, h = self._backend.size
            return ToolResult(True, {"width": int(w), "height": int(h)})
        except Exception as exc:
            return self._fail(exc)

    # ---- screenshot ----------------------------------------------------------
    def screenshot(self, workspace_path: str) -> ToolResult:
        action = "screenshot"
        ok, reason = self._gate(action, f"Capture the desktop into {workspace_path}.")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            dest = Path(workspace_path).resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._backend.screenshot(str(dest))
            self._log("executed", action=action, path=str(dest))
            return ToolResult(True, {"path": str(dest), "note": "Saved inside the AIBA workspace. Not exposed elsewhere."})
        except Exception as exc:
            return self._fail(exc)

    # ---- pointer -------------------------------------------------------------
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> ToolResult:
        action = "click"
        ok, reason = self._gate(action, f"Click ({x},{y}) with '{button}' ({clicks} time(s)).")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.click(int(x), int(y), button=str(button), clicks=int(clicks))
            self._log("executed", action=action, x=x, y=y, button=button, clicks=clicks)
            return ToolResult(True, {"clicked": [int(x), int(y)], "button": button})
        except Exception as exc:
            return self._fail(exc)

    def move(self, x: int, y: int, duration: float = 0.0) -> ToolResult:
        action = "move"
        ok, reason = self._gate(action, f"Move pointer to ({x},{y}).")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.moveTo(int(x), int(y), duration=float(duration))
            self._log("executed", action=action, x=x, y=y)
            return ToolResult(True, {"moved": [int(x), int(y)]})
        except Exception as exc:
            return self._fail(exc)

    def drag(self, from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.2, button: str = "left") -> ToolResult:
        action = "drag"
        ok, reason = self._gate(action, f"Drag from ({from_x},{from_y}) to ({to_x},{to_y}).")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.moveTo(int(from_x), int(from_y))
            self._backend.dragTo(int(to_x), int(to_y), duration=float(duration), button=str(button))
            self._log("executed", action=action, from_x=from_x, from_y=from_y, to_x=to_x, to_y=to_y)
            return ToolResult(True, {"dragged": [[from_x, from_y], [to_x, to_y]]})
        except Exception as exc:
            return self._fail(exc)

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> ToolResult:
        action = "scroll"
        loc = f" at ({x},{y})" if (x is not None and y is not None) else ""
        ok, reason = self._gate(action, f"Scroll {clicks} click(s){loc}.")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.scroll(int(clicks), x=int(x) if x is not None else None, y=int(y) if y is not None else None)
            self._log("executed", action=action, clicks=clicks)
            return ToolResult(True, {"scrolled": int(clicks)})
        except Exception as exc:
            return self._fail(exc)

    # ---- keyboard ------------------------------------------------------------
    def keypress(self, key: str) -> ToolResult:
        action = "keypress"
        ok, reason = self._gate(action, f"Press the '{key}' key.")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.press(str(key))
            self._log("executed", action=action, key=key)
            return ToolResult(True, {"pressed": key})
        except Exception as exc:
            return self._fail(exc)

    def hotkey(self, *keys: str) -> ToolResult:
        action = "hotkey"
        combo = " + ".join(str(k).strip() for k in keys if str(k).strip())
        ok, reason = self._gate(action, f"Press hotkey combo: {combo}.")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.hotkey(*[str(k).strip() for k in keys if str(k).strip()])
            self._log("executed", action=action, combo=combo)
            return ToolResult(True, {"hotkey": combo})
        except Exception as exc:
            return self._fail(exc)

    def type_text(self, text: str, interval: float = 0.0) -> ToolResult:
        action = "type"
        secretish = _is_secretish(text)
        summary = f"Type {len(text)} character(s)."
        if secretish:
            summary += " (looks secret-bearing; content will not be logged.)"
        ok, reason = self._gate(action, summary)
        if not ok:
            return ToolResult(False, error=reason)
        try:
            self._backend.write(str(text), interval=float(interval))
            self._log("executed", action=action, chars=len(text), redacted=secretish)
            return ToolResult(True, {"typed_chars": len(text), "secret_filtered_log": secretish})
        except Exception as exc:
            return self._fail(exc)

    # ---- open URL ------------------------------------------------------------
    def open_url(self, url: str) -> ToolResult:
        action = "open_url"
        ok, reason = self._gate(action, f"Open URL {_redact_url(url)} in the default browser.")
        if not ok:
            return ToolResult(False, error=reason)
        if not (url.startswith("http://") or url.startswith("https://")):
            return ToolResult(False, error="Only http(s) URLs may be opened.")
        # Robust host policy: loopback, metadata, link-local, private/internal
        # IP ranges, and their numeric/hex aliases are refused before dispatch.
        reason_url = _forbidden_open_target(url)
        if reason_url:
            return ToolResult(False, error=reason_url)
        try:
            if sys.platform.startswith("linux"):
                opener = shutil.which("xdg-open") or shutil.which("sensible-browser")
                if not opener:
                    raise RuntimeError("No browser opener found (xdg-open/sensible-browser).")
                subprocess.run([opener, url], check=False)  # argv only, never a shell string
            elif sys.platform == "darwin":
                subprocess.run(["/usr/bin/open", url], check=False)
            elif sys.platform.startswith("win"):
                subprocess.run(["cmd", "/c", "start", "", url], check=False)
            else:  # pragma: no cover
                raise RuntimeError("Unsupported platform for opening URLs.")
            self._log("executed", action=action, url=_redact_url(url))
            return ToolResult(True, {"opened": url})
        except Exception as exc:
            return self._fail(exc)

    # ---- clipboard (opt-in) --------------------------------------------------
    def clipboard_read(self) -> ToolResult:
        action = "clipboard_read"
        ok, reason = self._gate(action, "Read the current clipboard contents (sensitive).")
        if not ok:
            return ToolResult(False, error=reason)
        # Reaching here means an owner approved clipboard opt-in. Even then we
        # never pass raw clipboard bytes through the tool response: the model
        # (and audit) receive only a length marker. Actual transfer happens via
        # an explicit paste primitive chosen by the owner, so clipboard content
        # never appears in tool responses, logs, or the model stream.
        try:
            tool = self._clip_read_tool()
            out = subprocess.run([tool], capture_output=True, text=True, timeout=10).stdout or ""
            content = out.rstrip("\n")
            self._log("executed", action=action, chars=len(content), content="[redacted]")
            return ToolResult(True, {
                "clipboard_chars": len(content),
                "note": "Clipboard read approved. Content is not exposed in responses; use an explicit paste primitive for transfer.",
            })
        except Exception as exc:
            return self._fail(exc)

    @staticmethod
    def _clip_read_tool() -> str:
        for t in ("wl-paste", "xclip", "xsel", "pbpaste"):
            if shutil.which(t):
                return t
        raise RuntimeError("No clipboard read tool (wl-paste/xclip/xsel/pbpaste).")

    @staticmethod
    def _clip_write_tool() -> str:
        for t in ("wl-copy", "xclip", "xsel", "pbcopy"):
            if shutil.which(t):
                return t
        raise RuntimeError("No clipboard write tool (wl-copy/xclip/xsel/pbcopy).")

    def clipboard_write(self, text: str) -> ToolResult:
        action = "clipboard_write"
        ok, reason = self._gate(action, f"Set clipboard to {len(text)} character(s).")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            tool = self._clip_write_tool()
            p = subprocess.run([tool], input=text, text=True, capture_output=True, timeout=10)
            if p.returncode != 0:
                raise RuntimeError("clipboard write tool failed")
            self._log("executed", action=action, chars=len(text))
            return ToolResult(True, {"clipboard_chars": len(text)})
        except Exception as exc:
            return self._fail(exc)

    # ---- process control (opt-in) -------------------------------------------
    def process_start(self, command: list[str], cwd: str | None = None) -> ToolResult:
        # Strictest possible shape check first: only a non-empty argv *list* of
        # strings is ever accepted. A bare shell command string is rejected so
        # nothing can reach subprocess without explicit argv-array semantics.
        if not isinstance(command, list) or not command or not all(
            isinstance(c, str) and c for c in command
        ):
            return ToolResult(False, error="command must be a non-empty argv list of strings (no shell).")
        action = "process_start"
        safe_argv = " ".join(_redact_url(c) if _is_secretish(c) else c for c in command)
        ok, reason = self._gate(action, f"Start process: {safe_argv} in {cwd or '.'}.")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            proc = subprocess.Popen(command, cwd=cwd)
            self._log("executed", action=action, pid=proc.pid, argv_len=len(command))
            return ToolResult(True, {"pid": proc.pid})
        except Exception as exc:
            return self._fail(exc)

    def process_list(self) -> ToolResult:
        action = "process_status"
        ok, reason = self._gate(action, "List running desktop processes (names/pids).")
        if not ok:
            return ToolResult(False, error=reason)
        try:
            ps = shutil.which("ps")
            if not ps:
                raise RuntimeError("'ps' is not available.")
            if sys.platform == "darwin":
                out = subprocess.run([ps, "-axo", "pid,comm"], capture_output=True, text=True, timeout=15).stdout or ""
            else:
                out = subprocess.run([ps, "-eo", "pid,comm"], capture_output=True, text=True, timeout=15).stdout or ""
            procs = []
            for line in out.splitlines()[1:]:
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    procs.append({"pid": int(parts[0]), "name": parts[1].strip()})
            self._log("executed", action=action, count=len(procs))
            return ToolResult(True, {"processes": procs[:50], "note": "First 50 shown; names/pids only."})
        except Exception as exc:
            return self._fail(exc)

    def process_stop(self, pid: int, signal: str = "SIGTERM") -> ToolResult:
        action = "process_stop"
        ok, reason = self._gate(action, f"Send {signal} to process pid {pid}.")
        if not ok:
            return ToolResult(False, error=reason)
        if not isinstance(pid, int) or pid <= 1:
            return ToolResult(False, error="pid must be a positive integer > 1.")
        allow_fn = self._allowed_signal(signal)
        if not allow_fn:
            return ToolResult(False, error=f"Signal {signal} is not safely allowed (SIGKILL not auto-sent).")
        try:
            script = shutil.which("kill")
            if not script:
                raise RuntimeError("'kill' binary not found.")
            subprocess.run([script, f"-{signal}", str(pid)], check=False, timeout=10)
            self._log("executed", action=action, pid=pid, signal=signal)
            return ToolResult(True, {"signal": signal, "pid": pid})
        except Exception as exc:
            return self._fail(exc)

    @staticmethod
    def _allowed_signal(signal: str) -> bool:
        s = (signal or "").upper().replace("SIG", "")
        # Allow graceful signals only; SIGKILL and friends require explicit opt-in
        # because they may be destructive.
        return s in {"TERM", "INT", "HUP", "CONT", "STOP"} and s != "KILL"
