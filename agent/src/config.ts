import { config as loadEnv } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

loadEnv({ path: path.join(__dirname, "..", ".env") });
loadEnv({ path: path.join(__dirname, "..", "..", ".env") });

export function repoRoot(): string {
  return (
    process.env.BLENDER_ASSIST_ROOT?.trim() ||
    path.resolve(__dirname, "..", "..")
  );
}

export function agentStateDir(): string {
  return path.join(repoRoot(), "agent", ".state");
}

export function globalStatePath(): string {
  return path.join(repoRoot(), ".blender_assist_state.json");
}

export function outputDir(): string {
  return (
    process.env.BLENDER_ASSIST_OUTPUT_DIR?.trim() ||
    path.join(repoRoot(), "agent", "output")
  );
}

export const bridge = {
  host: process.env.BLENDER_MCP_HOST ?? "127.0.0.1",
  port: Number(process.env.BLENDER_MCP_PORT ?? "8765"),
  timeoutShort: 30,
  timeoutRender: 120,
};

export const google = {
  serviceAccountJson: process.env.GOOGLE_SERVICE_ACCOUNT_JSON?.trim(),
  driveFolderId: process.env.GOOGLE_DRIVE_FOLDER_ID?.trim(),
  sheetsSpreadsheetId: process.env.GOOGLE_SHEETS_SPREADSHEET_ID?.trim(),
  syncDelayMs: Number(process.env.GOOGLE_SYNC_DELAY_MS ?? "120000"),
  sheetsDelayMs: Number(process.env.GOOGLE_SHEETS_DELAY_MS ?? "900000"),
};

export const trigger = {
  gatewayUrl: process.env.TRIGGER_GATEWAY_URL?.trim(),
  hmacSecret: process.env.TRIGGER_HMAC_SECRET?.trim(),
};

export const openRouter = {
  apiKey: process.env.OPENROUTER_API_KEY?.trim(),
  model: process.env.OPENROUTER_MODEL ?? "anthropic/claude-sonnet-4",
};

export const cursorSdk = {
  apiKey: process.env.CURSOR_API_KEY?.trim(),
  repoUrl:
    process.env.BLENDER_ASSIST_REPO_URL?.trim() ||
    "https://github.com/EPIRjewelry/Blender_assist",
};
