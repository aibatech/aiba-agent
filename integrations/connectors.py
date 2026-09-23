from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConnectorRegistry:
    """Operator-configured connector catalog.

    Credentials never live here. Each connector points at an MCP server/tool or
    another trusted adapter configured outside the model prompt. This gives AIBA
    one stable connector surface while Gmail/Calendar/Drive/Slack/Stripe adapters
    can be added independently.
    """

    def __init__(self, path: Path, mcp=None):
        self.path = Path(path)
        self.mcp = mcp

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "connectors": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 1, "connectors": {}}

    def list(self) -> list[dict[str, Any]]:
        rows = []
        for name, cfg in self._load().get("connectors", {}).items():
            if not isinstance(cfg, dict):
                continue
            rows.append({
                "name": name,
                "enabled": bool(cfg.get("enabled", False)),
                "kind": cfg.get("kind", "mcp"),
                "server": cfg.get("server"),
                "tools": sorted((cfg.get("tools") or {}).keys()),
            })
        return rows

    def call(self, connector: str, action: str, arguments: dict | None = None):
        cfg = self._load().get("connectors", {}).get(connector)
        if not isinstance(cfg, dict) or not cfg.get("enabled"):
            raise ValueError(f"Connector is not enabled: {connector}")
        if cfg.get("kind", "mcp") != "mcp":
            raise ValueError("Only MCP-backed connectors are supported by this adapter")
        tool = (cfg.get("tools") or {}).get(action)
        if not tool:
            raise ValueError(f"Action is not allowlisted for connector: {action}")
        if self.mcp is None:
            raise ValueError("MCP is not available")
        # Delegate through the existing MCP controller so server allowlists,
        # SSRF policy and remote-tool approvals remain authoritative.
        return self.mcp.call(server=str(cfg.get("server") or ""), tool=str(tool),
                             arguments=arguments or {})
