import { jobLog } from "../logging/correlation.js";

export async function sendEmail(params: {
  to: string;
  subject: string;
  html: string;
}): Promise<boolean> {
  const apiKey = process.env.RESEND_API_KEY?.trim();
  if (!apiKey) {
    jobLog("Email skipped — RESEND_API_KEY unset.");
    return false;
  }
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: process.env.NOTIFY_EMAIL_FROM ?? "Blender Assist <onboarding@resend.dev>",
      to: [params.to],
      subject: params.subject,
      html: params.html,
    }),
  });
  if (!res.ok) {
    jobLog(`Email failed HTTP ${res.status}`);
    return false;
  }
  jobLog("Email sent.");
  return true;
}
