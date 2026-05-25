import { z } from "zod";

export const JobPhase = z.enum([
  "local_verify",
  "render",
  "awaiting_audit",
  "awaiting_human",
  "resume_check",
  "export_stl",
  "done",
  "rejected",
]);

export const BlenderAssistStateSchema = z.object({
  version: z.literal(1),
  jobId: z.string().uuid(),
  blueprint: z.string(),
  phase: JobPhase,
  auditorVerdict: z.enum(["PASS", "FAIL"]).optional(),
  humanApproval: z.boolean().optional(),
  humanApprovalSource: z.enum(["sheets", "webhook", "cli"]).optional(),
  triggerToken: z.string().optional(),
  objectName: z.string(),
  host: z.string(),
  port: z.number().int(),
  localPngPath: z.string(),
  localStlPath: z.string().optional(),
  sheetsSpreadsheetId: z.string().optional(),
  sheetsRowIndex: z.number().int().optional(),
  driveFileId: z.string().optional(),
  driveLink: z.string().optional(),
  blueprintPayload: z.record(z.unknown()),
  googleSync: z
    .object({
      drivePending: z.boolean().optional(),
      driveDone: z.boolean().optional(),
      sheetsPending: z.boolean().optional(),
      sheetsDone: z.boolean().optional(),
      driveScheduledAt: z.string().optional(),
      sheetsScheduledAt: z.string().optional(),
    })
    .optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type BlenderAssistState = z.infer<typeof BlenderAssistStateSchema>;

export const AuditorInputSchema = z.object({
  jobId: z.string().uuid(),
  blueprint: z.string(),
  objectName: z.string(),
  requireManifold: z.boolean().default(true),
  humanApproval: z.boolean().optional(),
  metrics: z.record(z.unknown()).optional(),
  localPngPath: z.string(),
  pngSha256: z.string().optional(),
});

export type AuditorInput = z.infer<typeof AuditorInputSchema>;

export const AuditorVerdictSchema = z.object({
  verdict: z.enum(["PASS", "FAIL"]),
  reasons: z.array(z.string()),
  checks: z.record(z.unknown()).optional(),
});

export type AuditorVerdict = z.infer<typeof AuditorVerdictSchema>;

export const GoogleSyncQueueSchema = z.object({
  version: z.literal(1),
  items: z.array(
    z.object({
      jobId: z.string().uuid(),
      kind: z.enum(["drive", "sheets"]),
      runAfter: z.string(),
      statePath: z.string(),
    }),
  ),
});

export type GoogleSyncQueue = z.infer<typeof GoogleSyncQueueSchema>;
