import { readFileSync } from "node:fs";

// Test-only actual-bundle reader; never imported by demo renderers or default tests.
const root = new URL("../../demo-public/data/tohoku-descriptive-demo-v2/", import.meta.url);
export function readDemoBytes(path: string): Buffer {
  try {
    return readFileSync(new URL(path, root));
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      throw new Error("Real-data demo integration requires the accepted local v2 bundle at app/demo-public/data/tohoku-descriptive-demo-v2/. Build it using docs/data/demo-bundle.md before running npm --workspace app run test:demos. No fallback or automatic skip is provided.", { cause: error });
    }
    throw error;
  }
}
export function readDemoJson(path: string): unknown {
  return JSON.parse(readDemoBytes(path).toString("utf8")) as unknown;
}

// Test-only reader for the accepted local story map-layers bundle (no fallback, no skip).
const layersRoot = new URL("../../demo-public/data/tohoku-story-layers-v1/", import.meta.url);
export function readLayersBytes(path: string): Buffer {
  try {
    return readFileSync(new URL(path, layersRoot));
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      throw new Error("Story integration requires the local map-layers bundle at app/demo-public/data/tohoku-story-layers-v1/. Build it using docs/data/story-map-layers.md. No fallback or automatic skip is provided.", { cause: error });
    }
    throw error;
  }
}
export function readLayersJson(path: string): unknown {
  return JSON.parse(readLayersBytes(path).toString("utf8")) as unknown;
}
