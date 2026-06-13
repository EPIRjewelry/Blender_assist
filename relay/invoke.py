"""Dispatch allowlisted tool names to existing mcp_server.server functions."""

from __future__ import annotations

import inspect
import os
from typing import Any

from mcp_server import server as mcp_server

from relay.allowlist import BLENDER_BRIDGE_ALLOWLIST_V1

_TOOL_FN = {
    "blender_ping": mcp_server.blender_ping,
    "scene_list_objects": mcp_server.scene_list_objects,
    "object_get_info": mcp_server.object_get_info,
    "object_convert_to_mesh": mcp_server.object_convert_to_mesh,
    "mesh_get_bbox_mm": mcp_server.mesh_get_bbox_mm,
    "mesh_check_manifold": mcp_server.mesh_check_manifold,
    "jewelry_mass_report": mcp_server.jewelry_mass_report,
    "export_stl": mcp_server.export_stl,
    "render_packshot": mcp_server.render_packshot,
    "apply_material_preset": mcp_server.apply_material_preset,
}


def default_bridge_host() -> str:
    return os.environ.get("BLENDER_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"


def default_bridge_port() -> int:
    raw = os.environ.get("BLENDER_BRIDGE_PORT", "8765").strip()
    try:
        return int(raw)
    except ValueError:
        return 8765


def invoke_tool(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    if tool_name not in BLENDER_BRIDGE_ALLOWLIST_V1:
        return {
            "ok": False,
            "error": {"code": "tool_not_allowed", "message": f"Tool not in allowlist v1: {tool_name}"},
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 0,
        }

    fn = _TOOL_FN.get(tool_name)
    if fn is None:
        return {
            "ok": False,
            "error": {"code": "tool_not_implemented", "message": f"No relay handler for {tool_name}"},
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 0,
        }

    payload = dict(args or {})
    sig = inspect.signature(fn)
    if "host" in sig.parameters and "host" not in payload:
        payload["host"] = default_bridge_host()
    if "port" in sig.parameters and "port" not in payload:
        payload["port"] = default_bridge_port()

    allowed = set(sig.parameters)
    filtered = {k: v for k, v in payload.items() if k in allowed}

    try:
        out = fn(**filtered)
    except TypeError as exc:
        return {
            "ok": False,
            "error": {"code": "invalid_arguments", "message": str(exc)},
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 0,
        }

    if not isinstance(out, dict):
        return {
            "ok": False,
            "error": {"code": "invalid_tool_response", "message": "Tool did not return a dict"},
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 0,
        }

    out.pop("_bridge_result", None)
    out.pop("result", None)
    return out
