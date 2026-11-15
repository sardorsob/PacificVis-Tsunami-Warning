import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { fetchHashed, fetchHashedBytes } from "./loader";
import { decodeSliceStation, loadBasemap, loadSliceManifest, loadSliceStation, parseCsv, validateSliceManifest, type SliceStation } from "./slices";
import type { EventEntry, EventsIndex } from "./types";

// A deliberate records-schema-2 unit-test bundle; never a fallback for the real bundles.
const entry: EventEntry = { event_id: "test-event", label: "Test event", origin_time_utc: "2001-01-01T00:00:00.5Z", latitude: 0, longitude: -160,
  magnitude: 8, magnitude_type: "mww", records: { bundle_id: "records-test-event-v1", manifest_sha256: "a".repeat(64), manifest_bytes: 1 }, layers: null, arrivals: null };
const station = (station_id: string, product: string, vertical_datum: string, rows: number) => ({ station_id, display_station_key: `coops:${station_id}`,
  name: `Test ${station_id}`, product, latitude: 1, longitude: 2, units: "m", vertical_datum,
  source: { source_id: `src-${station_id}`, sha256: "0".repeat(64), url: null as string | null },
  coverage_fraction: 0.5, longest_supported_minutes: 60, coverage_rule_id: "test-rule", rows });
const file = (path: string, content_encoding = "gzip") => ({ path, sha256: "e".repeat(64), bytes: 1, content_encoding });
const manifestInput = () => ({
  schema_version: "2", exporter_version: "1", bundle_id: "records-test-event-v1", evidence_state: "internal_descriptive_only",
  event: { event_id: "test-event", origin_time_utc: "2001-01-01T00:00:00.5Z", latitude: 0, longitude: -160 },
  release: { release_id: "multi-event-descriptive-v1", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy",
    allowed_uses: ["descriptive_data_quality", "preliminary_story_diagnostics"], prohibited_uses: ["physical_arrival_comparison", "modeled_minus_observed_residual",
      "community_timing_selection", "actionable_warning_time", "operational_warning", "public_story_scene_promotion"] },
  window: { id: "display", label: "6 hours before to 30 hours after the origin", start_utc: "2000-12-31T18:00:00.5Z", end_utc_exclusive: "2001-01-02T06:00:00.5Z" },
  default_station_id: "a1",
  stations: [station("a1", "one_minute_water_level", "STND", 3), station("b2", "archive_window", "unknown", 0)],
  assets: [file("geometry.json", "identity"), file("stations/a1.csv.gz"), file("stations/b2.csv.gz")],
  geometry_path: "geometry.json", input_fingerprints: [{ path: "artifacts/releases/multi-event-descriptive-v1.json", sha256: "1".repeat(64) }],
  config_sha256: "f".repeat(64), accounting: { station_count: 2, rows: 3 },
});
const m0 = manifestInput();
const patched = (patch: Record<string, unknown>) => ({ ...manifestInput(), ...patch });
const manifest = validateSliceManifest(manifestInput(), entry);
const [a1, b2] = manifest.stations;
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

describe("records schema 2 manifest", () => {
  it("accepts a sound manifest, including a station with no rows", () => {
    expect(manifest.stations.map(s => [s.station_id, s.product, s.rows])).toEqual([["a1", "one_minute_water_level", 3], ["b2", "archive_window", 0]]);
  });
  it("refuses another schema, extra fields, or a manifest that disagrees with its entry", () => {
    expect(() => validateSliceManifest(patched({ schema_version: "1" }), entry)).toThrow(/schema/);
    expect(() => validateSliceManifest(patched({ windows: [] }), entry)).toThrow(/fields/);
    expect(() => validateSliceManifest(patched({ bundle_id: "records-other-v1" }), entry)).toThrow(/bundle/);
    for (const field of [{ event_id: "other" }, { origin_time_utc: "2001-01-01T00:00:00.500Z" }, { latitude: 0.001 }])
      expect(() => validateSliceManifest(patched({ event: { ...m0.event, ...field } }), entry)).toThrow(/event identity/);
    expect(() => validateSliceManifest(manifestInput(), { ...entry, records: null })).toThrow(/records/);
  });
  it("keeps the schema-1 release literals and pins the multi-event release id", () => {
    for (const change of [{ release_id: "test-release" }, { arrival_comparison_allowed: true }, { physical_arrival_records_released: 1 }, { prohibited_uses: [] }])
      expect(() => validateSliceManifest(patched({ release: { ...m0.release, ...change } }), entry)).toThrow(/release/);
  });
  it("requires the display window from origin − 6 h to origin + 30 h, compared as instants", () => {
    const w = m0.window;
    for (const change of [{ end_utc_exclusive: "2001-01-02T06:01:00.5Z" }, { start_utc: "2000-12-31T18:00:00Z" }, { id: "day" }, { label: "Display" }])
      expect(() => validateSliceManifest(patched({ window: { ...w, ...change } }), entry)).toThrow(/window/);
    expect(() => validateSliceManifest(patched({ window: { ...w, end_utc_exclusive: "2001-01-02T06:00:00.500Z" } }), entry)).not.toThrow();
  });
  it("requires unique, ascending, safe station ids with their coops display key", () => {
    const [a, b] = m0.stations;
    expect(() => validateSliceManifest(patched({ stations: [b, a] }), entry)).toThrow(/station order/);
    expect(() => validateSliceManifest(patched({ stations: [a, a] }), entry)).toThrow(/station order/);
    for (const display_station_key of ["coops:b2", "coops-a1", "a1"])
      expect(() => validateSliceManifest(patched({ stations: [{ ...a, display_station_key }, b] }), entry)).toThrow(/display station key/);
  });
  it("refuses station fields outside their rules", () => {
    const [a, b] = m0.stations;
    for (const bad of [{ station_id: "a/1", display_station_key: "coops:a/1" }, { product: "six_minute" }, { latitude: 91 }, { longitude: Number.NaN }, { units: "ft" },
      { vertical_datum: "Unknown" }, { coverage_fraction: 1.5 }, { coverage_fraction: -0.1 }, { longest_supported_minutes: -1 }, { coverage_rule_id: "" },
      { rows: 1.5 }, { name: "" }, { source: { ...a.source, url: "https://user:pass@example.org/x" } }, { source: { ...a.source, sha256: "x" } }, { extra: 1 }])
      expect(() => validateSliceManifest(patched({ stations: [{ ...a, ...bad }, b] }), entry), JSON.stringify(bad)).toThrow();
    expect(() => validateSliceManifest(patched({ stations: [{ ...a, source: { ...a.source, url: "https://example.org/a&b" } }, b] }), entry)).not.toThrow();
  });
  it("requires a listed default station", () => {
    expect(() => validateSliceManifest(patched({ default_station_id: "zz" }), entry)).toThrow(/default/);
    expect(() => validateSliceManifest(patched({ default_station_id: "b2" }), entry)).not.toThrow();
  });
  it("requires geometry first, then exactly one gzip file per station in path order", () => {
    const [g, a, b] = m0.assets;
    for (const assets of [[g, a], [g, b, a], [a, g, b], [g, a, b, file("stations/c3.csv.gz")], [g, a, { ...b, content_encoding: "identity" }],
      [{ ...g, content_encoding: "gzip" }, a, b], [g, a, file("stations/b2.json")]])
      expect(() => validateSliceManifest(patched({ assets }), entry)).toThrow(/asset/);
    expect(() => validateSliceManifest(patched({ assets: [g, a, { ...b, bytes: 0 }] }), entry)).toThrow();
    expect(() => validateSliceManifest(patched({ assets: [g, a, { ...b, extra: 1 }] }), entry)).toThrow(/fields/);
    expect(() => validateSliceManifest(patched({ geometry_path: "stations/a1.csv.gz" }), entry)).toThrow(/geometry/);
  });
  it("orders station files by path, not by station id ('-' sorts before '.')", () => {
    const stations = [station("a", "water_level", "STND", 1), station("a-b", "water_level", "STND", 2)];
    const ok = { stations, default_station_id: "a", accounting: { station_count: 2, rows: 3 } };
    expect(() => validateSliceManifest(patched({ ...ok, assets: [file("geometry.json", "identity"), file("stations/a-b.csv.gz"), file("stations/a.csv.gz")] }), entry)).not.toThrow();
    expect(() => validateSliceManifest(patched({ ...ok, assets: [file("geometry.json", "identity"), file("stations/a.csv.gz"), file("stations/a-b.csv.gz")] }), entry)).toThrow(/asset/);
  });
  it("requires accounting that adds up and safe fingerprints", () => {
    for (const accounting of [{ station_count: 1, rows: 3 }, { station_count: 2, rows: 4 }, { station_count: 2 }])
      expect(() => validateSliceManifest(patched({ accounting }), entry)).toThrow(/accounting|fields/);
    expect(() => validateSliceManifest(patched({ input_fingerprints: [{ path: "../x", sha256: "1".repeat(64) }] }), entry)).toThrow(/fingerprint/);
    expect(() => validateSliceManifest(patched({ config_sha256: "x" }), entry)).toThrow(/SHA256/);
  });
});

describe("RFC 4180 parsing", () => {
  it("reads quoted fields with commas, doubled quotes and line breaks, with or without a final line break", () => {
    expect(parseCsv('a,"b,c","d ""e"""\n')).toEqual([["a", "b,c", 'd "e"']]);
    expect(parseCsv("a,b\r\nc,")).toEqual([["a", "b"], ["c", ""]]);
    expect(parseCsv('"x\ny",""\n,\n')).toEqual([["x\ny", ""], ["", ""]]);
    expect(parseCsv("")).toEqual([]);
  });
  it("refuses a stray or unterminated quote and a bare carriage return", () => {
    for (const bad of ['a"b,c\n', '"ab"c\n', '"abc\n', "a\rb\n"]) expect(() => parseCsv(bad), JSON.stringify(bad)).toThrow(/CSV/);
  });
});

const HEADER = "event_id,source_id,station_key,sensor,timestamp_utc,numeric_value,value_state,timestamp_state,duplicate_timestamp,units,vertical_datum,qc_state,qc_json";
const BASE = { event_id: "test-event", source_id: "src-a1", station_key: "coops-a1", sensor: "unknown", timestamp_utc: "2001-01-01T00:00:00Z", numeric_value: "1.5",
  value_state: "finite_numeric", timestamp_state: "reported_utc", duplicate_timestamp: "False", units: "m", vertical_datum: "STND", qc_state: "not_provided", qc_json: "{}" };
type Fields = Partial<typeof BASE>;
const line = (f: Fields = {}) => Object.values({ ...BASE, ...f }).join(",");
const gz = (text: string) => new Uint8Array(gzipSync(text)).buffer;
const at = (minute: number) => new Date(Date.UTC(2001, 0, 1, 0, minute)).toISOString().replace(".000Z", "Z");
const ms = (minute: number) => Date.UTC(2001, 0, 1, 0, minute);
/** Decodes the rows against the station with its `rows` set to match. */
const decode = (rows: Fields[], s: SliceStation = a1, header = HEADER) =>
  decodeSliceStation(gz(`${[header, ...rows.map(line)].join("\n")}\n`), { ...s, rows: rows.length }, manifest);
const series = (r: { segments: { t: number }[][] }) => r.segments.map(s => s.map(p => p.t));

describe("records schema 2 station file", () => {
  it("decodes rows in file order, with quoted QC JSON, into drawing-ready segments", async () => {
    const qc = '"{""f"":""0,0,0,0"",""q"":""v"",""s"":""0.021""}"';
    const r = await decode([{ timestamp_utc: at(0) }, { timestamp_utc: at(1), numeric_value: "-0.651", qc_state: "provided", qc_json: qc }, { timestamp_utc: at(2), numeric_value: "1e-05" }]);
    expect(r.station_id).toBe("a1");
    expect(r.rows[1]).toEqual({ ...BASE, timestamp_utc: at(1), numeric_value: -0.651, duplicate_timestamp: false, qc_state: "provided", qc_json: { f: "0,0,0,0", q: "v", s: "0.021" } });
    expect(r.segments).toEqual([[{ t: ms(0), v: 1.5 }, { t: ms(1), v: -0.651 }, { t: ms(2), v: 0.00001 }]]);
    expect(r.counts).toEqual({ rows: 3, blank: 0, duplicates_dropped: 0, outside_window: 0, backward_steps: 0 });
  });
  it("decodes a header-only file with rows 0 to an empty record", async () => {
    expect(await decode([], b2)).toEqual({ station_id: "b2", rows: [], segments: [], counts: { rows: 0, blank: 0, duplicates_dropped: 0, outside_window: 0, backward_steps: 0 } });
  });
  it("ends a segment at a blank row and never parses its value", async () => {
    const r = await decode([{ timestamp_utc: at(0) }, { timestamp_utc: at(1), value_state: "blank", numeric_value: "unknown" }, { timestamp_utc: at(2) },
      { timestamp_utc: at(3), value_state: "blank", numeric_value: "unknown" }]);
    expect(series(r)).toEqual([[ms(0)], [ms(2)]]);
    expect(r.rows[1].numeric_value).toBeNull(); expect(r.counts.blank).toBe(2);
  });
  it("draws a duplicate_timestamp row only when no earlier row in the file has its timestamp", async () => {
    const r = await decode([{ timestamp_utc: at(0), duplicate_timestamp: "True" }, { timestamp_utc: at(1) }, { timestamp_utc: at(0), duplicate_timestamp: "True" },
      { timestamp_utc: at(2), duplicate_timestamp: "True", value_state: "blank", numeric_value: "unknown" }, { timestamp_utc: at(2), duplicate_timestamp: "True" },
      { timestamp_utc: at(3) }]);
    expect(series(r)).toEqual([[ms(0), ms(1)], [ms(3)]]);
    expect(r.counts).toMatchObject({ duplicates_dropped: 2, blank: 1, backward_steps: 0 });
    expect(r.rows.map(x => x.duplicate_timestamp)).toEqual([true, false, true, true, true, false]);
  });
  it("ends a segment at a backward time step, counts it and still draws the row, in file order", async () => {
    const r = await decode([{ timestamp_utc: at(0) }, { timestamp_utc: at(5) }, { timestamp_utc: at(2) }, { timestamp_utc: at(3) }]);
    expect(series(r)).toEqual([[ms(0), ms(5)], [ms(2), ms(3)]]);
    expect(r.counts.backward_steps).toBe(1);
  });
  it("does not draw rows outside the half-open display window", async () => {
    const r = await decode([{ timestamp_utc: "2000-12-31T18:00:00Z" }, { timestamp_utc: "2000-12-31T18:00:00.5Z" }, { timestamp_utc: "2001-01-02T06:00:00Z" },
      { timestamp_utc: "2001-01-02T06:00:00.5Z" }]);
    expect(series(r)).toEqual([[Date.UTC(2000, 11, 31, 18, 0, 0, 500), Date.UTC(2001, 0, 2, 6)]]);
    expect(r.counts.outside_window).toBe(2); expect(r.rows).toHaveLength(4);
  });
  it("shows QC without filtering: a flagged zero stays zero", async () => {
    const r = await decode([{ numeric_value: "0", qc_state: "provided", qc_json: '"{""q"":""flagged""}"' }]);
    expect(r.segments).toEqual([[{ t: ms(0), v: 0 }]]); expect(r.rows[0].qc_json).toEqual({ q: "flagged" });
  });
  it("refuses a file without the gzip magic bytes, or one that is not UTF-8", async () => {
    await expect(decodeSliceStation(new TextEncoder().encode(`${HEADER}\n`).buffer, b2, manifest)).rejects.toThrow(/gzip/);
    await expect(decodeSliceStation(new ArrayBuffer(0), b2, manifest)).rejects.toThrow(/gzip/);
    await expect(decodeSliceStation(new Uint8Array(gzipSync(Buffer.from([0xff]))).buffer, b2, manifest)).rejects.toThrow();
  });
  it("refuses a different, reordered or extended header and rows of another width", async () => {
    const cols = HEADER.split(",");
    for (const header of [cols.slice(1).join(","), [cols[1], cols[0], ...cols.slice(2)].join(","), `${HEADER},extra`, HEADER.replace("qc_json", "qc")])
      await expect(decode([], b2, header)).rejects.toThrow(/columns/);
    await expect(decodeSliceStation(gz(`${HEADER}\n${line()},x\n`), { ...a1, rows: 1 }, manifest)).rejects.toThrow(/width/);
  });
  it("refuses a row count that differs from the manifest", async () => {
    await expect(decodeSliceStation(gz(`${HEADER}\n${line()}\n`), { ...a1, rows: 2 }, manifest)).rejects.toThrow(/row count/);
    await expect(decodeSliceStation(gz(`${HEADER}\n`), { ...a1, rows: 1 }, manifest)).rejects.toThrow(/row count/);
  });
  it("ties numeric_value to value_state: blank holds the text unknown, finite_numeric a strict finite number", async () => {
    await expect(decode([{ value_state: "blank", numeric_value: "1.5" }])).rejects.toThrow(/value/);
    for (const numeric_value of ["unknown", "NaN", "", "Infinity", "1e", "1e999", " 1", "+1", ".5", "1.", "0x10"])
      await expect(decode([{ numeric_value }]), numeric_value).rejects.toThrow(/value/);
    await expect(decode([{ value_state: "missing" }])).rejects.toThrow();
  });
  it("refuses unknown states, flags and timestamps", async () => {
    for (const bad of [{ timestamp_state: "estimated" }, { duplicate_timestamp: "true" }, { qc_state: "flagged" }, { sensor: "" },
      { timestamp_utc: "2001-01-01 00:00:00" }, { timestamp_utc: "2001-02-30T00:00:00Z" }])
      await expect(decode([bad]), JSON.stringify(bad)).rejects.toThrow();
    for (const timestamp_state of ["epoch_calendar_agree", "epoch_calendar_minute_agree", "header_day_end_boundary"])
      expect((await decode([{ timestamp_state }])).segments).toHaveLength(1);
  });
  it("refuses a row from another event or source", async () => {
    await expect(decode([{ event_id: "other-event" }])).rejects.toThrow(/event/);
    await expect(decode([{ source_id: "src-b2" }])).rejects.toThrow(/source/);
  });
  it("requires coops-<station_id> for the CO-OPS products and an NTWC code for archive windows", async () => {
    for (const product of ["one_minute_water_level", "water_level"] as const) {
      expect((await decode([{ station_key: "coops-a1" }], { ...a1, product })).rows).toHaveLength(1);
      for (const station_key of ["coops-b2", "coops:a1", "ntwc-fpnt"]) await expect(decode([{ station_key }], { ...a1, product }), station_key).rejects.toThrow(/station key/);
    }
    const archive = { ...a1, product: "archive_window" as const };
    expect((await decode([{ station_key: "ntwc-fpnt" }], archive)).rows).toHaveLength(1);
    for (const station_key of ["coops-a1", "ntwc-", "ntwc-FPNT", "ntwc-fp_nt"]) await expect(decode([{ station_key }], archive), station_key).rejects.toThrow(/station key/);
  });
  it("requires the station's units and datum, mapping only the CSV's Unknown to the manifest's unknown", async () => {
    for (const vertical_datum of ["MLLW", "Unknown"]) await expect(decode([{ vertical_datum }])).rejects.toThrow(/datum/);
    await expect(decode([{ units: "ft" }])).rejects.toThrow(/units/);
    const unknown = { ...a1, vertical_datum: "unknown" as const };
    expect((await decode([{ vertical_datum: "Unknown" }], unknown)).rows[0].vertical_datum).toBe("Unknown");
    await expect(decode([{ vertical_datum: "STND" }], unknown)).rejects.toThrow(/datum/);
    expect((await decode([{ vertical_datum: "MLLW" }], { ...a1, vertical_datum: "MLLW" })).rows).toHaveLength(1);
  });
  it("requires qc_json to be a JSON object", async () => {
    for (const qc_json of ["[]", "1", '"""x"""', "null", "{", '"{""a"":1}x"']) await expect(decode([{ qc_json }]), qc_json).rejects.toThrow(/object|CSV/);
  });
});

describe("pinned bytes", () => {
  const bytes = new TextEncoder().encode('{"a":1}'), request = async () => new Response(bytes);
  it("returns the exact bytes only when the count and SHA-256 match the pin; fetchHashed parses them", async () => {
    expect(new Uint8Array(await fetchHashedBytes("/x", bytes.byteLength, sha(bytes), undefined, request))).toEqual(bytes);
    await expect(fetchHashedBytes("/x", bytes.byteLength + 1, sha(bytes), undefined, request)).rejects.toThrow(/byte count/);
    await expect(fetchHashedBytes("/x", bytes.byteLength, "0".repeat(64), undefined, request)).rejects.toThrow(/hash/);
    await expect(fetchHashedBytes("/x", 1, sha(bytes), undefined, async () => new Response("", { status: 404 }))).rejects.toThrow(/HTTP 404/);
    expect(await fetchHashed("/x", bytes.byteLength, sha(bytes), undefined, request)).toEqual({ a: 1 });
  });
});

describe("loading a schema-2 bundle", () => {
  const csv = new Uint8Array(gz(`${HEADER}\n${line()}\n`));
  const mBytes = new TextEncoder().encode(JSON.stringify({ ...manifestInput(), stations: [station("a1", "one_minute_water_level", "STND", 1)],
    assets: [file("geometry.json", "identity"), { path: "stations/a1.csv.gz", sha256: sha(csv), bytes: csv.byteLength, content_encoding: "gzip" }],
    accounting: { station_count: 1, rows: 1 } }));
  const pinned: EventEntry = { ...entry, records: { bundle_id: "records-test-event-v1", manifest_bytes: mBytes.byteLength, manifest_sha256: sha(mBytes) } };
  it("fetches the manifest the index pins, then a station file by its asset's bytes and hash", async () => {
    const urls: string[] = [];
    const request = async (u: string | URL | Request) => { urls.push(String(u)); return new Response(String(u).endsWith(".csv.gz") ? csv : mBytes); };
    const m = await loadSliceManifest(pinned, undefined, request);
    expect((await loadSliceStation(m, "a1", undefined, request)).segments).toEqual([[{ t: ms(0), v: 1.5 }]]);
    expect(urls).toEqual(["/data/records-test-event-v1/manifest.json", "/data/records-test-event-v1/stations/a1.csv.gz"]);
    await expect(loadSliceStation(m, "zz", undefined, request)).rejects.toThrow(/station/);
    await expect(loadSliceStation({ ...m, assets: [m.assets[0], { ...m.assets[1], sha256: "0".repeat(64) }] }, "a1", undefined, request)).rejects.toThrow(/hash/);
    await expect(loadSliceManifest({ ...pinned, records: { ...pinned.records!, manifest_bytes: 1 } }, undefined, request)).rejects.toThrow(/byte count/);
  });
  it("does not fetch for an event without records", async () => {
    let called = false;
    await expect(loadSliceManifest({ ...entry, records: null }, undefined, async () => { called = true; return new Response(mBytes); })).rejects.toThrow(/records/);
    expect(called).toBe(false);
  });
  it("loads the basemap the index pins, in the layers coastline format with the 1:110m source id", async () => {
    const coast = (source_id: string, closed = [false]) => new TextEncoder().encode(JSON.stringify({ schema_version: "1", source_id, parts: [[[0, 10], [5, 20]]], closed }));
    const index = (bytes: Uint8Array): EventsIndex => ({ schema_version: "2", evidence_state: "internal_descriptive_only", default_event_id: "test-event", events: [entry],
      basemap: { path: "basemap-v1/coastline.json", bytes: bytes.byteLength, sha256: sha(bytes) } });
    const good = coast("natural-earth-110m-coastline"); let url = "";
    expect(await loadBasemap(index(good), undefined, async u => { url = String(u); return new Response(good); })).toEqual({ parts: [[[0, -10], [5, -20]]], closed: [false] });
    expect(url).toBe("/data/basemap-v1/coastline.json");
    for (const bad of [coast("natural-earth-50m-coastline"), coast("natural-earth-110m-coastline", [])])
      await expect(loadBasemap(index(bad), undefined, async () => new Response(bad))).rejects.toThrow(/coastline/);
    await expect(loadBasemap({ ...index(good), basemap: undefined }, undefined, async () => new Response(good))).rejects.toThrow(/basemap/);
  });
});
