import { randomUUID } from "node:crypto";

let currentJobId: string | undefined;

export function newJobId(): string {
  currentJobId = randomUUID();
  return currentJobId;
}

export function getJobId(): string | undefined {
  return currentJobId ?? process.env.BLENDER_ASSIST_JOB_ID;
}

export function setJobId(jobId: string): void {
  currentJobId = jobId;
  process.env.BLENDER_ASSIST_JOB_ID = jobId;
}

export function logPrefix(): string {
  const id = getJobId();
  return id ? `[job_id=${id}]` : "[job_id=unknown]";
}

export function jobLog(message: string): void {
  console.log(`${logPrefix()} ${message}`);
}

export function pngFileName(blueprint: string, jobId: string): string {
  return `${blueprint}_${jobId}.png`;
}

export function stlFileName(blueprint: string, jobId: string): string {
  return `${blueprint}_${jobId}.stl`;
}
