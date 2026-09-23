import json
from pathlib import Path


def test_high_risk_parity_surfaces_default_off():
    root=Path(__file__).resolve().parents[1]
    permissions=json.loads((root/"config"/"permissions.json").read_text(encoding="utf-8"))
    tools=permissions["tools"]
    for name in (
        "delegate_task",
        "mcp_call",
        "browser_open",
        "desktop_screenshot",
        "host_list_files",
        "host_read_file",
        "host_search_files",
    ):
        assert name in tools, f"{name} must have an explicit policy row"
        assert tools[name]["enabled"] is False, f"{name} must default off"
