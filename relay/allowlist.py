"""Bridge tool policy — denylist for HTTP relay (matches workers/chat blender-bridge-tools.json)."""

from __future__ import annotations

# Empty denylist: solo operator / design_blender role. run_script and node_tool_invoke
# are gated in the addon (BLENDER_MCP_ALLOW_SCRIPT_EXEC, confirm=True, addon pref).
BLENDER_BRIDGE_DENYLIST: frozenset[str] = frozenset()


def is_tool_denied(tool_name: str) -> bool:
    return tool_name in BLENDER_BRIDGE_DENYLIST


# Legacy alias — older docs/tests referenced allowlist v1.
BLENDER_BRIDGE_ALLOWLIST_V1 = BLENDER_BRIDGE_DENYLIST
