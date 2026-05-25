import { executePackshotV1 } from "./executor/run-packshot.js";
import { auditCurrentJob } from "./auditor/run-audit.js";
import { jobLog } from "./logging/correlation.js";

async function main(): Promise<void> {
  const cmd = process.argv[2] ?? "help";
  const objectName = process.argv[3] ?? process.env.BLENDER_ASSIST_OBJECT_NAME;

  switch (cmd) {
    case "execute": {
      if (!objectName) {
        console.error("Usage: npm run agent -- execute <ObjectName>");
        process.exit(1);
      }
      await executePackshotV1({
        objectName,
        hdriPath: process.env.BLENDER_ASSIST_HDRI_PATH,
      });
      break;
    }
    case "audit": {
      await auditCurrentJob();
      break;
    }
    case "help":
    default:
      console.log(`
Blender Assist Agent CLI

  npm run agent -- execute <ObjectName>   Local packshot pipeline (verify → render → audit → await human)
  npm run agent:resume                    Resume STL after approval
  npm run agent:sync-google               Process paced Google Drive/Sheets queue
  npm run agent:orchestrate [prompt]      Cloud orchestrator (Cursor Agents Window)
  npm run agent:audit                     Re-run deterministic/OpenRouter auditor

Requires: Blender MCP bridge running, optional .env in agent/
`);
  }
}

main().catch((err) => {
  jobLog(`Fatal: ${err instanceof Error ? err.message : err}`);
  process.exit(1);
});
