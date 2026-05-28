/**
 * Sheets onEdit → Cloudflare gateway (HMAC-SHA256 per jobId).
 * Install in the spreadsheet bound to Approvals sheet.
 *
 * Script properties:
 *   TRIGGER_GATEWAY_URL — worker base URL (no trailing slash)
 *   TRIGGER_HMAC_SECRET — same secret as wrangler secret / agent .env
 */
function hmacSha256Hex(message, secret) {
  const raw = Utilities.computeHmacSha256Signature(message, secret);
  return raw
    .map(function (b) {
      const n = b < 0 ? b + 256 : b;
      return ("0" + n.toString(16)).slice(-2);
    })
    .join("");
}

function onEdit(e) {
  const sheet = e.range.getSheet();
  if (sheet.getName() !== "Approvals") return;
  const row = e.range.getRow();
  if (row < 2) return;
  const status = sheet.getRange(row, 6).getValue(); // column F = status
  if (status !== "APPROVED") return;
  const jobId = String(sheet.getRange(row, 1).getValue() || "").trim();
  const secret = PropertiesService.getScriptProperties().getProperty(
    "TRIGGER_HMAC_SECRET",
  );
  const base = PropertiesService.getScriptProperties().getProperty(
    "TRIGGER_GATEWAY_URL",
  );
  if (!jobId || !secret || !base) return;

  const token = hmacSha256Hex(jobId, secret);
  const url =
    base.replace(/\/$/, "") +
    "/jobs/" +
    encodeURIComponent(jobId) +
    "/approve?token=" +
    token;
  UrlFetchApp.fetch(url, { method: "get", muteHttpExceptions: true });
}
