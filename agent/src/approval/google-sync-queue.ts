import path from "node:path";
import { google } from "../config.js";
import { jobLog } from "../logging/correlation.js";
import type { BlenderAssistState } from "./state-schema.js";
import { jobDir, saveState, updateGoogleQueue } from "./state-store.js";

export async function enqueueGoogleSync(
  state: BlenderAssistState,
): Promise<BlenderAssistState> {
  if (!google.serviceAccountJson) {
    jobLog("Google credentials unset — skipping paced sync enqueue.");
    return state;
  }

  const now = Date.now();
  const driveAt = new Date(now + google.syncDelayMs).toISOString();
  const sheetsAt = new Date(now + google.sheetsDelayMs).toISOString();
  const perJobStatePath = path.join(jobDir(state.jobId), "state.json");

  await updateGoogleQueue((queue) => {
    queue.items.push(
      {
        jobId: state.jobId,
        kind: "drive",
        runAfter: driveAt,
        statePath: perJobStatePath,
      },
      {
        jobId: state.jobId,
        kind: "sheets",
        runAfter: sheetsAt,
        statePath: perJobStatePath,
      },
    );
    return queue;
  });

  const next: BlenderAssistState = {
    ...state,
    googleSync: {
      drivePending: true,
      sheetsPending: true,
      driveScheduledAt: driveAt,
      sheetsScheduledAt: sheetsAt,
    },
    updatedAt: new Date().toISOString(),
  };
  await saveState(next);
  jobLog(`Google sync queued (drive @ ${driveAt}, sheets @ ${sheetsAt})`);
  return next;
}
