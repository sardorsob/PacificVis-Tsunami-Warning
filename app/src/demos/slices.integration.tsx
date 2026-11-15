import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { eventsIndex, localFetch, readDataBytes, tohokuEntry } from "./integration-data";
import { loadManifest } from "./loader";
import { loadBasemap, loadGeometry, loadSliceManifest, loadSliceStation, loadStation, loadViewManifest, type SliceRecords, type SliceView } from "./slices";
import { StationCard } from "./StationCard";
import { loadLayers } from "./story/layers";

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

const byId = (id: string) => eventsIndex.events.find(e => e.event_id === id)!;
describe("the app's records path on the pilot event and the empty record", () => {
  it("opens Illapel through the schema dispatch and the real validators: default station La Jolla, its record, geometry and layers", async () => {
    const illapel = byId("us20003k7a"), m = await loadViewManifest(illapel, undefined, localFetch) as SliceView;
    expect([m.schema_version, m.default_state]).toEqual(["2", { selectedStationId: "9410230", pinnedStationId: null, windowId: "display", productKey: "raw_value" }]);
    expect(m.stations.find(s => s.station_id === "9410230")!.name).toBe("La Jolla");
    const r = await loadStation(m, "9410230", undefined, localFetch) as SliceRecords;
    expect(r.counts.rows).toBe(m.stations.find(s => s.station_id === "9410230")!.rows); expect(r.segments.length).toBeGreaterThan(0);
    expect((await loadGeometry(m, illapel, undefined, localFetch)).points).toHaveLength(m.stations.length + 1);
    expect((await loadLayers(illapel, undefined, localFetch)).manifest.contour_source_id).toBe("ncei-ttt-us20003k7a-layer19-geojson");
  });
  it("shows Maule station 9413450's header-only file as a record with no rows in the display window", async () => {
    const m = await loadViewManifest(byId("official20100227063411530_30"), undefined, localFetch) as SliceView;
    const station = m.stations.find(s => s.station_id === "9413450")!, records = await loadStation(m, "9413450", undefined, localFetch) as SliceRecords;
    expect([station.rows, records.rows.length]).toEqual([0, 0]);
    const html = renderToStaticMarkup(<StationCard selection={{ station, status: "ready", records, error: null }} role="selected" windowId="display"
      productKey="raw_value" onOpenEvidence={() => undefined} onRetryStation={() => undefined}/>);
    expect(html).toContain("This record has no rows in the display window.");
  });
});
