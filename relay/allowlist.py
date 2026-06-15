"""Bridge tool policy — denylist for HTTP relay (matches workers/chat internal-blender-tools.ts)."""

from __future__ import annotations

# ESOG: HTTP bridge must not expose arbitrary script / bpy.ops automation.
BLENDER_BRIDGE_DENYLIST: frozenset[str] = frozenset(
    {
        "run_script",
        "node_tool_invoke",
    }
)


def is_tool_denied(tool_name: str) -> bool:
    return tool_name in BLENDER_BRIDGE_DENYLIST


# Legacy alias — older docs/tests referenced allowlist v1.
BLENDER_BRIDGE_ALLOWLIST_V1 = BLENDER_BRIDGE_DENYLIST
