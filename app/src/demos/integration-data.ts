import { readFileSync } from "node:fs";
import { validateIndex } from "./loader";
import type { EventEntry } from "./types";

// Test-only actual-bundle reader; never imported by demo renderers or default tests.
// Everything is reached through the real events index, as the browser does: the index names (and pins) each bundle.
const dataRoot = new URL("../../demo-public/data/", import.meta.url);
/** Bytes under app/demo-public/data/, addressed by the path the browser fetches below /data/. */
export function readDataBytes(path: string): Buffer {
  try {
    return readFileSync(new URL(path, dataRoot));
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      throw new Error(`Real-data demo integration requires app/demo-public/data/${path}. Build the bundles and then the events index using docs/data/demo-bundle.md before running npm --workspace app run test:demos. No fallback or automatic skip is provided.`, { cause: error });
    }
    throw error;
  }
}
export const eventsIndex = validateIndex(JSON.parse(readDataBytes("events.json").toString("utf8")) as unknown);
/** The index's default event (Tōhoku); the real-data tests pin its identity. */
export const tohokuEntry: EventEntry = eventsIndex.events.find(e => e.event_id === eventsIndex.default_event_id)!;
export function readDemoBytes(path: string): Buffer {
  return readDataBytes(`${tohokuEntry.records!.bundle_id}/${path}`);
}
export function readDemoJson(path: string): unknown {
  return JSON.parse(readDemoBytes(path).toString("utf8")) as unknown;
}
// Test-only reader for the local story map-layers bundle named by the index (no fallback, no skip).
export function readLayersBytes(path: string): Buffer {
  return readDataBytes(`${tohokuEntry.layers!.bundle_id}/${path}`);
}
export function readLayersJson(path: string): unknown {
  return JSON.parse(readLayersBytes(path).toString("utf8")) as unknown;
}
/** A fetch stand-in serving the real local files at the browser's /data/ URLs. */
export const localFetch = async (url: string | URL | Request) => new Response(new Uint8Array(readDataBytes(String(url).replace(/^\/data\//, ""))));
