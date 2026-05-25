import { bridge } from "../config.js";
import { sendBridgeRequest, type BridgeConfig } from "../mcp/bridge-client.js";
import { jobLog } from "../logging/correlation.js";

export interface VerifyOptions {
  objectName: string;
  requireManifold?: boolean;
  minBboxMm?: number;
  maxBboxMm?: number;
}

export interface VerifyResult {
  ok: boolean;
  errors: string[];
  metrics: Record<string, unknown>;
}

const cfg = (): BridgeConfig => ({
  host: bridge.host,
  port: bridge.port,
  timeoutS: bridge.timeoutShort,
});

export async function runLocalVerify(
  options: VerifyOptions,
): Promise<VerifyResult> {
  const errors: string[] = [];
  const metrics: Record<string, unknown> = {};
  const c = cfg();

  const ping = await sendBridgeRequest("ping", {}, c);
  if (!ping.ok) {
    return { ok: false, errors: ["BLENDER_OFFLINE"], metrics };
  }

  const info = await sendBridgeRequest(
    "object_get_info",
    { object_name: options.objectName },
    c,
  );
  if (!info.ok) {
    errors.push(info.error?.code ?? "OBJECT_GET_INFO_FAILED");
    return { ok: false, errors, metrics };
  }
  metrics.object = info.result ?? {};

  const bbox = await sendBridgeRequest(
    "mesh_get_bbox_mm",
    { object_name: options.objectName },
    c,
  );
  if (!bbox.ok) {
    errors.push(bbox.error?.code ?? "BBOX_FAILED");
  } else {
    metrics.bbox_mm = bbox.result?.bbox_mm;
    const dims = bbox.result?.bbox_mm as number[] | undefined;
    if (dims && dims.length === 3) {
      const maxDim = Math.max(...dims);
      const minDim = Math.min(...dims);
      if (options.minBboxMm != null && maxDim < options.minBboxMm) {
        errors.push("BBOX_TOO_SMALL");
      }
      if (options.maxBboxMm != null && minDim > options.maxBboxMm) {
        errors.push("BBOX_TOO_LARGE");
      }
      if (minDim <= 0) {
        errors.push("BBOX_DEGENERATE");
      }
    }
  }

  if (options.requireManifold !== false) {
    const manifold = await sendBridgeRequest(
      "mesh_check_manifold",
      { object_name: options.objectName },
      c,
    );
    if (!manifold.ok) {
      errors.push(manifold.error?.code ?? "MANIFOLD_CHECK_FAILED");
    } else {
      metrics.is_manifold = manifold.result?.is_manifold;
      if (manifold.result?.is_manifold !== true) {
        errors.push("NOT_MANIFOLD");
      }
    }
  }

  const frame = await sendBridgeRequest(
    "camera_frame_object",
    { object_name: options.objectName, camera_margin: 1.15 },
    c,
  );
  if (!frame.ok) {
    errors.push(frame.error?.code ?? "CAMERA_FRAME_FAILED");
  } else {
    metrics.camera = frame.result ?? {};
    const extent = frame.result?.bbox_extent as number[] | undefined;
    if (extent && extent.some((v) => !Number.isFinite(v) || v <= 0)) {
      errors.push("BBOX_EXTENT_DEGENERATE");
    }
  }

  const ok = errors.length === 0;
  jobLog(`local verify ok=${ok} errors=${errors.join(",") || "none"}`);
  return { ok, errors, metrics };
}
