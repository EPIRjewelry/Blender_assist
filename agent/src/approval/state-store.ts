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
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const tmp = `${filePath}.${process.pid}.tmp`;
  await fs.writeFile(tmp, data, "utf8");
  await fs.rename(tmp, filePath);
}

export function jobDir(jobId: string): string {
  return path.join(agentStateDir(), jobId);
}

export async function saveState(state: BlenderAssistState): Promise<void> {
  const parsed = BlenderAssistStateSchema.parse(state);
  parsed.updatedAt = new Date().toISOString();
  const payload = `${JSON.stringify(parsed, null, 2)}\n`;
  await atomicWrite(globalStatePath(), payload);
  await atomicWrite(path.join(jobDir(parsed.jobId), "state.json"), payload);
}

export async function loadState(): Promise<BlenderAssistState | null> {
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
  await atomicWrite(queuePath(), `${JSON.stringify(queue, null, 2)}\n`);
}
