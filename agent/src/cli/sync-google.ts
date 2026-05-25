import fs from "node:fs/promises";
import { loadGoogleQueue, saveGoogleQueue, loadState, saveState } from "../approval/state-store.js";
import { uploadPngToDrive } from "../approval/google-drive.js";
import { appendPendingRow } from "../approval/google-sheets.js";
import { pngFileName, jobLog } from "../logging/correlation.js";
import { BlenderAssistStateSchema } from "../approval/state-schema.js";

export async function processGoogleSyncQueue(): Promise<void> {
  const queue = await loadGoogleQueue();
  const now = new Date().toISOString();
  const remaining = [];

  for (const item of queue.items) {
    if (item.runAfter > now) {
      remaining.push(item);
      continue;
    }

    let raw: string;
    try {
      raw = await fs.readFile(item.statePath, "utf8");
    } catch {
      jobLog(`Skip sync — state file missing for ${item.jobId}`);
      continue;
    }

    const state = BlenderAssistStateSchema.parse(JSON.parse(raw));
    if (item.kind === "drive" && !state.googleSync?.driveDone) {
      const name = pngFileName(state.blueprint, state.jobId);
      const uploaded = await uploadPngToDrive(state.localPngPath, name);
      if (uploaded) {
        state.driveFileId = uploaded.fileId;
        state.driveLink = uploaded.webViewLink;
        state.googleSync = { ...state.googleSync, driveDone: true, drivePending: false };
        await saveState(state);
      }
    }

    if (item.kind === "sheets" && !state.googleSync?.sheetsDone) {
      const row = await appendPendingRow(state);
      if (row != null) {
        state.sheetsRowIndex = row;
        state.googleSync = { ...state.googleSync, sheetsDone: true, sheetsPending: false };
        await saveState(state);
      }
    }
  }

  await saveGoogleQueue({ version: 1, items: remaining });
  jobLog(`Google sync processed; ${remaining.length} item(s) remaining.`);
}

processGoogleSyncQueue().catch((err) => {
  console.error(err);
  process.exit(1);
});
