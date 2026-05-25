import { trigger } from "../config.js";
import { jobLog } from "../logging/correlation.js";

export async function checkGatewayApproval(
  jobId: string,
  token?: string,
): Promise<{ approved: boolean }> {
  if (!trigger.gatewayUrl) {
    return { approved: false };
  }
  const base = trigger.gatewayUrl.replace(/\/$/, "");
  const url = new URL(`${base}/jobs/${jobId}/status`);
  if (token) url.searchParams.set("token", token);

  try {
    const res = await fetch(url.toString(), { method: "GET" });
    if (!res.ok) {
      jobLog(`Gateway status HTTP ${res.status}`);
      return { approved: false };
    }
    const data = (await res.json()) as { approved?: boolean };
    return { approved: data.approved === true };
  } catch (err) {
    jobLog(`Gateway unreachable: ${err instanceof Error ? err.message : err}`);
    return { approved: false };
  }
}

export function approveUrl(jobId: string, token?: string): string | null {
  if (!trigger.gatewayUrl || !token) return null;
  const base = trigger.gatewayUrl.replace(/\/$/, "");
  return `${base}/jobs/${jobId}/approve?token=${token}`;
}
