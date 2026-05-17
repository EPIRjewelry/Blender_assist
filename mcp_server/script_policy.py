"""
Optional gates for dangerous operations (step 7).

Remote script execution requires env var on the MCP host process.
"""

from __future__ import annotations

import os

_ENV_FLAG = "BLENDER_MCP_ALLOW_SCRIPT_EXEC"


def is_mcp_script_exec_enabled() -> bool:
    val = os.environ.get(_ENV_FLAG, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def exec_disabled_message() -> str:
    return (
        f"Script execution is disabled. Set {_ENV_FLAG}=1 in the environment that runs "
        "`python -m mcp_server`, then restart the MCP server."
    )
