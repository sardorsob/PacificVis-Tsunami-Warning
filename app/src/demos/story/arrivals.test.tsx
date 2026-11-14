import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { EventEntry } from "../types";
import { arrivalDisplay, loadArrivals, validateArrivals, type ArrivalMark, type StoryArrivals } from "./arrivals";
import { ClockColumn } from "./ClockColumn";
import { contourColour } from "./palette";
import { Overlay } from "./StoryMap";

// The contract's synthetic, test-only file (docs/data/examples); the exporter's tests must accept it too. Compared by parsed value.
type Row = Record<string, unknown>;
type Example = Row & { release: Row; ruler: Row; places: Row[]; reports: Row[]; accounting: Record<string, number>; input_fingerprints: Row[] };
const example = () => JSON.parse(readFileSync(new URL("../../../../docs/data/examples/story-arrivals.example.json", import.meta.url), "utf8")) as Example;
const mutated = (change: (x: Example) => void) => { const x = example(); change(x); return x; };
// Example event A as a schema-1 index entry (the example index itself is schema 2).
const entry: EventEntry = { event_id: "example-event-a", label: "Example event A (test only)", origin_time_utc: "2001-01-01T00:00:00Z", latitude: 0,
  longitude: -160, magnitude: 8, magnitude_type: "mww", records: { bundle_id: "example-records-a", manifest_sha256: "a".repeat(64), manifest_bytes: 1024 },
  layers: null, arrivals: { path: "story-arrivals-v1/example-event-a.json", sha256: "c".repeat(64), bytes: 2048 } };
const rejects = (change: (x: Example) => void, why: RegExp, e = entry) => expect(() => validateArrivals(mutated(change), e)).toThrow(why);
const ex = validateArrivals(example(), entry);

describe("reported-times file (schema 1)", () => {
  it("accepts the contract's example unchanged", () => {
    expect(ex).toEqual(example());
  });
  it("keeps the release, ruler, projection and event identity literal", () => {
    rejects(x => { x.release.allowed_uses = [...(x.release.allowed_uses as string[])].reverse(); }, /release/);
    rejects(x => { x.release.arrival_comparison_allowed = true; }, /release/);
    rejects(x => { delete x.release.reported_arrival_display_allowed; }, /fields/);
    rejects(x => { x.release.extra = true; }, /fields/);
    rejects(x => { x.ruler.speed_km_per_h = 700; }, /ruler/);
    rejects(x => { x.ruler.statement = "A prediction."; }, /ruler/);
    rejects(x => { x.display_crs = "+proj=merc"; }, /projection/);
    rejects(x => { x.evidence_state = "public"; }, /schema/);
    rejects(() => undefined, /identity/, { ...entry, event_id: "example-event-b" });
    rejects(() => undefined, /identity/, { ...entry, origin_time_utc: "2001-01-01T00:00:00.000Z" });
  });
  it("applies the per-source null rules", () => {
    rejects(x => { x.reports[0].reported_utc = null; }, /NTWC/);
    rejects(x => { x.reports[0].origin_offset_seconds = 1; }, /NTWC/);
    rejects(x => { x.reports[0].source_flags = ["doubtful"]; }, /NTWC/);
    rejects(x => { x.reports[0].reported_origin = null; }, /origin/);
    rejects(x => { x.reports[3].estimate_minutes = 100; x.reports[3].estimate_utc = "2001-01-01T01:40:00Z"; }, /NCEI/);
    rejects(x => { x.reports[3].reported_text = "0310"; }, /NCEI/);
    rejects(x => { x.reports[3].gauge_kind = "unknown"; }, /NCEI/);
    rejects(x => { x.reports[1].reported_minus_ruler_minutes = 1; }, /minus-ruler/);
    rejects(x => { x.reports[0].reported_minutes = -5; x.reports[0].reported_minus_ruler_minutes = null; }, /before the origin/);
  });
  it("cross-checks places, reports, order and the input fence", () => {
    rejects(x => { [x.places[0], x.places[1]] = [x.places[1], x.places[0]]; }, /order/);
    rejects(x => { x.places[1].label = "Elsewhere"; }, /place/);
    rejects(x => { x.places[2].position_status = "reviewed"; }, /place/);
    rejects(x => { x.reports[2].site_id = "coops:9999999"; }, /place/);
    rejects(x => { x.reports[1].report_id = x.reports[0].report_id; }, /duplicate/);
    rejects(x => { x.reports.push(x.reports.splice(3, 1)[0]); x.reports.unshift(x.reports.pop()!); }, /precede/);
    rejects(x => { x.input_fingerprints[0].path = "models/fit.json"; }, /input/);
    rejects(x => { x.input_fingerprints.reverse(); }, /order/);
    rejects(() => undefined, /input/, { ...entry, records: null });   // no records bundle: its manifest is not an allowed input
    rejects(x => { x.input_fingerprints.shift(); }, /record/, { ...entry, records: null });
  });
  it("requires accounting that matches the lists", () => {
    rejects(x => { x.accounting.reports = 6; }, /accounting/);
    rejects(x => { x.accounting.places = 3; }, /accounting/);
    rejects(x => { x.accounting.ntwc_rows_with_estimate = 3; }, /accounting/);
    rejects(x => { x.accounting.ncei_records = 1; }, /accounting/);
    rejects(x => { x.accounting.ntwc_pairs_with_position = 3; }, /accounting/);
  });
  it("fetches the file the index pins, refuses other bytes, and fetches nothing for an event without one", async () => {
    const bytes = new TextEncoder().encode(JSON.stringify(example())), seen: string[] = [];
    const pinned = { ...entry, arrivals: { ...entry.arrivals!, bytes: bytes.byteLength, sha256: createHash("sha256").update(bytes).digest("hex") } };
    const request = async (u: string | URL | Request) => { seen.push(String(u)); return new Response(bytes); };
    expect(await loadArrivals(pinned, undefined, request)).toEqual(ex);
    expect(seen).toEqual(["/data/story-arrivals-v1/example-event-a.json"]);
    await expect(loadArrivals({ ...pinned, arrivals: { ...pinned.arrivals, sha256: "0".repeat(64) } }, undefined, request)).rejects.toThrow(/hash/);
    let called = false;
    expect(await loadArrivals({ ...entry, arrivals: null }, undefined, async () => { called = true; return new Response(bytes); })).toBeNull();
    expect(called).toBe(false);
  });
});

describe("reported-times marks", () => {
  const kinds = (marks: ArrivalMark[]) => marks.map(m => m.kind);
  it("draws one mark per placed time on the clock: a ring per published estimate, a dot per reported time", () => {
    const d = arrivalDisplay(ex);
    expect(kinds(d.marks)).toEqual(["estimate", "ntwc", "ntwc", "tide", "deep"]);
    expect(d.marks.map(m => m.minutes)).toEqual([120, 135, 260, 190, 62]);
    expect(d.marks[0].xy).toEqual([957998, -0]);   // the place in SVG space (y down)
    expect([d.unplaced, d.beforeOrigin, d.afterClock]).toEqual([1, 0, 0]);
  });
  it("draws only 0 ≤ minutes < 30 h, and counts what it leaves out", () => {
    const edge = validateArrivals(mutated(x => { x.reports[0].reported_minutes = 1800; x.reports[2].reported_minutes = -5; x.reports[2].reported_minus_ruler_minutes = null;
      x.reports[3].reported_minutes = 1799.999; x.reports[4].reported_minutes = 0.001; }), entry);
    const d = arrivalDisplay(edge);
    expect(kinds(d.marks)).toEqual(["estimate", "tide", "deep"]);
    expect([d.unplaced, d.beforeOrigin, d.afterClock]).toEqual([1, 1, 1]);
  });
  it("stacks several reports at one place side by side", () => {
    const shared = validateArrivals(mutated(x => { x.reports[2].site_id = "coops:0000001"; x.places.splice(3, 1); x.accounting.places = 3; }), entry);
    expect(arrivalDisplay(shared).marks.slice(0, 3).map(m => [m.kind, m.slot, m.of])).toEqual([["estimate", 0, 2], ["ntwc", 0, 2], ["ntwc", 1, 2]]);
  });
  it("draws nothing unless both display permissions are present", () => {
    for (const flag of ["reported_arrival_display_allowed", "estimate_difference_display_allowed"]) {
      const release: Row = { ...ex.release }; delete release[flag];
      expect(arrivalDisplay({ ...ex, release } as unknown as StoryArrivals).marks, flag).toEqual([]);
    }
  });
  const overlay = (t: number, marks: ArrivalMark[]) => renderToStaticMarkup(<svg><Overlay view={{ k: 1e-4, tx: 200, ty: 200 }} stations={[]} epicentre={[0, 0]}
    anchors={new Map()} t={t} aId={null} bId={null} width={800} marks={marks}/></svg>);
  const states = (html: string) => [...html.matchAll(/class="story-report story-report--(\w+)( story-report--on)?"/g)].map(m => `${m[1]}${m[2] ? " on" : ""}`);
  it("shows faint outlines until the clock reaches each mark's minutes, then lights it", () => {
    const { marks } = arrivalDisplay(ex);
    expect(states(overlay(0, marks))).toEqual(["estimate", "ntwc", "ntwc", "tide", "deep"]);
    expect(states(overlay(1.99, marks))).toEqual(["estimate", "ntwc", "ntwc", "tide", "deep on"]);
    expect(states(overlay(2, marks))).toEqual(["estimate on", "ntwc", "ntwc", "tide", "deep on"]);
    expect(states(overlay(2.25, marks))).toEqual(["estimate on", "ntwc on", "ntwc", "tide", "deep on"]);
    expect(states(overlay(30, marks))).toEqual(["estimate on", "ntwc on", "ntwc on", "tide on", "deep on"]);
  });
  it("fills a lit dot with its reported hour on the contour ramp, and never fills a ring", () => {
    const html = overlay(30, arrivalDisplay(ex).marks);
    expect(html).toContain(`fill="${contourColour(135 / 60)}"`);
    expect(html).toMatch(/<circle class="story-report story-report--estimate story-report--on"[^>]*fill="none"/);
  });
});

describe("reported-times key in the clock column", () => {
  const column = (reported: Parameters<typeof ClockColumn>[0]["reported"]) => renderToStaticMarkup(<ClockColumn t={0} originUtc="2001-01-01T00:00:00Z"
    stationName={null} counts={null} alert={null} head={false} reported={reported}>{null}</ClockColumn>);
  const key = (html: string) => { const at = html.indexOf("story-key"); return at < 0 ? "" : html.slice(at, html.indexOf("story-credits")); };
  it("names the four marks, gives the honest counts and says what reported times are not", () => {
    const html = key(column(arrivalDisplay(ex)));
    for (const label of ["NTWC published estimate", "NTWC reported time", "NCEI reported time (timed from NCEI&#x27;s own origin)", "NCEI deep-ocean reported time",
      "2 estimate–reported pairs in the NTWC table · 1 with a reviewed position · 2 NCEI reported times",
      "Reported times are what the sources reported, not validated arrivals; a difference does not say which side is off.",
      "Listed reports not drawn on the map: 1 without a place."]) expect(html).toContain(label);
    expect(html.replace("not validated arrivals", "")).not.toMatch(/arrival|measured|error|wrong|late|warning time/i);
  });
  it("says why listed reports are not drawn, only when some are not", () => {
    const edge = validateArrivals(mutated(x => { x.reports[1].site_id = "coops:0000001"; x.reports[1].reported_minus_ruler_minutes = 76.3;
      x.accounting.ntwc_pairs_with_position = 2; x.accounting.ntwc_reported_with_position = 3; x.reports[2].reported_minutes = 1800; }), entry);
    expect(key(column(arrivalDisplay(edge)))).toContain("Listed reports not drawn on the map: 1 after the 30-hour clock ends.");
    const none = validateArrivals(mutated(x => { x.reports[1].site_id = "coops:0000001"; x.reports[1].reported_minus_ruler_minutes = 76.3;
      x.accounting.ntwc_pairs_with_position = 2; x.accounting.ntwc_reported_with_position = 3; }), entry);
    expect(key(column(arrivalDisplay(none)))).not.toContain("not drawn");
  });
  it("says in one plain sentence that a rejected file is not shown, and adds nothing before a file loads", () => {
    expect(column("rejected")).toContain("<p class=\"story-legend\">The reported-times file was rejected, so no published estimates or reported times are shown.</p>");
    expect(column(null)).not.toMatch(/story-key|reported-times/);
  });
});
