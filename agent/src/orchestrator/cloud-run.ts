import { cursorSdk } from "../config.js";
import { buildMcpServers, localAgentOptions } from "../mcp-config.js";
import { loadState } from "../approval/state-store.js";
import { jobLog } from "../logging/correlation.js";

async function runCloudOrchestrator(prompt: string): Promise<void> {
  if (!cursorSdk.apiKey) {
    console.error("CURSOR_API_KEY required for cloud orchestrator.");
    process.exit(1);
  }

  const { Agent } = await import("@cursor/sdk");

  await using agent = await Agent.create({
    apiKey: cursorSdk.apiKey,
    model: { id: "composer-2.5" },
    cloud: {
      repos: [{ url: cursorSdk.repoUrl, startingRef: "main" }],
    },
    mcpServers: buildMcpServers() as Record<string, never>,
    agents: {
      auditor: {
        description: "CAD metrics auditor — PASS/FAIL JSON only",
        prompt:
          "Read auditor_input.json for the job. Output JSON {verdict,reasons,checks}. No vision on PNG.",
        model: "inherit",
      },
    },
  });

  jobLog(`Cloud orchestrator agentId=${agent.agentId}`);
  const run = await agent.send(prompt);

  for await (const event of run.stream()) {
    if (event.type === "assistant") {
      for (const block of event.message.content) {
        if (block.type === "text") process.stdout.write(block.text);
      }
    } else if (event.type === "tool_call") {
      jobLog(`[tool] ${event.name} ${event.status}`);
    } else if (event.type === "status") {
      jobLog(`[status] ${event.status}`);
    }
  }

  const result = await run.wait();
  jobLog(`Orchestrator finished status=${result.status}`);
}

async function main(): Promise<void> {
  const state = await loadState();
  const jobId = state?.jobId ?? process.argv[3];
  const prompt =
    process.argv[2] ??
    (jobId
      ? `Orchestrate Blender Assist job ${jobId}: spawn auditor on agent/.state/${jobId}/auditor_input.json, summarize for human, do not export STL.`
      : "List pending Blender Assist jobs in agent/.state and report status.");

  await runCloudOrchestrator(prompt);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
