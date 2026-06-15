"""SSOT: registered MCP tools available on HTTP bridge (denylist policy)."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from relay.allowlist import BLENDER_BRIDGE_DENYLIST, is_tool_denied

# Common model hallucinations → real MCP tool names.
TOOL_NAME_ALIASES: dict[str, str] = {
    "blender_add_curve": "curve_cutter_create",
    "add_curve": "curve_cutter_create",
    "create_curve": "curve_cutter_create",
    "add_curve_cutter": "curve_cutter_create",
}


async def _list_registered_tool_names_async() -> list[str]:
    from mcp_server.server import mcp

    tools = await mcp.list_tools()
    return sorted(t.name for t in tools)


def list_registered_mcp_tool_names() -> list[str]:
    return asyncio.run(_list_registered_tool_names_async())


@lru_cache(maxsize=1)
def _registered_name_set() -> frozenset[str]:
    return frozenset(list_registered_mcp_tool_names())


def resolve_bridge_tool_name(tool_name: str) -> str:
    raw = (tool_name or "").strip()
    return TOOL_NAME_ALIASES.get(raw, raw)


def is_bridge_tool_allowed(tool_name: str) -> bool:
    resolved = resolve_bridge_tool_name(tool_name)
    if is_tool_denied(resolved):
        return False
    return resolved in _registered_name_set()


def list_bridge_tools() -> list[str]:
    return sorted(name for name in _registered_name_set() if not is_tool_denied(name))


def tool_catalog_dict() -> dict[str, Any]:
    from mcp_server import server as mcp_server

    tools: list[dict[str, str]] = []
    for name in list_bridge_tools():
        fn = getattr(mcp_server, name, None)
        summary = ""
        if callable(fn) and fn.__doc__:
            summary = fn.__doc__.strip().split("\n")[0].strip()
        tools.append({"name": name, "summary": summary})

    return {
        "version": 2,
        "policy": "denylist",
        "denied": sorted(BLENDER_BRIDGE_DENYLIST),
        "aliases": dict(sorted(TOOL_NAME_ALIASES.items())),
        "tools": tools,
    }
