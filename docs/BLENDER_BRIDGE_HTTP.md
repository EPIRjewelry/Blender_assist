# HTTP relay for Operator Studio ↔ Blender (SSOT)

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Relay alive; `auth_configured` bool |
| `POST` | `/v1/tools/{tool_name}` | `Authorization: Bearer <EPIR_OPERATOR_PANEL_SECRET>` | Invoke allowlisted MCP tool |

Request body: JSON object — tool arguments (same as FastMCP), e.g. `{"object_name":"Ring","timeout_s":30}`.

Response: standard `ToolResponse` envelope (`ok`, `error`, `warnings`, `metrics`, `logs`, `timing_ms`).

## Allowlist v1

Must match `workers/chat/src/internal-blender-tools.ts`:

- `blender_ping`
- `scene_list_objects`
- `object_get_info`
- `object_convert_to_mesh`
- `mesh_get_bbox_mm`
- `mesh_check_manifold`
- `jewelry_mass_report`
- `export_stl`
- `render_packshot`
- `apply_material_preset`

Excluded from HTTP relay (Cursor MCP only): `node_tool_invoke`, `run_script`, `generate_parametric_solid`, …

## Chain

```
Operator Studio → workers/chat (blender_bridge_invoke)
  → https://blender-bridge.epirbizuteria.pl (named tunnel)
  → relay :9876 (this module)
  → addon TCP :8765
  → Blender main thread
```

## Run

1. Blender addon → **Start MCP Bridge** (`8765`).
2. `cp .env.example .env` — set `EPIR_OPERATOR_PANEL_SECRET` (same as Operator Studio).
3. `python -m relay` from repo root (after `pip install -e ".[dev]"`).
4. Named tunnel: `.\scripts\start-blender-bridge.ps1` (relay + cloudflared).

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `EPIR_OPERATOR_PANEL_SECRET` | — | Bearer token (required) |
| `RELAY_HTTP_HOST` | `127.0.0.1` | HTTP bind |
| `RELAY_HTTP_PORT` | `9876` | HTTP port |
| `BLENDER_BRIDGE_HOST` | `127.0.0.1` | Addon TCP host |
| `BLENDER_BRIDGE_PORT` | `8765` | Addon TCP port |

## Errors

| Code | Meaning |
|------|---------|
| `unauthorized` | Bearer mismatch / missing |
| `tool_not_allowed` | Outside allowlist v1 |
| `BLENDER_OFFLINE` | Addon not listening |
| `BRIDGE_TIMEOUT` | Blender main thread busy |
