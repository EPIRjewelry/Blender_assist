"""
Entry point for `python main.py` (same as `python -m mcp_server`).

Runs the FastMCP stdio server for Blender bridge tools.
"""

from mcp_server.server import main

if __name__ == "__main__":
    main()
