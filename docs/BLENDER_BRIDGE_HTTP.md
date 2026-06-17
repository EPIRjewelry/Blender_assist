# HTTP relay for Operator Studio ↔ Blender (SSOT)

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Relay alive |
| `GET` | `/v1/tools` | none | **Tool catalog** (names, summaries, denylist, aliases) |
| `POST` | `/v1/tools/{tool_name}` | none (default) | Invoke MCP tool |

Request body: JSON object — tool arguments (same as FastMCP), e.g. `{"object_name":"Ring","timeout_s":30}`.

Response: standard `ToolResponse` envelope (`ok`, `error`, `warnings`, `metrics`, `logs`, `timing_ms`).

Optional: set `RELAY_AUTH=1` in `.env` to require `Authorization: Bearer <EPIR_OPERATOR_PANEL_SECRET>` on relay (off by default).

## Tool catalog (SSOT)

**Source of truth:** `relay/tool_catalog.py` (auto-discovers registered `@mcp.tool` names via FastMCP).

**Exported JSON:** `docs/BLENDER_BRIDGE_TOOLS.json` — run after adding a tool:

```bash
python scripts/export_bridge_tool_catalog.py
```

Copy the same JSON to `aplikacja_epir/workers/chat/src/blender-bridge-tools.json` (worker enum + CI).

**Policy:** denylist (empty for solo operator). **32 tools** pass through HTTP, including `run_script` and `node_tool_invoke`. Addon gates script exec (`BLENDER_MCP_ALLOW_SCRIPT_EXEC`, `confirm=True`, addon pref).

**Aliases** (model typos → real tool):

| Alias | Resolves to |
|-------|-------------|
| `blender_add_curve` | `curve_cutter_create` |
| `add_curve` | `curve_cutter_create` |
| `create_curve` | `curve_cutter_create` |
| `add_curve_cutter` | `curve_cutter_create` |

**Live catalog on running relay:**

```bash
curl -s http://127.0.0.1:9876/v1/tools | jq '.catalog.tools[].name'
```

Full table with summaries: see `docs/BLENDER_BRIDGE_TOOLS.json`.

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
| `tool_not_allowed` | Denylisted tool (denylist empty by default) |
| `tool_not_found` | Unknown MCP name (check `/v1/tools` or aliases) |
| `BLENDER_OFFLINE` | Addon not listening |
| `BRIDGE_TIMEOUT` | Blender main thread busy |
