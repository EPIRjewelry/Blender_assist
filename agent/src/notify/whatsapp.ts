import { jobLog } from "../logging/correlation.js";

export async function sendWhatsApp(params: {
  to: string;
  body: string;
}): Promise<boolean> {
  const sid = process.env.TWILIO_ACCOUNT_SID?.trim();
  const token = process.env.TWILIO_AUTH_TOKEN?.trim();
  const from = process.env.TWILIO_WHATSAPP_FROM?.trim();
  if (!sid || !token || !from) {
    jobLog("WhatsApp skipped — Twilio env unset.");
    return false;
  }
  const auth = Buffer.from(`${sid}:${token}`).toString("base64");
  const url = `https://api.twilio.com/2010-04-01/Accounts/${sid}/Messages.json`;
  const body = new URLSearchParams({
    From: from,
    To: params.to,
    Body: params.body,
  });
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });
  if (!res.ok) {
    jobLog(`WhatsApp failed HTTP ${res.status}`);
    return false;
  }
  jobLog("WhatsApp sent.");
  return true;
}
