import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import { loadState, saveAuditorVerdict, saveState } from "../approval/state-store.js";
import type { AuditorInput, AuditorVerdict } from "../approval/state-schema.js";
import { jobLog, setJobId } from "../logging/correlation.js";
import { runLocalVerify } from "../loops/execute-verify.js";
import { isOpenRouterEnabled, openRouterChat } from "../llm/openrouter.js";

async function sha256File(filePath: string): Promise<string | undefined> {
  try {
    const buf = await fs.readFile(filePath);
    return createHash("sha256").update(buf).digest("hex");
  } catch {
    return undefined;
  }
}

export function runDeterministicAudit(input: AuditorInput): AuditorVerdict {
  const reasons: string[] = [];
  const metrics = input.metrics ?? {};
  const manifold = metrics.is_manifold;
  if (input.requireManifold && manifold !== true) {
    reasons.push("NOT_MANIFOLD");
  }
  const bbox = metrics.bbox_mm as number[] | undefined;
  if (!bbox || bbox.length !== 3 || bbox.some((v) => !Number.isFinite(v) || v <= 0)) {
    reasons.push("BBOX_INVALID");
  }
  if (input.humanApproval === false) {
    reasons.push("HUMAN_NOT_APPROVED");
  }
  const verdict = reasons.length === 0 ? "PASS" : "FAIL";
  return {
    verdict,
    reasons,
    checks: {
      manifold: manifold === true,
      bboxOk: reasons.every((r) => r !== "BBOX_INVALID"),
      humanApproval: input.humanApproval === true,
    },
  };
}

export async function auditCurrentJob(): Promise<AuditorVerdict> {
  const state = await loadState();
  if (!state) {
    throw new Error("No .blender_assist_state.json found.");
  }
  setJobId(state.jobId);

  const verify = await runLocalVerify({
    objectName: state.objectName,
    requireManifold: true,
  });

  const input: AuditorInput = {
    jobId: state.jobId,
    blueprint: state.blueprint,
    objectName: state.objectName,
    requireManifold: true,
    humanApproval: state.humanApproval,
    metrics: verify.metrics,
    localPngPath: state.localPngPath,
    pngSha256: await sha256File(state.localPngPath),
  };

  let verdict = runDeterministicAudit(input);

  if (isOpenRouterEnabled()) {
    try {
      const summary = await openRouterChat(
        [
          {
            role: "system",
            content:
              "You are a CAD auditor. Reply with JSON only: {verdict,reasons,checks}.",
          },
          {
            role: "user",
            content: JSON.stringify({ input, deterministic: verdict }),
          },
        ],
        { json: true },
      );
      const parsed = JSON.parse(summary) as AuditorVerdict;
      if (parsed.verdict === "PASS" || parsed.verdict === "FAIL") {
        verdict = parsed;
      }
    } catch (err) {
      jobLog(`OpenRouter audit skipped: ${err instanceof Error ? err.message : err}`);
    }
  }

  await saveAuditorVerdict(state.jobId, verdict);
  const nextPhase =
    verdict.verdict === "PASS" ? ("awaiting_human" as const) : ("rejected" as const);
  const next = {
    ...state,
    auditorVerdict: verdict.verdict,
    phase: nextPhase,
    updatedAt: new Date().toISOString(),
  };
  await saveState(next);
  jobLog(`Auditor verdict=${verdict.verdict} reasons=${verdict.reasons.join(";")}`);
  return verdict;
}
