# Blender addon (Blender 5.1 only)

Live bridge addon (**Blender 5.1.x only** target per `bl_info`) listens on `localhost` and runs MCP actions on Blender’s main thread (`queue.Queue` + `bpy.app.timers`).

Current scope includes:
- parametric CAD solid generation (`generate_parametric_solid`, current primitive: `ring_band`)
- generic Node Tools/operator invocation (`node_tool_invoke`) with explicit global idname validation
- procedural and preset Cycles shading (`build_procedural_jewelry_material`, `apply_material_preset`)
- still rendering (`render_still`)

Step 1: install the MCP Python package from the **repository root** (`pip install -e ".[dev]"`), then run `python -m mcp_server` or `python main.py` from that directory. See root [README.md](../README.md) (SSOT).

## Operator Studio (one click)

1. Once: `scripts/setup-blender-bridge-once.ps1` (optional `.env` from `.env.example`).
2. Each session: **Start MCP Bridge** in this addon — starts TCP `:8765`, relay `:9876`, and named Cloudflare tunnel via `bridge_orchestrator.py`.
3. Smoke: Operator Studio → Blender tab → `OK — most odpowiada`.

Fallback: `scripts/start-blender-bridge.ps1` (CLI only).
