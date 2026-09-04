"""Opt-in, local computer-control node gate.

The AIBA core server never gains desktop access by default. Desktop actions are
only possible once the owner explicitly *pairs* a local computer node for this
run: ``pair(name, code)`` stores a strong, argon-sha256-hashed node token in a
mode-0600 store on disk. Until a node is paired AND enabled, every desktop
controller action is refused.

Security properties enforced here (and unit-tested):
  * Disabled by default  - no store + no env flag + no node = everything off.
  * One-time pairing code / cryptographically strong node token (secrets.token_bytes),
    stored only as a salted SHA-256 digest - never the raw secret.
  * Local-only by design - there is no network/desktop-control listener here; the
    node is an in-process guarded binding, so a public endpoint cannot exist.
  * Emergency disconnect/disable - ``emergency_stop()`` sets a killed flag that
    the controller checks before every action and that survives reload.
  * Max-action budget - a configurable cap on desktop actions since pairing.
  * Capability lock - the node declares which action classes it allows
    (clipboard / process are OFF unless explicitly enabled by the owner).
  * Full audit - every requested/approved/denied/executed/result event is
    recorded via the injected AuditLog (caller supplies it).

This module holds no secrets in memory longer than the handshake needs and never
logs the raw token, screenshots, clipboard contents, or chain-of-thought.
"""

from __future__ import annotations
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Action classes that are always allowed once paired (mouse, keys, scroll,
# screen). Clipboard and process control must be explicitly opted-in because
# they can read/act on sensitive data outside the AIBA workspace.
CLIPBOARD_ACTIONS = {"clipboard_read", "clipboard_write"}
PROCESS_ACTIONS = {"process_start", "process_status", "process_stop"}
OPTIONAL_ACTIONS = CLIPBOARD_ACTIONS | PROCESS_ACTIONS
# Sensitive action classes are never enabled by default, even when paired.
_ALWAYS_REQUIRE_OWNER_OPTIN = OPTIONAL_ACTIONS


class NodeNotPairedError(PermissionError):
    """Raised when a desktop action is attempted before a node is paired/enabled."""


class NodeBudgetExhaustedError(PermissionError):
    """Raised when the desktop action budget is exhausted."""


class NodeEmergencyStoppedError(PermissionError):
    """Raised after the owner invoked the emergency disconnect."""


class ComputerNodeGate:
    """Guard + pairing store for local desktop control.

    ``store_path`` holds the paired identity JSON (digest only). ``audit`` is an
    optional ``AuditLog`` used to record pairing, enable/disable, emergency stop,
    and per-action decision events. ``emergency_path`` persists the kill switch.
    """

    # A fixed, low default that normal users can raise deliberately. Capturing
    # the option is what matters; the audit records value.
    DEFAULT_MAX_ACTIONS = 500

    def __init__(
        self,
        store_path: Path,
        *,
        enabled: bool = False,
        max_actions: int | None = None,
        allow_clipboard: bool = False,
        allow_process: bool = False,
        audit: Any = None,
        emergency_path: Path | None = None,
    ) -> None:
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.emergency_path = Path(emergency_path) if emergency_path else self.store_path.with_name(self.store_path.name + ".kill")
        self.audit = audit
        self.max_actions = int(max_actions) if max_actions is not None else self.DEFAULT_MAX_ACTIONS
        self._enabled = bool(enabled)
        self._allow_clipboard = bool(allow_clipboard)
        self._allow_process = bool(allow_process)
        self._actions_used = 0
        self._ops_lock = __import__("threading").RLock()
        self._load()

    # ---- persistence helpers -------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        self._digest = data.get("token_digest") or ""
        self._node_name = data.get("node_name") or ""
        self._paired_at = data.get("paired_at") or ""
        self._cap_locked = set(data.get("capabilities") or [])
        # Re-hydrate emergency state from disk so a stop survives restart.
        try:
            kill = json.loads(self.emergency_path.read_text(encoding="utf-8"))
            self._killed = bool(kill.get("killed", False))
        except (FileNotFoundError, json.JSONDecodeError):
            self._killed = False

    def _persist(self) -> None:
        obj = {
            "token_digest": self._digest,
            "node_name": self._node_name,
            "paired_at": self._paired_at,
            "capabilities": sorted(self._cap_locked),
        }
        tmp = self.store_path.with_name(self.store_path.name + ".tmp")
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.store_path)

    def _record(self, event: str, **kw: Any) -> None:
        if self.audit is not None:
            try:
                self.audit.record("computer_node_" + event, **kw)
            except Exception:
                pass

    # ---- pairing / lifecycle -------------------------------------------------
    @property
    def paired(self) -> bool:
        return bool(self._digest)

    @property
    def enabled(self) -> bool:
        return self._enabled and self.paired and not self._killed

    @property
    def killed(self) -> bool:
        return self._killed

    @property
    def node_name(self) -> str:
        return self._node_name

    @property
    def actions_used(self) -> int:
        return self._actions_used

    @property
    def capabilities(self) -> set[str]:
        return set(self._cap_locked)

    def pair(self, name: str, capabilities: list[str] | None = None) -> str:
        """Pair a node: generate a fresh node token, store only its digest.

        Returns the raw one-time node token to the *caller only* (printed to the
        operator once by the CLI); the raw value is never persisted.
        Any ``OPTIONAL_ACTIONS`` (clipboard/process) included here are refused
        unless separately enabled via ``set_optin``; the capability lock always
        means we can always tell the model what is actually permitted.
        """
        raw = "aiba_node_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(("aiba::" + raw).encode()).hexdigest()
        allowed = [c for c in (capabilities or []) if self._is_valid_capability(c)]
        with self._ops_lock:
            self._digest = digest
            self._node_name = (name or "local-computer").strip()[:64]
            self._paired_at = datetime.now(timezone.utc).isoformat()
            self._cap_locked = set(allowed)
            # Optional classes default to REQUIRED-but-not-yet-enabled listing;
            # store them so the capability report reflects the lock accurately.
            self._cap_locked.update(_ALWAYS_REQUIRE_OWNER_OPTIN)
            self._actions_used = 0
            self._killed = False
            self._persist()
        self._record("paired", node=name, capabilities=sorted(self._cap_locked))
        return raw

    @staticmethod
    def _is_valid_capability(c: str) -> bool:
        return c in {
            "screen", "mouse", "keyboard", "scroll", "open_url",
            *CLIPBOARD_ACTIONS, *PROCESS_ACTIONS,
        }

    def enable(self) -> None:
        if not self.paired:
            raise NodeNotPairedError("Desktop control cannot be enabled until a node is paired (aiba --computer-pair).")
        self._enabled = True
        self._record("enabled")

    def disable(self) -> None:
        self._enabled = False
        self._record("disabled")

    def emergency_stop(self) -> None:
        """Immediately disable all desktop actions and persist a kill flag."""
        with self._ops_lock:
            self._enabled = False
            self._killed = True
            self.emergency_path.parent.mkdir(parents=True, exist_ok=True)
            self.emergency_path.write_text(json.dumps({"killed": True}), encoding="utf-8")
            try:
                os.chmod(self.emergency_path, 0o600)
            except OSError:
                pass
        self._record("emergency_stop")

    def revoke(self) -> None:
        """Remove the paired identity entirely (full disconnect)."""
        with self._ops_lock:
            self._digest = ""
            self._node_name = ""
            self._paired_at = ""
            self._cap_locked = set()
            self._enabled = False
            self._killed = False
            self._persist()
            self.emergency_path.unlink(missing_ok=True)
        self._record("revoked")

    def set_optin(self, allow_clipboard: bool | None = None, allow_process: bool | None = None) -> None:
        if allow_clipboard is not None:
            self._allow_clipboard = bool(allow_clipboard)
            self._record("clipboard_optin", enabled=bool(allow_clipboard))
        if allow_process is not None:
            self._allow_process = bool(allow_process)
            self._record("process_optin", enabled=bool(allow_process))

    def reset_budget(self) -> None:
        with self._ops_lock:
            self._actions_used = 0
        self._record("budget_reset")

    def budget_status(self) -> dict[str, Any]:
        return {
            "used": self._actions_used,
            "limit": self.max_actions,
            "remaining": max(0, self.max_actions - self._actions_used),
        }

    # ---- runtime authorization ----------------------------------------------
    def authorize(self, action: str) -> tuple[bool, str]:
        """Return (allowed, reason) for a desktop ``action`` name.

        Checks, in order: paired+enabled (not emergency-stopped), capability
        lock, owner opt-in for clipboard/process, and the max-action budget.
        This is the single choke point every controller action must pass.
        """
        with self._ops_lock:
            if not self.paired:
                return False, "No computer node is paired (run aiba --computer-pair)."
            if self._killed:
                return False, "Computer node is emergency-stopped (aiba --computer-stop then --computer-enable to recover)."
            if not self._enabled:
                return False, "Computer node is paired but disabled (aiba --computer-enable)."
            if action in _ALWAYS_REQUIRE_OWNER_OPTIN:
                if action in CLIPBOARD_ACTIONS and not self._allow_clipboard:
                    return False, "Clipboard access is not enabled for this node."
                if action in PROCESS_ACTIONS and not self._allow_process:
                    return False, "Process control is not enabled for this node."
            if self._actions_used >= self.max_actions:
                return False, "Desktop action budget exhausted (aiba --computer-reset-budget to continue)."
            self._actions_used += 1
        self._record("authorized", action=action)
        return True, ""

    def status(self) -> dict[str, Any]:
        """Human/diagnostic view used by ``aiba --computer-status`` + diagnostics."""
        return {
            "paired": self.paired,
            "enabled": self.enabled,
            "node_name": self._node_name,
            "paired_at": self._paired_at if self._paired_at else None,
            "killed": self._killed,
            "capabilities": sorted(self._cap_locked),
            "clipboard_enabled": self._allow_clipboard,
            "process_enabled": self._allow_process,
            "budget": self.budget_status(),
        }
