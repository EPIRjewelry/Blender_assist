import fs from "node:fs/promises";
import { createHmac } from "node:crypto";
import { bridge, google, outputDir, trigger } from "../config.js";
import { buildPackshotV1Plan, type PackshotV1Input } from "../blueprints/packshot-v1.js";
import { enqueueGoogleSync } from "../approval/google-sync-queue.js";
import { enterAwaitingHuman } from "../approval/wait-approval.js";
import { saveAuditorInput, saveState } from "../approval/state-store.js";
import type { BlenderAssistState } from "../approval/state-schema.js";
import { runLocalVerify } from "../loops/execute-verify.js";
import { newJobId, setJobId, jobLog, pngFileName } from "../logging/correlation.js";
import { sendBridgeRequest } from "../mcp/bridge-client.js";
import { auditCurrentJob } from "../auditor/run-audit.js";
import { sendApprovalNotifications } from "../notify/index.js";

function buildTriggerToken(jobId: string): string | undefined {
  if (!trigger.hmacSecret) return undefined;
  return createHmac("sha256", trigger.hmacSecret).update(jobId).digest("hex");
}

export async function executePackshotV1(
  input: Omit<PackshotV1Input, "jobId"> & { jobId?: string },
): Promise<BlenderAssistState> {
  const jobId = input.jobId ?? newJobId();
  setJobId(jobId);
  await fs.mkdir(outputDir(), { recursive: true });

  const plan = buildPackshotV1Plan({ ...input, jobId });
  jobLog(`Starting packshot_v1 for object=${plan.objectName}`);

  const verify = await runLocalVerify({
    objectName: plan.objectName,
    requireManifold: plan.verify.requireManifold,
  });
  if (!verify.ok) {
    throw new Error(`Local verify failed: ${verify.errors.join(", ")}`);
  }

  const renderCfg = {
    host: bridge.host,
    port: bridge.port,
    timeoutS: bridge.timeoutRender,
  };
  const render = await sendBridgeRequest(
    "render_packshot",
    plan.renderPayload,
    renderCfg,
  );
  if (!render.ok) {
    throw new Error(
      render.error?.message ?? `render_packshot failed: ${render.error?.code}`,
    );
  }
  jobLog(`Render saved ${plan.localPngPath}`);

  let state: BlenderAssistState = {
    version: 1,
    jobId,
    blueprint: plan.blueprint,
    phase: "awaiting_audit",
    objectName: plan.objectName,
    host: bridge.host,
    port: bridge.port,
    localPngPath: plan.localPngPath,
    localStlPath: plan.localStlPath,
    sheetsSpreadsheetId: google.sheetsSpreadsheetId,
    blueprintPayload: plan.exportPayload,
    triggerToken: buildTriggerToken(jobId),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  await saveState(state);

  await saveAuditorInput(jobId, {
    jobId,
    blueprint: plan.blueprint,
    objectName: plan.objectName,
    requireManifold: true,
    metrics: verify.metrics,
    localPngPath: plan.localPngPath,
  });

  const verdict = await auditCurrentJob();
  const refreshed = await import("../approval/state-store.js").then((m) => m.loadState());
  if (!refreshed) throw new Error("State missing after audit");
  state = refreshed;
  if (verdict.verdict !== "PASS") {
    throw new Error(`Auditor FAIL: ${verdict.reasons.join(", ")}`);
  }

  state = await enqueueGoogleSync(state);
  state = await enterAwaitingHuman(state);

  await sendApprovalNotifications(state, {
    pngName: pngFileName(plan.blueprint, jobId),
  });

  jobLog("Executor finished — awaiting human approval (npm run agent:resume).");
  return state;
}
