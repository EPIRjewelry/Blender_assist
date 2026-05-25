import path from "node:path";
import { bridge, outputDir } from "../config.js";
import { pngFileName, stlFileName } from "../logging/correlation.js";

export interface PackshotV1Input {
  jobId: string;
  objectName: string;
  hdriPath?: string;
  resolutionX?: number;
  resolutionY?: number;
  requireManifold?: boolean;
}

export interface PackshotV1Plan {
  blueprint: "packshot_v1";
  jobId: string;
  objectName: string;
  localPngPath: string;
  localStlPath: string;
  renderPayload: Record<string, unknown>;
  exportPayload: Record<string, unknown>;
  verify: {
    requireManifold: boolean;
  };
}

export function buildPackshotV1Plan(input: PackshotV1Input): PackshotV1Plan {
  const png = path.join(
    outputDir(),
    pngFileName("packshot_v1", input.jobId),
  );
  const stl = path.join(
    outputDir(),
    stlFileName("packshot_v1", input.jobId),
  );

  return {
    blueprint: "packshot_v1",
    jobId: input.jobId,
    objectName: input.objectName,
    localPngPath: png,
    localStlPath: stl,
    verify: { requireManifold: input.requireManifold !== false },
    renderPayload: {
      object_name: input.objectName,
      output_path: png,
      resolution_x: input.resolutionX ?? 1080,
      resolution_y: input.resolutionY ?? 1080,
      hdri_path: input.hdriPath ?? null,
      file_format: "PNG",
      host: bridge.host,
      port: bridge.port,
    },
    exportPayload: {
      object_name: input.objectName,
      output_path: stl,
      require_manifold: input.requireManifold !== false,
      host: bridge.host,
      port: bridge.port,
    },
  };
}
