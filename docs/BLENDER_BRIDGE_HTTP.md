# HTTP relay for Operator Studio ↔ Blender (SSOT)

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Relay alive |
| `POST` | `/v1/tools/{tool_name}` | none (default) | Invoke allowlisted MCP tool |

Request body: JSON object — tool arguments (same as FastMCP), e.g. `{"object_name":"Ring","timeout_s":30}`.

Response: standard `ToolResponse` envelope (`ok`, `error`, `warnings`, `metrics`, `logs`, `timing_ms`).

Optional: set `RELAY_AUTH=1` in `.env` to require `Authorization: Bearer <EPIR_OPERATOR_PANEL_SECRET>` on relay (off by default).

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

Worker origin: `BLENDER_BRIDGE_ORIGIN` in `workers/chat/wrangler.toml` (not a secret). Operator logs into Studio with `EPIR_OPERATOR_PANEL_SECRET` only — no PC `.env` secret.

## Run

**Setup raz:** `scripts/setup-blender-bridge-once.ps1` (venv + cloudflared config). Optional: `copy .env.example .env`.

**Codziennie (jeden klik):** Blender → sidebar **Blender MCP** → **Start MCP Bridge** — addon uruchamia TCP `:8765`, relay `:9876` i named tunnel (`bridge_orchestrator.py`). Operator Studio → zakładka **Blender** → status `online: true` w ~10 s.

**Fallback (diagnostyka):** `scripts/start-blender-bridge.ps1` — relay + tunel bez Blendera.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `RELAY_AUTH` | `0` | `1` = Bearer on relay (optional) |
| `RELAY_HTTP_HOST` | `127.0.0.1` | HTTP bind |
| `RELAY_HTTP_PORT` | `9876` | HTTP port |
| `BLENDER_BRIDGE_HOST` | `127.0.0.1` | Addon TCP host |
| `BLENDER_BRIDGE_PORT` | `8765` | Addon TCP port |
| `BLENDER_BRIDGE_HOSTNAME` | `blender-bridge.epirbizuteria.pl` | Public tunnel hostname |

## Errors

| Code | Meaning |
|------|---------|
| `unauthorized` | Bearer mismatch when `RELAY_AUTH=1` |
| `tool_not_allowed` | Outside allowlist v1 |
| `BLENDER_OFFLINE` | Addon not listening |
| `BRIDGE_TIMEOUT` | Blender main thread busy |
