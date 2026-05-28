import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import {
  agentStateDir,
  globalStatePath,
  repoRoot,
} from "../config.js";
import {
  AuditorInputSchema,
  AuditorVerdictSchema,
  BlenderAssistState,
  BlenderAssistStateSchema,
  GoogleSyncQueue,
  GoogleSyncQueueSchema,
} from "./state-schema.js";

async function atomicWrite(filePath: string, data: string): Promise<void> {
  const dir = path.dirname(filePath);
  await fs.mkdir(dir, { recursive: true });
  const tmp = path.join(
    dir,
    `.${path.basename(filePath)}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`,
  );
  await fs.writeFile(tmp, data, { encoding: "utf8", flag: "wx" });
  await fs.rename(tmp, filePath);
}

export function jobDir(jobId: string): string {
  return path.join(agentStateDir(), jobId);
}

export async function saveState(state: BlenderAssistState): Promise<void> {
  const parsed = BlenderAssistStateSchema.parse(state);
  parsed.updatedAt = new Date().toISOString();
  const payload = `${JSON.stringify(parsed, null, 2)}\n`;
  const perJobPath = path.join(jobDir(parsed.jobId), "state.json");
  await atomicWrite(perJobPath, payload);
  await atomicWrite(globalStatePath(), payload);
}

export async function loadState(jobId?: string): Promise<BlenderAssistState | null> {
  const resolvedId =
    jobId?.trim() || process.env.BLENDER_ASSIST_JOB_ID?.trim() || undefined;

  if (resolvedId) {
    try {
      const raw = await fs.readFile(
        path.join(jobDir(resolvedId), "state.json"),
        "utf8",
      );
      return BlenderAssistStateSchema.parse(JSON.parse(raw));
    } catch {
      /* fall through to global pointer */
    }
  }

  try {
    const raw = await fs.readFile(globalStatePath(), "utf8");
    return BlenderAssistStateSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}

export async function saveAuditorInput(
  jobId: string,
  input: unknown,
): Promise<string> {
  const parsed = AuditorInputSchema.parse(input);
  const filePath = path.join(jobDir(jobId), "auditor_input.json");
  await atomicWrite(filePath, `${JSON.stringify(parsed, null, 2)}\n`);
  return filePath;
}

export async function saveAuditorVerdict(
  jobId: string,
  verdict: unknown,
): Promise<void> {
  const parsed = AuditorVerdictSchema.parse(verdict);
  await atomicWrite(
    path.join(jobDir(jobId), "auditor_verdict.json"),
    `${JSON.stringify(parsed, null, 2)}\n`,
  );
}

export async function loadAuditorVerdict(jobId: string) {
  try {
    const raw = await fs.readFile(
      path.join(jobDir(jobId), "auditor_verdict.json"),
      "utf8",
    );
    return AuditorVerdictSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}

const queuePath = (): string => path.join(repoRoot(), "agent", ".state", "google_sync_queue.json");

export async function loadGoogleQueue(): Promise<GoogleSyncQueue> {
  try {
    const raw = await fs.readFile(queuePath(), "utf8");
    return GoogleSyncQueueSchema.parse(JSON.parse(raw));
  } catch {
    return { version: 1, items: [] };
  }
}

export async function saveGoogleQueue(queue: GoogleSyncQueue): Promise<void> {
  const parsed = GoogleSyncQueueSchema.parse(queue);
  await atomicWrite(queuePath(), `${JSON.stringify(parsed, null, 2)}\n`);
}

/** Read-modify-write with short retries — reduces lost updates under parallel jobs. */
export async function updateGoogleQueue(
  mutator: (queue: GoogleSyncQueue) => GoogleSyncQueue,
): Promise<GoogleSyncQueue> {
  const file = queuePath();
  for (let attempt = 0; attempt < 5; attempt++) {
    const current = await loadGoogleQueue();
    const next = GoogleSyncQueueSchema.parse(mutator(current));
    await atomicWrite(file, `${JSON.stringify(next, null, 2)}\n`);
    return next;
  }
  throw new Error("updateGoogleQueue: exhausted retries");
}
