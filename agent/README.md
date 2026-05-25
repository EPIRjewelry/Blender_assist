# Blender Assist Agent (TypeScript)

Orchestrates jewelry packshot workflows: local Blender MCP bridge, algorithmic verify, auditor gate, human approval (Google / gateway), STL resume.

## Prerequisites

- Python MCP: `pip install -e ".[dev]"` from repo root
- Blender 5.1+ with **Blender MCP Bridge** started (`127.0.0.1:8765`)
- Node 20+ in `agent/`

## Setup

```bash
cd agent
cp .env.example .env
# Edit .env — at minimum BLENDER_ASSIST_ROOT, object output path optional
npm install
```

## Commands

| Script | Description |
|--------|-------------|
| `npm run agent -- execute <ObjectName>` | Verify → render packshot → audit → save state → exit (await human) |
| `npm run agent:resume` | After auditor PASS + human approval → `export_stl` |
| `npm run agent:sync-google` | Process paced Drive/Sheets queue (no tight polling) |
| `npm run agent:audit` | Re-run auditor on current state |
| `npm run agent:orchestrate` | Cloud Cursor agent (Agents Window, needs `CURSOR_API_KEY`) |

## Human approval

1. PNG: `agent/output/packshot_v1_{jobId}.png`
2. Optional: approve via Cloudflare gateway (`TRIGGER_GATEWAY_URL` + `TRIGGER_HMAC_SECRET`)
3. Optional: Google Sheets row (via paced `agent:sync-google`) — Apps Script can call gateway
4. `npm run agent:resume`

## Cloudflare gateway

```bash
cd cloudflare
npm install
npx wrangler secret put TRIGGER_HMAC_SECRET
npx wrangler deploy
```

Set `TRIGGER_GATEWAY_URL` in `agent/.env` to the worker URL.

## Multi-agent (Cursor)

- `.cursor/agents/orchestrator.md` — cloud runs (`npm run agent:orchestrate`)
- `.cursor/agents/auditor.md` — PASS/FAIL on metrics
- `.cursor/agents/executor.md` — local MCP guidance

Blender steps always run **locally**; cloud agents coordinate and notify only.
