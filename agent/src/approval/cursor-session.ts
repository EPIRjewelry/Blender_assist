import { Agent, CursorAgentError } from "@cursor/sdk";
import { cursorSdk, repoRoot } from "../config.js";
import { jobLog } from "../logging/correlation.js";
import type { BlenderAssistState } from "./state-schema.js";

export interface CursorSessionIds {
  agentId: string;
  runId: string;
  runtime: "local" | "cloud";
}

export function withCursorSession(
  state: BlenderAssistState,
  session: CursorSessionIds,
): BlenderAssistState {
  return {
    ...state,
    cursorAgentId: session.agentId,
    cursorRunId: session.runId,
    cursorRuntime: session.runtime,
  };
}

function resolveRuntime(
  state: BlenderAssistState,
): "local" | "cloud" {
  if (state.cursorRuntime) return state.cursorRuntime;
  if (state.cursorAgentId?.startsWith("bc-")) return "cloud";
  return "local";
}

/**
 * Reattach to a prior Cursor SDK run (durable session) before local STL resume.
 * Non-fatal if IDs or API key are missing — local pipeline still proceeds.
 */
export async function attachCursorRun(
  state: BlenderAssistState,
): Promise<{ ok: boolean; status?: string }> {
  if (!state.cursorRunId) {
    return { ok: true };
  }
  if (!cursorSdk.apiKey) {
    jobLog("cursorRunId present but CURSOR_API_KEY unset — skip Agent.getRun");
    return { ok: true };
  }
  if (!state.cursorAgentId) {
    jobLog("cursorRunId without cursorAgentId — skip Agent.getRun");
    return { ok: true };
  }

  const runtime = resolveRuntime(state);
  try {
    const run = await Agent.getRun(state.cursorRunId, {
      apiKey: cursorSdk.apiKey,
      runtime,
      agentId: state.cursorAgentId,
      ...(runtime === "local" ? { cwd: repoRoot() } : {}),
    });

    jobLog(
      `Reattached Cursor run=${state.cursorRunId} agent=${state.cursorAgentId} runtime=${runtime}`,
    );

    if (run.supports("wait")) {
      const result = await run.wait();
      jobLog(`Cursor run terminal status=${result.status}`);
      return { ok: result.status !== "error", status: result.status };
    }

    return { ok: true, status: "detached" };
  } catch (err) {
    if (err instanceof CursorAgentError) {
      jobLog(`Agent.getRun failed (continuing local resume): ${err.message}`);
      return { ok: true };
    }
    throw err;
  }
}
