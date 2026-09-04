"""AIBA optional MCP client (Phase 7).

A real but optional MCP **client** behind a single gated AIBA tool ``mcp_call``.
Exposure is one static, manifest-backed tool — no dynamic per-server AIBA tool
names — so every server/tool/approval decision stays operator-owned in
``config/mcp_servers.json`` and can never broaden AIBA's permission surface.
MCP is disabled by default on three independent axes (feature flag,
permissions.json, configured enabled server). The PyPI ``mcp`` SDK is imported
lazily inside :mod:`mcp_client.client` so a base install without the optional
``[mcp]`` extra is unaffected.
"""
