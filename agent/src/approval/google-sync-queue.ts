import { google, repoRoot } from "../config.js";
import { globalStatePath } from "../config.js";
import { jobLog } from "../logging/correlation.js";
import type { BlenderAssistState } from "./state-schema.js";
import {
  loadGoogleQueue,
  saveGoogleQueue,
  saveState,
} from "./state-store.js";

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
  const queue = await loadGoogleQueue();

  queue.items.push(
    {
      jobId: state.jobId,
      kind: "drive",
      runAfter: driveAt,
      statePath: globalStatePath(),
    },
    {
      jobId: state.jobId,
      kind: "sheets",
      runAfter: sheetsAt,
      statePath: globalStatePath(),
    },
  );

  await saveGoogleQueue(queue);

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
