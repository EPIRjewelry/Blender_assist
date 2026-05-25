import type { BlenderAssistState } from "../approval/state-schema.js";
import { approveUrl } from "../approval/trigger-gateway.js";
import { jobLog } from "../logging/correlation.js";
import { sendEmail } from "./email.js";
import { sendWhatsApp } from "./whatsapp.js";

export async function sendApprovalNotifications(
  state: BlenderAssistState,
  meta: { pngName: string },
): Promise<void> {
  const link = approveUrl(state.jobId, state.triggerToken);
  const drive = state.driveLink ?? state.localPngPath;
  const text = [
    `Blender Assist — ${state.blueprint}`,
    `job_id: ${state.jobId}`,
    `object: ${state.objectName}`,
    `preview: ${drive}`,
    link ? `approve: ${link}` : "approve: set TRIGGER_GATEWAY_URL",
    `resume CLI: npm run agent:resume`,
  ].join("\n");

  const emailTo = process.env.NOTIFY_EMAIL_TO?.trim();
  if (emailTo) {
    await sendEmail({
      to: emailTo,
      subject: `[Blender Assist] Review ${meta.pngName}`,
      html: `<pre>${text}</pre>`,
    });
  }

  const waTo = process.env.NOTIFY_WHATSAPP_TO?.trim();
  if (waTo) {
    await sendWhatsApp({ to: waTo, body: text });
  }

  if (!emailTo && !waTo) {
    jobLog("No NOTIFY_EMAIL_TO / NOTIFY_WHATSAPP_TO — notifications skipped.");
  }
}
