export interface Env {
  JOB_FLAGS: KVNamespace;
  ARTIFACTS: R2Bucket;
  TRIGGER_HMAC_SECRET: string;
}

async function verifyToken(
  env: Env,
  jobId: string,
  token: string | null,
): Promise<boolean> {
  if (!token || !env.TRIGGER_HMAC_SECRET) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(env.TRIGGER_HMAC_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(jobId),
  );
  const expected = [...new Uint8Array(sig)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return timingSafeEqual(token, expected);
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const approveMatch = url.pathname.match(/^\/jobs\/([^/]+)\/approve$/);
    const statusMatch = url.pathname.match(/^\/jobs\/([^/]+)\/status$/);

    if (approveMatch && request.method === "GET") {
      const jobId = approveMatch[1];
      const token = url.searchParams.get("token");
      if (!(await verifyToken(env, jobId, token))) {
        return new Response("Invalid token", { status: 403 });
      }
      await env.JOB_FLAGS.put(
        `job:${jobId}`,
        JSON.stringify({ approved: true, at: new Date().toISOString() }),
      );
      return new Response(
        `Approved job ${jobId}. Run: npm run agent:resume`,
        { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } },
      );
    }

    if (statusMatch && request.method === "GET") {
      const jobId = statusMatch[1];
      const token = url.searchParams.get("token");
      if (!(await verifyToken(env, jobId, token))) {
        return new Response(JSON.stringify({ approved: false }), {
          status: 403,
          headers: { "content-type": "application/json" },
        });
      }
      const raw = await env.JOB_FLAGS.get(`job:${jobId}`);
      const approved = raw ? (JSON.parse(raw) as { approved?: boolean }).approved === true : false;
      return new Response(JSON.stringify({ jobId, approved }), {
        headers: { "content-type": "application/json" },
      });
    }

    if (url.pathname === "/health") {
      return new Response("ok");
    }

    return new Response("Not found", { status: 404 });
  },
};
