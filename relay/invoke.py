"""Dispatch MCP tool names to mcp_server.server functions (denylist-only for HTTP)."""

from __future__ import annotations

import inspect
import os
from typing import Any

from mcp_server import server as mcp_server

from relay.allowlist import is_tool_denied
from relay.tool_catalog import is_bridge_tool_allowed, resolve_bridge_tool_name


def default_bridge_host() -> str:
    return os.environ.get("BLENDER_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"


def default_bridge_port() -> int:
    raw = os.environ.get("BLENDER_BRIDGE_PORT", "8765").strip()
    try:
        return int(raw)
    except ValueError:
        return 8765


def invoke_tool(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = resolve_bridge_tool_name(tool_name)

    if is_tool_denied(resolved):
        return {
            "ok": False,
            "error": {"code": "tool_not_allowed", "message": f"Tool blocked for HTTP bridge: {resolved}"},
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 0,
        }

    if not is_bridge_tool_allowed(resolved):
        hint = ""
        if "curve" in tool_name.lower():
            hint = " Użyj curve_cutter_create dla krzywych/obrysów CAD."
        return {
            "ok": False,
            "error": {"code": "tool_not_found", "message": f"Unknown MCP tool: {tool_name}.{hint}"},
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 0,
        }

    fn = getattr(mcp_server, resolved, None)
    if fn is None or not callable(fn):
        return {
            "ok": False,
            "error": {"code": "tool_not_implemented", "message": f"No relay handler for {resolved}"},
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
