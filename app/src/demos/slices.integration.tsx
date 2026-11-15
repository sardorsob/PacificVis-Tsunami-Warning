import { describe, expect, it } from "vitest";
import { eventsIndex, localFetch, readDataBytes, tohokuEntry } from "./integration-data";
import { loadManifest } from "./loader";
import { loadBasemap, loadSliceManifest, loadSliceStation } from "./slices";

// Records schema 2 on the real local bundles, reached through the index and the browser's own loaders (no fallback, no skip).
const schema2 = eventsIndex.events.filter(e => e.records &&
  (JSON.parse(readDataBytes(`${e.records.bundle_id}/manifest.json`).toString("utf8")) as { schema_version: unknown }).schema_version === "2");

describe("records schema 2 against the local multi-event bundles", () => {
  it("loads every pinned manifest, decodes every station file, and the rows add up", async () => {
    const totals = { events: 0, files: 0, rows: 0, blank: 0, duplicate_rows: 0, duplicates_dropped: 0, outside_window: 0, backward_steps: 0 };
    const empty: string[] = [], backward: string[] = [];
    let largest = { bytes: 0, ms: 0, name: "" };
    for (const entry of schema2) {
      const manifest = await loadSliceManifest(entry, undefined, localFetch); totals.events++;
      let rows = 0;
      for (const station of manifest.stations) {
        const name = `${manifest.bundle_id}/${station.station_id}`, bytes = manifest.assets.find(a => a.path === `stations/${station.station_id}.csv.gz`)!.bytes;
        const start = performance.now(), r = await loadSliceStation(manifest, station.station_id, undefined, localFetch), took = performance.now() - start;
        if (bytes > largest.bytes) largest = { bytes, ms: took, name };
        const c = r.counts; totals.files++; rows += c.rows; totals.blank += c.blank; totals.duplicates_dropped += c.duplicates_dropped;
        totals.outside_window += c.outside_window; totals.backward_steps += c.backward_steps; totals.duplicate_rows += r.rows.filter(x => x.duplicate_timestamp).length;
        if (!c.rows) empty.push(name);
        if (c.backward_steps) backward.push(`${name} ×${c.backward_steps}`);
      }
      expect(rows, entry.event_id).toBe(manifest.accounting.rows); totals.rows += rows;
    }
    console.info("records schema 2 totals", totals, "largest station file", largest);
    expect(totals).toEqual({ events: 13, files: 251, rows: 481_432, blank: 17_311, duplicate_rows: 32, duplicates_dropped: 16, outside_window: 0, backward_steps: 2 });
    expect(empty).toEqual(["records-official20100227063411530_30-v1/9413450"]);
    expect(backward).toEqual(["records-usp000exfn-v1/9414290 ×2"]);
  }, 120_000);
  it("loads the shared basemap the index pins", async () => {
    const coast = await loadBasemap(eventsIndex, undefined, localFetch);
    expect([coast.parts.length, coast.closed.length]).toEqual([147, 147]);
  });
  it("still loads Tōhoku through the schema-1 path, which the schema-2 reader refuses", async () => {
    expect(schema2.some(e => e.event_id === tohokuEntry.event_id)).toBe(false);
    expect((await loadManifest(tohokuEntry, undefined, localFetch)).schema_version).toBe("1");
    await expect(loadSliceManifest(tohokuEntry, undefined, localFetch)).rejects.toThrow(/fields/); // schema-1 keys, refused before the version
  });
});
