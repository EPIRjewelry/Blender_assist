import type { BlenderAssistState } from "./state-schema.js";
import { saveState } from "./state-store.js";
import { jobLog } from "../logging/correlation.js";
import { trigger } from "../config.js";

export async function enterAwaitingHuman(
  state: BlenderAssistState,
): Promise<BlenderAssistState> {
  const next: BlenderAssistState = {
    ...state,
    phase: "awaiting_human",
    updatedAt: new Date().toISOString(),
  };
  await saveState(next);
  const approveUrl =
    trigger.gatewayUrl && state.triggerToken
      ? `${trigger.gatewayUrl.replace(/\/$/, "")}/jobs/${state.jobId}/approve?token=${state.triggerToken}`
      : "(set TRIGGER_GATEWAY_URL)";
  jobLog(`Awaiting human approval. Resume: npm run agent:resume`);
  jobLog(`Approve link: ${approveUrl}`);
  return next;
}

export async function enterAwaitingAudit(
  state: BlenderAssistState,
): Promise<BlenderAssistState> {
  const next: BlenderAssistState = {
    ...state,
    phase: "awaiting_audit",
    updatedAt: new Date().toISOString(),
  };
  await saveState(next);
  jobLog("Awaiting auditor PASS (npm run agent:audit or cloud orchestrator).");
  return next;
}
