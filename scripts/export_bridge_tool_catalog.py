#!/usr/bin/env python3
"""Export bridge tool catalog JSON — run after adding @mcp.tool in mcp_server/server.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relay.tool_catalog import tool_catalog_dict  # noqa: E402


def main() -> None:
    out = ROOT / "docs" / "BLENDER_BRIDGE_TOOLS.json"
    payload = tool_catalog_dict()
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload['tools'])} tools)")


if __name__ == "__main__":
    main()
