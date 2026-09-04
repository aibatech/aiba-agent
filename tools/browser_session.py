"""Phase 4b — opt-in automated browser session (AIBA_BROWSER_ENABLED).

A persistent, approval- and SSRF-guarded browser automation surface built on
Playwright, mirroring the computer-control layer's security shape:

* Disabled by default (feature flag AIBA_BROWSER_ENABLED + permissions.json +
  manifest default_enabled:false).
* navigation and every outbound request is routed through the SAME URL/SSRF
  policy as computer control (``security.urlguard``) — loopback, private /
  internal / metadata ranges, numeric aliases and non-http(s) schemes are
  refused, and subresource requests to forbidden targets are aborted.
* Read-only actions (open, read text/state, screenshot, wait) are separated
  from actions that alter a site (click, type, select, submit, scroll,
  download, upload). Mutations require approval by default (via
  permissions.json ``requires_approval`` on the ``*_mutation`` tools).
* A sensitive-context guard refuses form actions on authentication, payment,
  checkout, account and purchase pages unless the owner opts in. Password /
  secret-like typed text is never logged and, by default, refused.
* Downloads land only inside the AIBA workspace; uploads only read files
  already inside the workspace.
* All actions audit against the shared AuditLog.

The default driver boots a real headless Chromium via Playwright. Automated
tests inject a :class:`_FakeDriver` so no browser or display is needed on the
CI runner — the security/approval/path layers are tested hermetically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from tools.base import ToolResult

try:  # pragma: no cover - environment
    from security.urlguard import forbidden_open_target as _url_allowed_reason
    from security.urlguard import public_peer_reason as _default_peer_check
except Exception:  # pragma: no cover
    _url_allowed_reason = None  # type: ignore[assignment]
    _default_peer_check = None  # type: ignore[assignment]

# Sensitive contexts where form/mutation actions are refused unless the owner
# explicitly enables sensitive-mode for the session. Detected from the current
# page URL and visible text (lower-cased substring match). These cover
# authentication, payment, checkout, purchase and account-change pages.
_SENSITIVE_URL_MARKERS = (
    "/login", "/signin", "/auth", "/log-in", "/login/",
    "/checkout", "/pay", "/payment", "/cart/checkout",
    "/account", "/profile/settings", "/password", "/reset-password",
    "/register", "/signup",
)
_SENSITIVE_TEXT_MARKERS = (
    "sign in", "sign-in", "log in", "log-in", "login",
    "password", "enter your password", "payment", "checkout",
    "card number", "cvv", "expiration", "purchase", "place your order",
    "security code", "verify your identity",
)
# Substrings in a URL that mark it as an auth/payment/account page.

_TIMEOUT_DEFAULT_MS = 20000  # bounded, overridable, never unbounded
_MAX_BODY_CHARS = 30000


class _UnavailableError(RuntimeError):
    pass


class Driver:
    """Minimal driver contract the controller drives. Real impl: Playwright."""

    def goto(self, url: str, timeout_ms: int) -> str:      # returns final url
        raise NotImplementedError

    def page_text(self, max_chars: int = _MAX_BODY_CHARS) -> str:
        raise NotImplementedError

    def state(self) -> dict:
        raise NotImplementedError

    def screenshot(self, dest: str) -> bool:
        raise NotImplementedError

    def wait_for(self, selector: str, timeout_ms: int) -> bool:
        raise NotImplementedError

    def wait_for_text(self, text: str, timeout_ms: int) -> bool:
        raise NotImplementedError

    def scroll(self, direction: str, amount: int, timeout_ms: int) -> None:
        raise NotImplementedError

    def click(self, selector: str, timeout_ms: int) -> None:
        raise NotImplementedError

    def click_text(self, text: str, timeout_ms: int) -> None:
        raise NotImplementedError

    def type_text(self, selector: str, text: str, timeout_ms: int) -> None:
        raise NotImplementedError

    def select(self, selector: str, value: str, timeout_ms: int) -> None:
        raise NotImplementedError

    def submit(self, timeout_ms: int) -> None:
        raise NotImplementedError

    def save_last_download(self, folder: Path) -> str:
        raise NotImplementedError

    def upload(self, selector: str, local_path: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class _PlaywrightDriver(Driver):
    """Real driver: headless Chromium via Playwright, with SSRF routing.

    Playwright is imported lazily so importing :mod:`tools.browser_session`
    (and constructing the controller) never requires it to be installed; only
    an actual navigation does. Every outbound request is routed through
    ``security.urlguard`` and subresource requests to forbidden targets abort.
    """

    _WORKSPACE: str  # placeholder for type checkers

    def __init__(self, url_check: Callable[[str], str | None] | None = None,
                 peer_check: Callable[[str], str | None] | None = None) -> None:
        self._url_check = url_check or _url_allowed_reason
        # Connect-time DNS/peer enforcement complementing the static host-form
        # guard: re-resolves a top-level host right before the request proceeds
        # and refuses it if it does not land on a global/public address (closes
        # the DNS-rebinding window for navigation + redirects).
        self._peer_check = peer_check if peer_check is not None else _default_peer_check
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._last_download: Any = None

    def _sync_api(self) -> Any:
        if self._pw is not None:
            return self._pw
        if _url_allowed_reason is None:
            raise _UnavailableError("security.urlguard unavailable")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment
            raise _UnavailableError(
                "Browser automation unavailable: pip install playwright && "
                "playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        return self._pw

    def _ensure(self) -> Any:
        if self._page is not None:
            return self._page
        pw = self._sync_api()
        self._browser = pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(accept_downloads=True)
        self._page = self._context.new_page()
        page = self._page
        route_guard = self

        def _on_route(route: Any) -> None:
            url = route.request.url
            if route_guard._url_check and route_guard._url_check(url):
                try:
                    route.abort()
                except Exception:  # pragma: no cover
                    pass
                return
            # Connect-time DNS/peer enforcement (option 3a): for the top-level
            # document (navigation + its redirects) require the resolved peer to
            # be a global/public IP. Subresources keep the cheaper static guard;
            # re-resolving every subresource would add unbounded DNS latency, and
            # the rebinding risk concentrates on the main document that sets the
            # trust anchor for the page.
            is_main = getattr(route.request, "is_main_frame", False)
            if is_main and route_guard._peer_check:
                reason = route_guard._peer_check(url)
                if reason:
                    try:
                        route.abort()
                    except Exception:  # pragma: no cover
                        pass
                    return
            try:
                route.continue_()
            except Exception:  # pragma: no cover
                pass

        try:
            page.route("**/*", _on_route)
        except Exception:  # pragma: no cover
            pass

        def _on_download(download: Any) -> None:
            self._last_download = download

        try:
            page.on("download", _on_download)
        except Exception:  # pragma: no cover
            pass
        return page

    def goto(self, url: str, timeout_ms: int) -> str:
        page = self._ensure()
        reason = self._url_check(url) if self._url_check else None
        if reason:
            raise _UnavailableError("Navigation refused: " + reason)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return page.url

    def page_text(self, max_chars: int = _MAX_BODY_CHARS) -> str:
        page = self._ensure()
        return page.locator("body").inner_text()[:max_chars]

    def state(self) -> dict:
        page = self._ensure()
        return {"url": page.url, "title": page.title()}

    def screenshot(self, dest: str) -> bool:
        page = self._ensure()
        page.screenshot(path=dest, full_page=False)
        return Path(dest).exists()

    def wait_for(self, selector: str, timeout_ms: int) -> bool:
        page = self._ensure()
        try:
            page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        except Exception:  # pragma: no cover
            return False

    def wait_for_text(self, text: str, timeout_ms: int) -> bool:
        page = self._ensure()
        try:
            page.wait_for_selector(f"text={text}", timeout=timeout_ms)
            return True
        except Exception:  # pragma: no cover
            return False

    def scroll(self, direction: str, amount: int, timeout_ms: int) -> None:
        page = self._ensure()
        dy = amount if direction == "down" else -amount
        page.mouse.wheel(0, dy)

    def click(self, selector: str, timeout_ms: int) -> None:
        page = self._ensure()
        page.click(selector, timeout=timeout_ms)

    def click_text(self, text: str, timeout_ms: int) -> None:
        page = self._ensure()
        page.click(f"text={text}", timeout=timeout_ms)

    def type_text(self, selector: str, text: str, timeout_ms: int) -> None:
        page = self._ensure()
        page.fill(selector, text, timeout=timeout_ms)

    def select(self, selector: str, value: str, timeout_ms: int) -> None:
        page = self._ensure()
        page.select_option(selector, value)

    def submit(self, timeout_ms: int) -> None:
        page = self._ensure()
        page.keyboard.press("Enter")

    def save_last_download(self, folder: Path) -> str:
        """Save the most recently captured download into *folder*; return path.

        The suggested filename from the server is reduced to a basename so a
        hostile Content-Disposition cannot traverse out of the destination.
        """
        dl = self._last_download
        if dl is None:
            raise ValueError("No download has been triggered.")
        try:
            suggested = dl.suggested_filename or "download.bin"
        except Exception:  # pragma: no cover
            suggested = "download.bin"
        safe_name = Path(suggested).name or "download.bin"
        dest = folder / safe_name
        dl.save_as(str(dest))
        self._last_download = None
        return str(dest)

    def upload(self, selector: str, local_path: str) -> None:
        page = self._ensure()
        page.set_input_files(selector, local_path)

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:  # pragma: no cover
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # pragma: no cover
            pass
        self._page = self._browser = self._context = self._pw = None


def _is_secretish(text: str) -> bool:
    """Best-effort secret detection for typed text (mirrors computer control)."""
    low = (text or "").lower().strip()
    markers = ("password", "passwd", "secret", "token=", "api_key", "apikey",
               "credential", "authorization:", "bearer ", "ssn", "cvv",
               "card number", "cardnumber")
    return bool(low) and any(m in low for m in markers)


def _looks_sensitive_url(url: str) -> bool:
    low = (url or "").lower()
    return any(m in low for m in _SENSITIVE_URL_MARKERS)


class BrowserSession:
    """Persistent opt-in browser automation bound to a Driver.

    ``enabled`` mirrors the AIBA_BROWSER_ENABLED feature flag (the driver is
    inert/refusing when False). ``sensitive_actions`` (default False) opts the
    session into form actions on authentication/payment/account pages — off by
    default, matching the "explicit approval for auth/payment/purchase" rule.
    ``secret_typing`` (default False) allows typing secret-like values into
    fields once the operator consents; without it such typing is refused.

    Methods raise :class:`BrowserDenied` (a ValueError) for policy denials so
    the registry returns a ToolResult(False, error=...).
    """

    def __init__(self, driver: Driver | None = None, *, enabled: bool = True,
                 workspace: str | Path | None = None,
                 sensitive_actions: bool = False, secret_typing: bool = False,
                 audit: Any = None) -> None:
        self.driver = driver if driver is not None else _make_default_driver()
        self.enabled = bool(enabled)
        self.sensitive_actions = bool(sensitive_actions)
        self.secret_typing = bool(secret_typing)
        self.workspace = Path(workspace).resolve() if workspace else None
        self.audit = audit
        self._closed = False

    # ---- internal helpers ---------------------------------------------------
    def _ensure_ready(self) -> None:
        if not self.enabled:
            raise ValueError(
                "Browser automation is disabled (AIBA_BROWSER_ENABLED=false)."
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("Browser session is closed.")

    def _audit(self, event: str, **data: Any) -> None:
        if self.audit is not None:
            try:
                self.audit.record("browser_" + event, **data)
            except Exception:
                pass

    def _resolve_workspace_file(self, candidate: str, *, must_exist: bool) -> Path:
        """Resolve *candidate* to a path inside the approved workspace and return it.

        Raises ValueError if there is no approved workspace or the resolved path
        escapes it (downloads/reads/uploads are confined to the workspace).
        """
        if not candidate or not str(candidate).strip():
            return Path("")
        p = Path(candidate)
        if self.workspace is None:
            raise ValueError("No approved browser workspace is configured.")
        resolved = p if p.is_absolute() else (self.workspace / p)
        try:
            resolved = resolved.resolve()
            relative = resolved.relative_to(self.workspace)
        except ValueError:
            raise ValueError(
                "Browser file path must stay inside the approved AIBA workspace."
            )
        if must_exist and not resolved.exists():
            raise ValueError(f"File does not exist in workspace: {candidate}")
        return resolved

    # ---- enabled/context ----------------------------------------------------
    def node_status(self) -> ToolResult:
        # SAFE to call when disabled: this is a reporting action, not a guarded
        # capability action. It must report the disabled state (enabled: False)
        # rather than refuse to answer about whether the session is available.
        self._ensure_open()
        return ToolResult(True, {
            "enabled": self.enabled,
            "session_open": not self._closed,
            "driver": type(self.driver).__name__,
            "sensitive_actions": self.sensitive_actions,
            "secret_typing": self.secret_typing,
        })

    def configure(self, *, sensitive_actions: bool | None = None,
                  secret_typing: bool | None = None) -> ToolResult:
        self._ensure_ready()
        if sensitive_actions is not None:
            self.sensitive_actions = bool(sensitive_actions)
        if secret_typing is not None:
            self.secret_typing = bool(secret_typing)
        return ToolResult(True, {"sensitive_actions": self.sensitive_actions,
                                 "secret_typing": self.secret_typing})

    def close_session(self) -> ToolResult:
        if not self._closed:
            try:
                self.driver.close()
            except Exception:
                pass
            self._closed = True
        return ToolResult(True, {"closed": True})

    # ---- read-only browsing -------------------------------------------------
    def open(self, url: str, timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        url = (url or "").strip()
        if not url:
            return ToolResult(False, error="url must not be empty")
        reason = _url_allowed_reason(url) if _url_allowed_reason else None
        if reason:
            self._audit("nav_denied", url=url, reason=reason)
            return ToolResult(False, error="Navigation refused: " + reason)
        try:
            final = self.driver.goto(url, timeout_ms=int(timeout_ms))
            self._audit("nav", url=final)
            return ToolResult(True, {"url": final})
        except Exception as exc:
            self._audit("nav_failed", url=url, error=str(exc))
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def state(self) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        try:
            st = self.driver.state()
            return ToolResult(True, st)
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def page_text(self) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        try:
            txt = self.driver.page_text(_MAX_BODY_CHARS)
            return ToolResult(True, {"text_chars": len(txt), "text": txt})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def screenshot(self, workspace_path: str) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        try:
            dest = self._resolve_workspace_file(workspace_path, must_exist=False)
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            ok = self.driver.screenshot(str(dest))
            self._audit("screenshot", path=str(dest))
            return ToolResult(True, {"path": str(dest), "captured": bool(ok)})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def wait_for(self, selector: str, timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        if not selector:
            return ToolResult(False, error="selector must not be empty")
        try:
            found = self.driver.wait_for(selector, timeout_ms=int(timeout_ms))
            return ToolResult(True, {"found": bool(found)})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    # ---- mutation actions (require approval; gated off sensitive pages) -----
    # Every mutation is prefixed by _gate_mutation which prevents actions on
    # sensitive pages unless self.sensitive_actions, and typed secrets unless
    # self.secret_typing. These come AFTER the registry's requires_approval so
    # approval prompts (user consent) happen first for every mutation below.
    def _gate_sensitive(self, action: str) -> None:
        """Refuse *action* when the current page looks like an auth/payment page.

        Sensitive pages are recognised from the current URL AND the page title
        (both cheap to read via ``state()``). If either matches a known
        sensitive marker, mutation/form actions are refused unless the owner
        enabled :attr:`sensitive_actions`.
        """
        if self.sensitive_actions:
            return
        try:
            state = self.driver.state()
            url = state.get("url", "") if isinstance(state, dict) else ""
            title = state.get("title", "") if isinstance(state, dict) else ""
        except Exception:  # pragma: no cover
            url, title = "", ""
        haystack = f"{url}\n{title}".lower()
        if _looks_sensitive_url(haystack):
            raise ValueError(
                f"Refusing {action} on a sensitive page (authentication/payment/"
                "checkout/account) unless the owner enables sensitive actions."
            )
        if any(m in haystack for m in _SENSITIVE_TEXT_MARKERS):
            raise ValueError(
                f"Refusing {action}: the current page presents authentication/"
                "payment content; enable sensitive actions to proceed."
            )

    def scroll(self, direction: str = "down", amount: int = 400,
               timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        if direction not in ("up", "down"):
            return ToolResult(False, error="direction must be 'up' or 'down'")
        try:
            self._gate_sensitive("scroll")
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            self.driver.scroll(direction, int(amount), timeout_ms=int(timeout_ms))
            self._audit("scroll", direction=direction, amount=int(amount))
            return ToolResult(True, {"direction": direction, "amount": int(amount)})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def click(self, selector: str = "", text: str = "",
              timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        if not selector and not text:
            return ToolResult(False, error="provide selector or text to click")
        try:
            self._gate_sensitive("click")
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            if selector:
                self.driver.click(selector, timeout_ms=int(timeout_ms))
            else:
                self.driver.click_text(text, timeout_ms=int(timeout_ms))
            self._audit("click", selector=selector or text)
            return ToolResult(True, {"clicked": selector or text})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def type_text(self, selector: str, text: str,
                  timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        if not selector:
            return ToolResult(False, error="selector must not be empty")
        secretish = _is_secretish(text)
        if secretish and not self.secret_typing:
            return ToolResult(
                False,
                error="Typing secret-like text (password/token/card) is disabled. "
                      "Enable secret typing only with explicit owner consent, or "
                      "avoid typing secrets into pages.",
            )
        try:
            self._gate_sensitive("typing")
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        if secretish and _looks_sensitive_url(self._current_url() or ""):
            return ToolResult(False, error="Refusing to type secret-bearing text on "
                                           "an authentication/payment page.")
        try:
            self.driver.type_text(selector, text, timeout_ms=int(timeout_ms))
            # Content is NEVER logged; only length + whether it looked secret.
            self._audit("type", selector=selector, chars=len(text),
                        redacted=secretish)
            return ToolResult(True, {"typed_chars": len(text),
                                     "secret_filtered_log": bool(secretish)})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def _current_url(self) -> str | None:
        try:
            st = self.driver.state()
            return st.get("url") if isinstance(st, dict) else None
        except Exception:
            return None

    def select_option(self, selector: str, value: str,
                      timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        if not selector:
            return ToolResult(False, error="selector must not be empty")
        try:
            self._gate_sensitive("selection")
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            self.driver.select(selector, value, timeout_ms=int(timeout_ms))
            self._audit("select", selector=selector, value=value)
            return ToolResult(True, {"selected": value})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def submit(self, timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        try:
            self._gate_sensitive("form submission")
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            self.driver.submit(timeout_ms=int(timeout_ms))
            self._audit("submit")
            return ToolResult(True, {"submitted": True})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def download(self, workspace_path: str = "downloads") -> ToolResult:
        """Trigger and save a download into the approved workspace folder.

        The caller is expected to have just caused the download (e.g. via
        browser_click). This routes the resulting download to *workspace_path*
        (contained, otherwise refused) and returns the absolute saved path.
        """
        self._ensure_ready(); self._ensure_open()
        try:
            dest_dir = self._resolve_workspace_file(workspace_path, must_exist=False)
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            saved = self._save_pending_download(dest_dir)
            if not saved:
                return ToolResult(False, error="No download was captured this step.")
            self._audit("download", path=str(saved))
            return ToolResult(True, {"saved_to": str(saved)})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

    def _save_pending_download(self, folder: Path) -> str | None:
        """Save the browser's most recently triggered download into *folder*.

        Delegates to the driver (real Playwright or injected fake). The folder
        is already containment-checked by the caller.
        """
        save = getattr(self.driver, "save_last_download", None)
        if save is None:
            return None
        try:
            return save(folder)
        except Exception:
            return None

    def upload(self, selector: str, workspace_path: str,
               timeout_ms: int = _TIMEOUT_DEFAULT_MS) -> ToolResult:
        self._ensure_ready(); self._ensure_open()
        if not selector:
            return ToolResult(False, error="selector must not be empty")
        try:
            src = self._resolve_workspace_file(workspace_path, must_exist=True)
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            self._gate_sensitive("upload")
        except ValueError as exc:
            return ToolResult(False, error=str(exc))
        try:
            self.driver.upload(selector, str(src))
            self._audit("upload", selector=selector, source=str(src))
            return ToolResult(True, {"uploaded": str(src)})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")


def _make_default_driver() -> Driver:
    return _PlaywrightDriver()


# Inner Tool wrappers expose the controller methods to a ToolRegistry. Read-only
# tools carry risk_class read_only_network / requires_approval false in the
# manifest; mutation tools carry external_mutation / requires_approval true, and
# the registry asks the operator for approval before they run.
def build_browser_tools(session: BrowserSession) -> list:
    from tools.base import Tool
    s = session
    return [
        Tool("browser_open",
             "Navigate the managed browser to a PUBLIC http(s) URL (SSRF-safe) and return the final URL.",
             s.open,
             {"type": "object", "properties": {"url": {"type": "string"},
                                               "timeout_ms": {"type": "integer"}},
              "required": ["url"], "additionalProperties": False}),
        Tool("browser_state",
             "Read the current browser page's structured state (URL + title).",
             s.state,
             {"type": "object", "properties": {}, "additionalProperties": False}),
        Tool("browser_page_text",
             "Read visible text from the current page (truncated for the model; returns a safe excerpt).",
             s.page_text,
             {"type": "object", "properties": {}, "additionalProperties": False}),
        Tool("browser_screenshot",
             "Capture the current browser viewport to a PNG inside the approved workspace.",
             s.screenshot,
             {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"], "additionalProperties": False}),
        Tool("browser_wait",
             "Wait up to a bounded timeout for an element selector to appear.",
             s.wait_for,
             {"type": "object", "properties": {"selector": {"type": "string"},
                                               "timeout_ms": {"type": "integer"}},
              "required": ["selector"], "additionalProperties": False}),
        Tool("browser_status",
             "Report whether the automated browser session is enabled and open.",
             s.node_status,
             {"type": "object", "properties": {}, "additionalProperties": False}),
        # ---- mutations (approval required via permissions.json) ----
        Tool("browser_scroll",
             "Scroll the current page by an offset. Approval required.",
             s.scroll,
             {"type": "object", "properties": {"direction": {"type": "string"},
                                               "amount": {"type": "integer"}},
              "additionalProperties": False}),
        Tool("browser_click",
             "Click an element by CSS selector or by visible text. Alters the site; approval required.",
             s.click,
             {"type": "object", "properties": {"selector": {"type": "string"},
                                               "text": {"type": "string"},
                                               "timeout_ms": {"type": "integer"}},
              "additionalProperties": False}),
        Tool("browser_type",
             "Type text into a field via CSS selector. Secret-like text is never logged and is refused on auth/payment pages.",
             s.type_text,
             {"type": "object", "properties": {"selector": {"type": "string"},
                                               "text": {"type": "string"},
                                               "timeout_ms": {"type": "integer"}},
              "required": ["selector", "text"], "additionalProperties": False}),
        Tool("browser_select",
             "Select an option in a <select> element by value. Approval required.",
             s.select_option,
             {"type": "object", "properties": {"selector": {"type": "string"},
                                               "value": {"type": "string"},
                                               "timeout_ms": {"type": "integer"}},
              "required": ["selector", "value"], "additionalProperties": False}),
        Tool("browser_submit",
             "Submit the current form (press Enter). Approval required.",
             s.submit,
             {"type": "object", "properties": {"timeout_ms": {"type": "integer"}},
              "additionalProperties": False}),
        Tool("browser_download",
             "Save the download most recently triggered into the approved workspace (default downloads/). Approval required.",
             s.download,
             {"type": "object", "properties": {"path": {"type": "string"}},
              "additionalProperties": False}),
        Tool("browser_upload",
             "Upload a file ALREADY inside the approved workspace to a file input. Approval required.",
             s.upload,
             {"type": "object", "properties": {"selector": {"type": "string"},
                                               "path": {"type": "string"}},
              "required": ["selector", "path"], "additionalProperties": False}),
    ]
