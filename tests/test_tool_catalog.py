"""Tool catalog SSOT tests."""

from __future__ import annotations

import json
from pathlib import Path

from relay.tool_catalog import list_bridge_tools, tool_catalog_dict


def test_bridge_tools_include_curve_cutter_create():
    names = list_bridge_tools()
    assert "curve_cutter_create" in names
    assert "run_script" in names
    assert "node_tool_invoke" in names
    assert len(names) == 32


def test_blender_add_curve_alias_resolves():
    from relay.invoke import invoke_tool
    from unittest.mock import patch

    with patch("relay.invoke.mcp_server.curve_cutter_create") as mocked:
        mocked.return_value = {
            "ok": True,
            "error": None,
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 1,
        }
        out = invoke_tool("blender_add_curve", {"object_name": "Band", "name": "cutter"})
        assert out["ok"] is True
        mocked.assert_called_once()


def test_catalog_json_matches_live_export():
    json_path = Path(__file__).resolve().parents[1] / "docs" / "BLENDER_BRIDGE_TOOLS.json"
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    live = tool_catalog_dict()
    assert on_disk["tools"] == live["tools"]
    assert on_disk["denied"] == live["denied"]
    assert on_disk["aliases"] == live["aliases"]
