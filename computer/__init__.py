"""Computer-node package re-exports + settings-driven factory.

``make_computer(settings, audit)`` builds a persistent
:class:`ComputerNodeGate` + :class:`ComputerController` pair configured from an
authoritative :class:`config.settings.Settings`. Everything stays disabled until
the owner pairs + enables a node via the CLI/admin surface — never silently.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

from .controller import ComputerController, _is_secretish, _redact_url
from .node import (
    ComputerNodeGate,
    NodeBudgetExhaustedError,
    NodeEmergencyStoppedError,
    NodeNotPairedError,
)

__all__ = [
    "ComputerController",
    "ComputerNodeGate",
    "make_computer",
    "NodeNotPairedError",
    "NodeBudgetExhaustedError",
    "NodeEmergencyStoppedError",
]


def _settings_node_store(settings: Any) -> Path:
    """Return the on-disk node store path for a Settings, or an inert temp path."""
    if settings is not None:
        val = getattr(settings, "computer_node_path", None)
        if val:
            return Path(val)
        data = getattr(settings, "data_dir", None)
        if data:
            return Path(data) / "computer_node.json"
    # No settings => callers must position an inert store; default to cwd but it
    # will never be paired so execution stays refused.
    return Path("computer_node.json")


def make_computer(settings: Any, audit: Any = None):
    """Return (gate, controller) built from an authoritative Settings.

    The node store + emergency flag live under the settings data dir. The master
    opt-in (``settings.desktop_enabled``) decides whether the *controller* is
    even allowed to act; but actual execution additionally requires a paired +
    enabled + approved node (defense in depth). With ``settings is None`` the
    controller is backed by an inert, never-paired gate — always refuses.
    """
    node_store = _settings_node_store(settings)
    master_on = bool(getattr(settings, "desktop_enabled", False)) if settings is not None else False
    gate = ComputerNodeGate(
        node_store,
        enabled=master_on,
        audit=audit,
        allow_clipboard=bool(getattr(settings, "desktop_clipboard_enabled", False)) if settings is not None else False,
        allow_process=bool(getattr(settings, "desktop_process_enabled", False)) if settings is not None else False,
    )
    controller = ComputerController(gate, audit=audit)
    return gate, controller
