import path from "node:path";
import { repoRoot } from "./config.js";

export function buildMcpServers(): Record<string, unknown> {
  const root = repoRoot();
  return {
    "blender-mcp": {
      type: "stdio",
      command: process.platform === "win32" ? "python" : "python3",
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
