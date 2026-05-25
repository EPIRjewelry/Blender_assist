import { randomUUID } from "node:crypto";
import net from "node:net";
import { getJobId, logPrefix } from "../logging/correlation.js";

export interface BridgeConfig {
  host: string;
  port: number;
  timeoutS: number;
}

export interface BridgeResponse {
  ok: boolean;
  request_id: string;
  result?: Record<string, unknown>;
  error?: { code: string; message: string };
}

function recvLine(socket: net.Socket): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    const onData = (chunk: Buffer) => {
      chunks.push(chunk);
      const buf = Buffer.concat(chunks);
      const idx = buf.indexOf(0x0a);
      if (idx >= 0) {
        socket.off("data", onData);
        socket.off("error", onError);
        resolve(buf.subarray(0, idx).toString("utf8"));
      }
    };
    const onError = (err: Error) => {
      socket.off("data", onData);
      reject(err);
    };
    socket.on("data", onData);
    socket.on("error", onError);
  });
}

export async function sendBridgeRequest(
  action: string,
  payload: Record<string, unknown> = {},
  config: BridgeConfig,
): Promise<BridgeResponse> {
  const requestId = randomUUID();
  const jobId = getJobId();
  const body = {
    action,
    request_id: requestId,
    payload: {
      ...payload,
      ...(jobId ? { job_id: jobId } : {}),
    },
  };
  const raw = `${JSON.stringify(body)}\n`;

  return new Promise((resolve, reject) => {
    const socket = net.createConnection(
      { host: config.host, port: config.port },
      async () => {
        try {
          socket.setTimeout(config.timeoutS * 1000);
          socket.write(raw, "utf8");
          const line = await recvLine(socket);
          socket.end();
          const parsed = JSON.parse(line) as BridgeResponse;
          if (parsed.request_id !== requestId) {
            reject(new Error(`${logPrefix()} Bridge request_id mismatch`));
            return;
          }
          resolve(parsed);
        } catch (err) {
          socket.destroy();
          reject(err);
        }
      },
    );
    socket.on("timeout", () => {
      socket.destroy();
      reject(
        new Error(
          `${logPrefix()} Timeout talking to bridge ${config.host}:${config.port}`,
        ),
      );
    });
    socket.on("error", (err) => reject(err));
  });
}

export async function blenderPing(config: BridgeConfig): Promise<boolean> {
  const res = await sendBridgeRequest("ping", {}, config);
  return res.ok === true;
}
