import { cursorSdk } from "../config.js";
import { buildMcpServers, localAgentOptions } from "../mcp-config.js";
import { jobLog } from "../logging/correlation.js";

async function runLocalCursorAgent(prompt: string): Promise<void> {
  if (!cursorSdk.apiKey) {
    console.error("CURSOR_API_KEY required for local Cursor agent run.");
    process.exit(1);
  }

  const { Agent } = await import("@cursor/sdk");

  await using agent = await Agent.create({
    apiKey: cursorSdk.apiKey,
    model: { id: "composer-2.5" },
    local: localAgentOptions(),
    mcpServers: buildMcpServers() as Record<string, never>,
  });

  jobLog(`Local executor agentId=${agent.agentId}`);
  const run = await agent.send(prompt);

  for await (const event of run.stream()) {
    if (event.type === "assistant") {
      for (const block of event.message.content) {
        if (block.type === "text") process.stdout.write(block.text);
      }
    } else if (event.type === "tool_call") {
      jobLog(`[tool] ${event.name} ${event.status}`);
    }
  }

  await run.wait();
}

const prompt =
  process.argv[2] ??
  "Run packshot_v1 via MCP for the active Shop product; use algorithmic verify before render_packshot.";

runLocalCursorAgent(prompt).catch((err) => {
  console.error(err);
  process.exit(1);
});
