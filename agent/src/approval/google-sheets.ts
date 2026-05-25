import { jobLog } from "../logging/correlation.js";
import { google } from "../config.js";
import type { BlenderAssistState } from "./state-schema.js";

const HEADERS = [
  "job_id",
  "blueprint",
  "object_name",
  "local_png_path",
  "drive_link",
  "status",
  "reviewer_notes",
  "updated_at",
];

export async function appendPendingRow(
  state: BlenderAssistState,
): Promise<number | null> {
  if (!google.serviceAccountJson || !google.sheetsSpreadsheetId) {
    jobLog("Sheets append skipped — missing Google env.");
    return null;
  }

  try {
    const fs = await import("node:fs/promises");
    const { google: googleapis } = await import("googleapis");
    const creds = JSON.parse(
      await fs.readFile(google.serviceAccountJson, "utf8"),
    );
    const auth = new googleapis.auth.GoogleAuth({
      credentials: creds,
      scopes: ["https://www.googleapis.com/auth/spreadsheets"],
    });
    const sheets = googleapis.sheets({ version: "v4", auth });
    const row = [
      state.jobId,
      state.blueprint,
      state.objectName,
      state.localPngPath,
      state.driveLink ?? "",
      "PENDING",
      "",
      new Date().toISOString(),
    ];
    const res = await sheets.spreadsheets.values.append({
      spreadsheetId: google.sheetsSpreadsheetId,
      range: "Approvals!A:H",
      valueInputOption: "USER_ENTERED",
      insertDataOption: "INSERT_ROWS",
      requestBody: { values: [row] },
    });
    const updates = res.data.updates;
    const rowIndex = updates?.updatedRange
      ? parseInt(updates.updatedRange.split("!")[1]?.split(":")[0]?.replace(/\D/g, "") ?? "0", 10)
      : null;
    jobLog(`Sheets row appended rowIndex=${rowIndex ?? "unknown"}`);
    return rowIndex;
  } catch (err) {
    jobLog(`Sheets append failed: ${err instanceof Error ? err.message : err}`);
    return null;
  }
}

export async function readStatusByJobId(
  jobId: string,
): Promise<"PENDING" | "APPROVED" | "REJECTED" | null> {
  if (!google.serviceAccountJson || !google.sheetsSpreadsheetId) {
    return null;
  }

  try {
    const fs = await import("node:fs/promises");
    const { google: googleapis } = await import("googleapis");
    const creds = JSON.parse(
      await fs.readFile(google.serviceAccountJson, "utf8"),
    );
    const auth = new googleapis.auth.GoogleAuth({
      credentials: creds,
      scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
    });
    const sheets = googleapis.sheets({ version: "v4", auth });
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId: google.sheetsSpreadsheetId,
      range: "Approvals!A:H",
    });
    const rows = res.data.values ?? [];
    if (rows.length === 0) {
      await sheets.spreadsheets.values.update({
        spreadsheetId: google.sheetsSpreadsheetId,
        range: "Approvals!A1:H1",
        valueInputOption: "RAW",
        requestBody: { values: [HEADERS] },
      });
      return null;
    }
    for (let i = 1; i < rows.length; i++) {
      const row = rows[i];
      if (row?.[0] === jobId) {
        const status = String(row[5] ?? "PENDING").toUpperCase();
        if (status === "APPROVED" || status === "REJECTED" || status === "PENDING") {
          return status;
        }
      }
    }
    return null;
  } catch (err) {
    jobLog(`Sheets read failed: ${err instanceof Error ? err.message : err}`);
    return null;
  }
}
