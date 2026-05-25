/**
 * Optional: Sheets onEdit → Cloudflare gateway (no agent polling).
 * Install in the spreadsheet bound to Approvals sheet.
 */
function onEdit(e) {
  const sheet = e.range.getSheet();
  if (sheet.getName() !== "Approvals") return;
  const row = e.range.getRow();
  if (row < 2) return;
  const status = sheet.getRange(row, 6).getValue(); // column F = status
  if (status !== "APPROVED") return;
  const jobId = sheet.getRange(row, 1).getValue();
  const token = PropertiesService.getScriptProperties().getProperty("TRIGGER_HMAC_TOKEN");
  const base = PropertiesService.getScriptProperties().getProperty("TRIGGER_GATEWAY_URL");
  if (!jobId || !token || !base) return;
  UrlFetchApp.fetch(base + "/jobs/" + jobId + "/approve?token=" + token, { method: "get" });
}
