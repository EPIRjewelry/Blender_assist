import fs from "node:fs/promises";
import { jobLog } from "../logging/correlation.js";
import { google } from "../config.js";

/**
 * Upload PNG to Google Drive (Service Account).
 * Requires GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_DRIVE_FOLDER_ID.
 */
export async function uploadPngToDrive(
  localPath: string,
  remoteName: string,
): Promise<{ fileId: string; webViewLink: string } | null> {
  if (!google.serviceAccountJson || !google.driveFolderId) {
    jobLog("Drive upload skipped — missing Google env.");
    return null;
  }

  try {
    const { google: googleapis } = await import("googleapis");
    const creds = JSON.parse(
      await fs.readFile(google.serviceAccountJson, "utf8"),
    );
    const auth = new googleapis.auth.GoogleAuth({
      credentials: creds,
      scopes: ["https://www.googleapis.com/auth/drive.file"],
    });
    const drive = googleapis.drive({ version: "v3", auth });
    const body = await fs.readFile(localPath);
    const res = await drive.files.create({
      requestBody: {
        name: remoteName,
        parents: [google.driveFolderId],
      },
      media: { mimeType: "image/png", body: Buffer.from(body) },
      fields: "id, webViewLink",
    });
    const fileId = res.data.id ?? "";
    const webViewLink = res.data.webViewLink ?? "";
    jobLog(`Drive upload ok fileId=${fileId}`);
    return { fileId, webViewLink };
  } catch (err) {
    jobLog(`Drive upload failed: ${err instanceof Error ? err.message : err}`);
    return null;
  }
}
