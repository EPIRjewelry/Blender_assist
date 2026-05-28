import fs from "node:fs";
import path from "node:path";
import { repoRoot } from "./config.js";

/** Prefer repo .venv Python on Windows (avoids PATH / env inheritance issues in Cursor). */
function resolveMcpPythonCommand(root: string): string {
  const candidates =
    process.platform === "win32"
      ? [path.join(root, ".venv", "Scripts", "python.exe")]
      : [
          path.join(root, ".venv", "bin", "python3"),
          path.join(root, ".venv", "bin", "python"),
        ];
  for (const exe of candidates) {
    if (fs.existsSync(exe)) return exe;
  }
  return process.platform === "win32" ? "python" : "python3";
}

export function buildMcpServers(): Record<string, unknown> {
  const root = repoRoot();
  return {
    "blender-mcp": {
      type: "stdio",
      command: resolveMcpPythonCommand(root),
      args: ["-m", "mcp_server"],
      cwd: root,
      env: {
        BLENDER_MCP_ALLOW_SCRIPT_EXEC: "0",
        BLENDER_ASSIST_JOB_ID: process.env.BLENDER_ASSIST_JOB_ID ?? "",
      },
    },
  };
}

export function localAgentOptions(cwd?: string) {
  return {
    cwd: cwd ?? repoRoot(),
    settingSources: ["project", "user"] as ("project" | "user")[],
  };
}
