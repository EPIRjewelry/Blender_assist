"""Blender addon TCP bridge — health and tool invoke (no relay/tunnel)."""

from __future__ import annotations

from typing import Any

from mcp_server.bridge import BridgeConfig, BridgeConnectionError, BridgeTimeoutError, send_request
from relay.invoke import invoke_tool
from relay.tool_catalog import list_bridge_tools, resolve_bridge_tool_name, tool_catalog_dict

from desktop_agent.config import AgentConfig


def bridge_config(cfg: AgentConfig) -> BridgeConfig:
    return BridgeConfig(host=cfg.bridge_host, port=cfg.bridge_port, timeout_s=5.0)


def check_bridge(cfg: AgentConfig) -> dict[str, Any]:
    try:
        raw = send_request("ping", {}, config=bridge_config(cfg))
        if raw.get("ok") is True:
            result = raw.get("result") or {}
            return {
                "online": True,
                "blender_version": result.get("blender_version"),
                "addon_version": result.get("addon_version"),
            }
        err = raw.get("error") or {}
        return {
            "online": False,
            "detail": err.get("message") or "ping failed",
            "code": err.get("code"),
        }
    except BridgeConnectionError:
        return {
            "online": False,
            "detail": f"Brak połączenia z {cfg.bridge_host}:{cfg.bridge_port} — w Blenderze: Start MCP Bridge",
            "code": "BLENDER_OFFLINE",
        }
    except BridgeTimeoutError:
        return {
            "online": False,
            "detail": "Timeout ping do addonu",
            "code": "BLENDER_TIMEOUT",
        }


def list_tools() -> dict[str, Any]:
    return tool_catalog_dict()


def tool_names() -> list[str]:
    return list_bridge_tools()


def execute_tool(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = resolve_bridge_tool_name(tool_name)
    return invoke_tool(resolved, dict(args or {}))
