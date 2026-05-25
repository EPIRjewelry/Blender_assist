import { bridge } from "../config.js";
import { loadState, saveState } from "../approval/state-store.js";
import { readStatusByJobId } from "../approval/google-sheets.js";
import { jobLog, setJobId } from "../logging/correlation.js";
import { sendBridgeRequest } from "../mcp/bridge-client.js";
import { checkGatewayApproval } from "../approval/trigger-gateway.js";

export async function resumeJob(): Promise<void> {
  const state = await loadState();
  if (!state) {
    console.error("No .blender_assist_state.json — run agent:execute first.");
    process.exit(1);
  }
  setJobId(state.jobId);

  if (state.auditorVerdict !== "PASS") {
    console.error(`Auditor verdict is ${state.auditorVerdict ?? "missing"} — need PASS.`);
    process.exit(2);
  }

  let humanApproval = state.humanApproval === true;
  let source = state.humanApprovalSource;

  if (!humanApproval) {
    const gw = await checkGatewayApproval(state.jobId, state.triggerToken);
    if (gw.approved) {
      humanApproval = true;
      source = "webhook";
    }
  }

  if (!humanApproval) {
    const sheetStatus = await readStatusByJobId(state.jobId);
    if (sheetStatus === "APPROVED") {
      humanApproval = true;
      source = "sheets";
    } else if (sheetStatus === "REJECTED") {
      await saveState({
        ...state,
        phase: "rejected",
        humanApproval: false,
        updatedAt: new Date().toISOString(),
      });
      console.error("Human REJECTED in Sheets.");
      process.exit(3);
    }
  }

  if (!humanApproval) {
    console.error("Human approval missing — use gateway link or set APPROVED in Sheets.");
    process.exit(1);
  }

  const exporting = {
    ...state,
    phase: "export_stl" as const,
    humanApproval: true,
    humanApprovalSource: source ?? "cli",
    updatedAt: new Date().toISOString(),
  };
  await saveState(exporting);

  const stlPath =
    state.localStlPath ??
    state.localPngPath.replace(/\.png$/i, ".stl");

  const res = await sendBridgeRequest(
    "export_stl",
    {
      ...(state.blueprintPayload as Record<string, unknown>),
      output_path: stlPath,
    },
    {
      host: bridge.host,
      port: bridge.port,
      timeoutS: bridge.timeoutShort,
    },
  );

  if (!res.ok) {
    console.error(res.error?.message ?? "export_stl failed");
    process.exit(4);
  }

  await saveState({
    ...exporting,
    phase: "done",
    localStlPath: stlPath,
    updatedAt: new Date().toISOString(),
  });
  jobLog(`STL export done: ${stlPath}`);
}

resumeJob().catch((err) => {
  console.error(err);
  process.exit(1);
});
