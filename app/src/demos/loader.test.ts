import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { loadIndex, loadManifest, validateGeometry, validateIndex, validateManifest } from "./loader";
import type { EventEntry } from "./types";

// The contract's synthetic, test-only index (docs/data/examples); the builder's tests must accept it too.
const example = () => JSON.parse(readFileSync(new URL("../../../docs/data/examples/story-events.example.json", import.meta.url), "utf8")) as {
  default_event_id: string; events: Record<string, unknown>[] };
const withEvent = (i: number, patch: Record<string, unknown>) => { const x = example(); x.events[i] = { ...x.events[i], ...patch }; return x; };

describe("events index (schema 1)", () => {
  it("accepts the contract's example index, including an event without records or layers", () => {
    const index = validateIndex(example());
    expect(index.events.map(e => e.event_id)).toEqual(["example-event-a", "example-event-b"]);
    expect(index.events[1]).toMatchObject({ records: null, layers: null });
  });
  it("rejects an unknown default, a duplicate id, a wrong order, an unsafe arrivals path and a bad hash", () => {
    expect(() => validateIndex({ ...example(), default_event_id: "missing" })).toThrow(/default/);
    expect(() => validateIndex(withEvent(1, { event_id: "example-event-a", origin_time_utc: "2003-01-01T00:00:00Z", arrivals: null }))).toThrow(/duplicate/);
    const swapped = example(); swapped.events.reverse(); expect(() => validateIndex(swapped)).toThrow(/order/);
    expect(() => validateIndex(withEvent(0, { arrivals: { path: "../arrivals/x.json", sha256: "c".repeat(64), bytes: 1 } }))).toThrow(/arrivals/);
    expect(() => validateIndex(withEvent(0, { records: { bundle_id: "example-records-a", manifest_sha256: "A".repeat(64), manifest_bytes: 1 } }))).toThrow(/SHA256/);
  });
  it("rejects other schema drift: same-time order by id, unsafe ids, empty list, bad origin or coordinates, extra fields", () => {
    expect(() => validateIndex(withEvent(1, { origin_time_utc: "2001-01-01T00:00:00Z", event_id: "example-event-0", arrivals: null }))).toThrow(/order/);
    expect(() => validateIndex(withEvent(1, { origin_time_utc: "2001-01-01T00:00:00Z", event_id: "example-event-c", arrivals: null }))).not.toThrow();
    expect(() => validateIndex(withEvent(0, { event_id: "../a" }))).toThrow();
    expect(() => validateIndex({ ...example(), events: [], default_event_id: "x" })).toThrow();
    expect(() => validateIndex(withEvent(0, { origin_time_utc: "2001-02-30T00:00:00Z" }))).toThrow();
    expect(() => validateIndex(withEvent(0, { latitude: 91 }))).toThrow();
    expect(() => validateIndex(withEvent(0, { magnitude: "8" }))).toThrow();
    expect(() => validateIndex(withEvent(0, { label: "" }))).toThrow();
    expect(() => validateIndex(withEvent(0, { layers: { bundle_id: "x/y", manifest_sha256: "b".repeat(64), manifest_bytes: 1 } }))).toThrow();
    expect(() => validateIndex(withEvent(0, { records: { bundle_id: "x", manifest_sha256: "b".repeat(64), manifest_bytes: 0 } }))).toThrow();
    expect(() => validateIndex(withEvent(0, { role: "model" }))).toThrow();
    expect(() => validateIndex(withEvent(0, { longitude: -180.5 }))).toThrow();
  });
  it("applies the amended rules: arrivals named after the event and ≤ 2 MiB, one bundle per event, order by instant", () => {
    const arrivals = (path: string, bytes = 1) => ({ arrivals: { path, sha256: "c".repeat(64), bytes } });
    expect(() => validateIndex(withEvent(0, arrivals("story-arrivals-v1/example-event-a.json", 2_097_152)))).not.toThrow();
    expect(() => validateIndex(withEvent(0, arrivals("story-arrivals-v1/example-event-b.json")))).toThrow(/arrivals/);
    expect(() => validateIndex(withEvent(0, arrivals("example-event-a.json")))).toThrow(/arrivals/);
    expect(() => validateIndex(withEvent(0, arrivals("a/b/example-event-a.json")))).toThrow(/arrivals/);
    expect(() => validateIndex(withEvent(0, arrivals("story-arrivals-v1/example-event-a.json", 2_097_153)))).toThrow(/arrivals/);
    expect(() => validateIndex(withEvent(1, { layers: { bundle_id: "example-records-a", manifest_sha256: "b".repeat(64), manifest_bytes: 1 } }))).toThrow(/bundle/);
    const at = (a: string, b: string) => { const x = example(); x.events[0].origin_time_utc = a; x.events[1].origin_time_utc = b; return x; };
    expect(() => validateIndex(at("2001-01-01T00:00:00Z", "2001-01-01T00:00:00.5Z"))).not.toThrow();
    expect(() => validateIndex(at("2001-01-01T00:00:00.5Z", "2001-01-01T00:00:00Z"))).toThrow(/order/); // ".5Z" < "Z" as text only
    expect(() => validateIndex({ ...example(), schema_version: "2" })).toThrow();
  });
  it("fetches /data/events.json and validates it", async () => {
    let url = "";
    const index = await loadIndex(undefined, async u => { url = String(u); return new Response(JSON.stringify(example())); });
    expect(url).toBe("/data/events.json"); expect(index.default_event_id).toBe("example-event-a");
  });
});

// A deliberate two-station unit-test manifest; never a fallback for the real bundle.
const entry: EventEntry = { event_id: "test-event", label: "Test event", origin_time_utc: "2001-01-01T00:00:00Z", latitude: 0, longitude: -160,
  magnitude: 8, magnitude_type: "mww", records: { bundle_id: "test-records", manifest_sha256: "a".repeat(64), manifest_bytes: 1 }, layers: null, arrivals: null };
const station = (station_id: string, observation_count: number, station_type = "coastal") => ({ station_id, source_id: `src-${station_id}`, station_type,
  name: `Test ${station_id}`, units: "m", vertical_reference: "unknown", horizontal_datum: "unknown", coordinate_order: "longitude,latitude", time_basis: "UTC",
  latitude: 1, longitude: 2, observation_count,
  source: { source_id: `src-${station_id}`, title: "t", publisher: "p", accessed_on: "unknown", version_or_date: "unknown", license_or_terms: "unknown",
    processing_level: "test", sha256: "0".repeat(64), url: null },
  products: [{ key: "raw_value", label: "Raw", units: "m", available: true }, { key: "residual_value", label: "Residual", units: "m", available: false },
    { key: "fitted_value", label: "Fitted", units: "m", available: false }] });
const file = (path: string) => ({ path, sha256: "e".repeat(64), bytes: 1 });
const manifestInput = (): Record<string, unknown> => ({
  schema_version: "1", exporter_version: "1", bundle_id: "test-records", evidence_state: "internal_descriptive_only",
  event: { event_id: "test-event", origin_time_utc: "2001-01-01T00:00:00Z", latitude: 0, longitude: -160 },
  release: { release_id: "test-release", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy",
    allowed_uses: ["descriptive_data_quality", "preliminary_story_diagnostics"], prohibited_uses: ["physical_arrival_comparison", "modeled_minus_observed_residual",
      "community_timing_selection", "actionable_warning_time", "operational_warning", "public_story_scene_promotion"] },
  windows: [{ id: "day", label: "Test day", start_utc: "2001-01-01T00:00:00Z", end_utc_exclusive: "2001-01-02T00:00:00Z" }, { id: "source_full", label: "Full source" }],
  default_state: { selectedStationId: "a", pinnedStationId: "b", windowId: "day", productKey: "raw_value" },
  stations: [station("a", 3), station("b", 4, "dart")], assets: [file("geometry.json"), file("stations/a.json"), file("stations/b.json")],
  geometry_path: "geometry.json", input_fingerprints: [], config_sha256: "f".repeat(64),
  accounting: { source_observation_count: 7, exported_observation_count: 7, station_count: 2, rejected_observation_count: 0 },
});
const patched = (patch: Record<string, unknown>) => ({ ...manifestInput(), ...patch });
const m0 = manifestInput() as { release: object; event: object; windows: object[]; default_state: object; stations: object[]; accounting: object };

describe("records manifest against its index entry", () => {
  it("accepts any station cohort, types and windows that are structurally sound", () => {
    expect(validateManifest(manifestInput(), entry).stations.map(s => s.station_type)).toEqual(["coastal", "dart"]);
    expect(() => validateManifest(patched({ windows: [m0.windows[0]] }), entry)).not.toThrow();
    expect(() => validateManifest(patched({ default_state: { ...m0.default_state, pinnedStationId: null } }), entry)).not.toThrow();
  });
  it("refuses a manifest that disagrees with its entry, or an entry without records", () => {
    expect(() => validateManifest(patched({ bundle_id: "other" }), entry)).toThrow(/bundle/);
    for (const field of [{ event_id: "other" }, { origin_time_utc: "2001-01-01T00:00:00.000Z" }, { latitude: 0.001 }, { longitude: 200 }])
      expect(() => validateManifest(patched({ event: { ...m0.event, ...field } }), entry)).toThrow(/event identity/);
    expect(() => validateManifest(manifestInput(), { ...entry, records: null })).toThrow(/records/);
  });
  it("keeps the release restrictions literal", () => {
    expect(() => validateManifest(patched({ release: { ...m0.release, arrival_comparison_allowed: true } }), entry)).toThrow(/release/);
    expect(() => validateManifest(patched({ release: { ...m0.release, physical_arrival_records_released: 1 } }), entry)).toThrow(/release/);
    expect(() => validateManifest(patched({ release: { ...m0.release, allowed_uses: ["descriptive_data_quality"] } }), entry)).toThrow(/release/);
    expect(() => validateManifest(patched({ evidence_state: "public" }), entry)).toThrow();
  });
  it("requires unique stations in ascending id order", () => {
    expect(() => validateManifest(patched({ stations: [m0.stations[1], m0.stations[0]] }), entry)).toThrow(/station/);
    expect(() => validateManifest(patched({ stations: [m0.stations[0], m0.stations[0]] }), entry)).toThrow(/station/);
    expect(() => validateManifest(patched({ stations: [] }), entry)).toThrow(/station/);
    expect(() => validateManifest(patched({ stations: [m0.stations[0], station("b", 4, "satellite")] }), entry)).toThrow();
  });
  it("requires unique, valid half-open windows with an optional final source_full", () => {
    const day = m0.windows[0] as Record<string, unknown>, full = m0.windows[1];
    expect(() => validateManifest(patched({ windows: [day, day, full] }), entry)).toThrow(/window/);
    expect(() => validateManifest(patched({ windows: [{ ...day, end_utc_exclusive: day.start_utc }, full] }), entry)).toThrow(/interval/);
    expect(() => validateManifest(patched({ windows: [full, day] }), entry)).toThrow();
    expect(() => validateManifest(patched({ windows: [day, { ...full, start_utc: day.start_utc, end_utc_exclusive: day.end_utc_exclusive }] }), entry)).toThrow();
  });
  it("requires defaults that name listed stations, a different pin, a listed window and a product", () => {
    for (const d of [{ selectedStationId: "z" }, { pinnedStationId: "z" }, { pinnedStationId: "a" }, { windowId: "z" }, { productKey: "z" }])
      expect(() => validateManifest(patched({ default_state: { ...m0.default_state, ...d } }), entry)).toThrow(/default/);
  });
  it("requires exactly the geometry plus one chunk per station, and accounting that adds up", () => {
    expect(() => validateManifest(patched({ assets: [file("geometry.json"), file("stations/a.json")] }), entry)).toThrow(/asset/);
    expect(() => validateManifest(patched({ assets: [file("geometry.json"), file("stations/a.json"), file("stations/c.json")] }), entry)).toThrow(/asset/);
    expect(() => validateManifest(patched({ assets: [file("geometry.json"), file("stations/a.json"), file("stations/b.json"), file("stations/c.json")] }), entry))
      .toThrow(/asset/);
    for (const a of [{ station_count: 1 }, { exported_observation_count: 6, source_observation_count: 6 }, { source_observation_count: 8 }, { rejected_observation_count: 1 }])
      expect(() => validateManifest(patched({ accounting: { ...m0.accounting, ...a } }), entry)).toThrow(/accounting/);
  });
  it("takes geometry point ids from the manifest", () => {
    const m = validateManifest(manifestInput(), entry);
    const geometry = { schema_version: "1", source_crs: "EPSG:4326", display_crs: "+proj=eqearth +lon_0=-160", coordinate_order: "x,y", central_meridian: -160,
      coastline: [], bounds: [0, 0, 1, 1], points: ["test-event", "a", "b"].map(id => ({ id, x: 0, y: 0 })) };
    expect(validateGeometry(geometry, m).points).toHaveLength(3);
    expect(() => validateGeometry({ ...geometry, points: geometry.points.slice(1) }, m)).toThrow(/point/);
    expect(() => validateGeometry({ ...geometry, points: [...geometry.points.slice(1), { id: "1617760", x: 0, y: 0 }] }, m)).toThrow();
  });
});

describe("manifest pinned by the index", () => {
  const bytes = new TextEncoder().encode(JSON.stringify(manifestInput()));
  const pinned: EventEntry = { ...entry, records: { bundle_id: "test-records", manifest_bytes: bytes.byteLength,
    manifest_sha256: createHash("sha256").update(bytes).digest("hex") } };
  it("fetches <bundle_id>/manifest.json and verifies its bytes before parsing", async () => {
    let url = "";
    const m = await loadManifest(pinned, undefined, async u => { url = String(u); return new Response(bytes); });
    expect(url).toBe("/data/test-records/manifest.json"); expect(m.bundle_id).toBe("test-records");
  });
  it("refuses a manifest whose hash or byte count differs from the index pin", async () => {
    const request = async () => new Response(bytes);
    await expect(loadManifest({ ...pinned, records: { ...pinned.records!, manifest_sha256: "0".repeat(64) } }, undefined, request)).rejects.toThrow(/hash/);
    await expect(loadManifest({ ...pinned, records: { ...pinned.records!, manifest_bytes: 1 } }, undefined, request)).rejects.toThrow(/byte/);
  });
  it("does not fetch for an event without records", async () => {
    let called = false;
    await expect(loadManifest({ ...entry, records: null }, undefined, async () => { called = true; return new Response(bytes); })).rejects.toThrow(/records/);
    expect(called).toBe(false);
  });
});
