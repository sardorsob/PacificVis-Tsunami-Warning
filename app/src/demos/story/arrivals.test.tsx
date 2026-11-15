import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { EventEntry } from "../types";
import { arrivalDisplay, loadArrivals, validateArrivals, type ArrivalMark, type StoryArrivals } from "./arrivals";
import { Ladder } from "./ArrivalsView";
import { ClockColumn } from "./ClockColumn";
import { contourColour } from "./palette";
import { Overlay } from "./StoryMap";
import { ThreeClocks } from "./ThreeClocks";

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
  const column = (reported: Parameters<typeof ClockColumn>[0]["reported"]) => renderToStaticMarkup(<ClockColumn t={0} entry={{ event_id: "e", label: "Example Bay, Example", origin_time_utc: "2001-01-01T00:00:00Z",
    latitude: 0, longitude: 0, magnitude: 8, magnitude_type: "mww", records: null, layers: { bundle_id: "l", manifest_sha256: "0".repeat(64), manifest_bytes: 1 }, arrivals: null }}
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

// Words the reported-times displays never use: a reported time is not a validated arrival, and a difference is not an error.
const BANNED = /arrival|measured|error|wrong|late|warning time/i;
const harbor = { id: "0000001", name: "Test harbor" }, bay = { id: "0000002", name: "Test bay" }, unlinked = { id: "1617760", name: "Test unlinked" };
type Stations = Parameters<typeof ThreeClocks>[0]["stations"];
const clocks = (a: StoryArrivals, stations: Stations, t = 3) => renderToStaticMarkup(<ThreeClocks arrivals={a} t={t} stations={stations}/>);
const lanes = (html: string) => (html.match(/class="story-lane"/g) ?? []).length;
const count = (html: string, cls: string) => (html.match(new RegExp(`class="${cls}"`, "g")) ?? []).length;
/** Report 0 (Example Harbor, linked to 0000001) with other times; the exporter's difference and ruler fields follow the rules. */
const harborAt = (reported: number | null, estimate: number | null, diff: number | null) => validateArrivals(mutated(x => {
  const r = x.reports[0], utc = (m: number) => new Date(Date.UTC(2001, 0, 1) + m * 60_000).toISOString().replace(".000", "");
  Object.assign(r, { reported_minutes: reported, reported_origin: reported === null ? null : "usgs_reviewed", reported_utc: reported === null ? null : utc(reported),
    estimate_minutes: estimate,
    estimate_utc: estimate === null ? null : utc(estimate), reported_minus_estimate_minutes: diff,
    reported_minus_ruler_minutes: reported === null || reported < 0 ? null : 1 });
  if (reported === null) { x.accounting.ntwc_rows_with_reported_time--; x.accounting.ntwc_reported_with_position--; }
}), entry);

describe("three-clocks strip (record arm)", () => {
  it("draws each linked report on the 0–30 h axis with the clock line, and gives the difference in words", () => {
    const html = clocks(ex, [harbor]);
    expect(html).toContain('aria-label="Reported times linked to Test harbor"');
    expect(html).toContain("1,113.2 km in a straight line from the epicentre");
    expect(html).toContain("NTWC: reported 15 min after the published estimate · this station&#x27;s record.");   // Example Harbor's record link is same_provider_id
    expect(html).toContain('style="--clock:10%"');                                   // t = 3 h on the 0–30 h scale
    expect(html).toMatch(/<svg x="6.666[0-9]*%" y="7" overflow="visible"><path class="story-report story-report--estimate story-report--on" d="M-5 -4H5L0 4Z"/);
    expect(html).toMatch(/<svg x="7.5%" y="7" overflow="visible"><circle class="story-report story-report--ntwc story-report--on"/);
    expect([lanes(html), count(html, "story-lane__join"), count(html, "story-lane__ticks")]).toEqual([1, 1, 1]);
    expect(html.replace(/story-[a-z_-]+/g, "")).not.toMatch(BANNED);
  });
  it("words a report in the same minute, and one before the published estimate", () => {
    expect(clocks(harborAt(120, 120, 0), [harbor])).toContain("NTWC: reported in the same minute as the published estimate · this station&#x27;s record.");
    expect(clocks(harborAt(113, 120, -7), [harbor])).toContain("NTWC: reported 7 min before the published estimate · this station&#x27;s record.");
    expect(clocks(harborAt(null, 120, null), [harbor])).toContain("NTWC: published estimate 02:00 UTC · this station&#x27;s record.");
  });
  it("prints the fixed clause for each record link: within 1 km, and the same provider ID, each only for its own report", () => {
    expect(clocks(ex, [bay])).toContain("Reported by NCEI: 3 h 10 min after NCEI&#x27;s origin · "
      + "record from a station within 1 km, not verified as the same instrument.");
    expect(clocks(ex, [harbor])).not.toContain("within 1 km");
    expect(clocks(ex, [bay])).not.toContain("this station&#x27;s record");
  });
  it("says in one quiet line that no reported times are linked, with no axis", () => {
    const html = clocks(ex, [unlinked]);
    expect(html).toContain("<p>No reported times are linked to this station.</p>");
    expect([lanes(html), count(html, "story-lane__ticks")]).toEqual([0, 0]);
    expect(html).not.toContain("km in a straight line from the epicentre");
  });
  it("does not draw a time before the origin or after 30 h, and says why", () => {
    const late = clocks(harborAt(1800, 120, 1680), [harbor]);
    expect(late).toContain("Reported after the 30-hour clock ends.");
    expect([count(late, "story-report story-report--estimate story-report--on"), count(late, "story-report story-report--ntwc story-report--on"),
      count(late, "story-lane__join")]).toEqual([1, 0, 0]);
    const early = clocks(harborAt(135, -5, null), [harbor]);
    expect(early).toContain("The source gives a time before the earthquake origin. The project does not correct dates.");
    expect(early).toContain("NTWC: published estimate 23:55 UTC · reported 02:15 UTC · this station&#x27;s record.");
    expect([count(early, "story-report story-report--estimate story-report--on"), count(early, "story-lane__join")]).toEqual([0, 0]);
  });
  it("stacks B under A on one axis in Compare, each named with its distance (omitted when nothing is linked)", () => {
    const html = clocks(ex, [{ ...harbor, tag: "A" }, { ...bay, tag: "B" }]);
    const a = html.indexOf('<span class="story-tag story-tag--a">A</span><b>Test harbor</b> · 1,113.2 km in a straight line from the epicentre');
    const b = html.indexOf('<span class="story-tag story-tag--b">B</span><b>Test bay</b> · 1,565.1 km in a straight line from the epicentre');
    expect(a).toBeGreaterThan(-1); expect(b).toBeGreaterThan(a);
    expect(count(html, "story-lane__ticks")).toBe(1);
    expect(clocks(ex, [{ ...harbor, tag: "A" }, { ...unlinked, tag: "B" }])).toContain("<b>Test unlinked</b></p><p>No reported times are linked to this station.</p>");
  });
  it("never joins or differences an NCEI report and an NTWC report at one station", () => {
    const both = validateArrivals(mutated(x => { (x.places[1].record as Row).station_id = "0000001"; }), entry), html = clocks(both, [harbor]);
    expect([lanes(html), count(html, "story-lane__join")]).toEqual([2, 1]);
    const ncei = html.slice(html.indexOf("Reported by NCEI"));
    expect(ncei.slice(0, ncei.indexOf("</p>"))).not.toMatch(/estimate|differ|after the|before the/);
  });
});

type NodeProps = { children?: ReactNode; onClick?: () => void; "aria-pressed"?: boolean };
/** Walks a hook-free component's element tree (no DOM needed). */
function nodes(node: ReactNode): ReactElement<NodeProps>[] {
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (!isValidElement<NodeProps>(node)) return [];
  const own = typeof node.type === "function" ? nodes((node.type as (p: unknown) => ReactNode)(node.props)) : [];
  return [node, ...own, ...nodes(node.props.children)];
}

describe("reported-times ladder (the Reported times view)", () => {
  const ladder = (a: StoryArrivals, sort: "time" | "distance" = "time") => renderToStaticMarkup(<Ladder arrivals={a} sort={sort} onSort={() => undefined}/>);
  const section = (html: string, which: "ntwc" | "ncei") => {
    const n = html.indexOf('aria-label="NTWC table'), c = html.indexOf('aria-label="Reported by NCEI');
    return which === "ntwc" ? html.slice(n, c) : html.slice(c);
  };
  const places = (html: string) => [...html.matchAll(/<li class="ladder-row"><p><b>([^<]+)<\/b>/g)].map(m => m[1]);
  it("lists NTWC rows and, in their own section below, NCEI rows, by reported time", () => {
    const html = ladder(ex);
    expect(places(section(html, "ntwc"))).toEqual(["Example Harbor", "Example Unplaced Town", "Example Point"]);
    expect(places(section(html, "ncei"))).toEqual(["Example deep-ocean gauge", "Example Bay"]);
    expect(html).toContain("NTWC table · published estimates and reported times · 3 rows");
    expect(html).toContain("Reported by NCEI, timed from NCEI&#x27;s own origin · 2 rows");
  });
  it("sorts by distance, with rows of unknown distance last", () => {
    expect(places(section(ladder(ex, "distance"), "ntwc"))).toEqual(["Example Harbor", "Example Point", "Example Unplaced Town"]);
    const far = validateArrivals(mutated(x => { x.places[2].distance_km = 9999; }), entry);
    expect(places(section(ladder(far, "distance"), "ncei"))).toEqual(["Example Bay", "Example deep-ocean gauge"]);
    expect(places(section(ladder(far, "time"), "ncei"))).toEqual(["Example deep-ocean gauge", "Example Bay"]);
  });
  it("states the honest counts at the top", () => {
    expect(ladder(ex)).toContain('<p class="ladder-counts">2 estimate–reported pairs in the NTWC table · 1 with a reviewed position · '
      + "1 NTWC report without a place · 2 NCEI reported times</p>");
  });
  it("gives each row its place, distance, times in words, raw source text and source id", () => {
    const html = ladder(ex), row = (place: string) => { const at = html.indexOf(`<b>${place}</b>`); return html.slice(at, html.indexOf("</li>", at)); };
    for (const text of ["1,113.2 km in a straight line from the epicentre", "published estimate 02:00 UTC · reported 02:15 UTC · reported 15 min after the published estimate",
      "Source cells: estimate “0200” · reported “0215” · example-ntwc-source"]) expect(row("Example Harbor")).toContain(text);
    expect(row("Example Unplaced Town")).toContain("reported 10 min before the published estimate");
    expect(row("Example Unplaced Town")).not.toContain("km in a straight line from the epicentre");
    expect(row("Example Point")).toContain("reported 04:20 UTC</p>");
    for (const text of ["784 km in a straight line from the epicentre", "reported 1 h 2 min after NCEI&#x27;s origin · deep-ocean gauge",
      "Source: example-ncei-source · NCEI marks it doubtful"]) expect(row("Example deep-ocean gauge")).toContain(text);
    expect(row("Example Bay")).toContain("reported 3 h 10 min after NCEI&#x27;s origin · tide gauge");
    expect(html.replace(/story-[a-z_-]+/g, "")).not.toMatch(BANNED);
  });
  it("keeps rows before the origin or after 30 h in the table, with the contract's note and no mark for that time", () => {
    const edge = validateArrivals(mutated(x => { x.reports[0].reported_minutes = 1800; x.reports[2].reported_minutes = -5; x.reports[2].reported_minus_ruler_minutes = null; }), entry);
    const html = ladder(edge), ntwc = section(html, "ntwc");
    expect(html).toContain("Listed rows not drawn on the ladder: 1 before the earthquake origin (the project does not correct dates) · 1 after the 30-hour clock ends.");
    expect(ntwc).toContain('<p class="ladder-row__note">Reported after the 30-hour clock ends.</p>');
    expect(ntwc).toContain('<p class="ladder-row__note">The source gives a time before the earthquake origin. The project does not correct dates.</p>');
    expect(count(ntwc, "ladder-row")).toBe(3);
    expect(count(ntwc, "story-report story-report--ntwc story-report--on")).toBe(1);     // only the unplaced row's reported time is on the clock
    expect(ladder(ex)).not.toContain("not drawn");
  });
  it("never joins an NCEI row to an estimate", () => {
    const ncei = section(ladder(ex), "ncei"), rows = ncei.slice(ncei.indexOf('<ol class="ladder-rows">'));
    expect([count(ncei, "story-lane__join"), count(ncei, "story-report story-report--estimate story-report--on")]).toEqual([0, 0]);
    expect(rows).not.toMatch(/published estimate|differ|after the|before the/);
  });
  it("offers a keyboard-reachable sort control that changes only to the other order", () => {
    const onSort = vi.fn(), tree = nodes(Ladder({ arrivals: ex, sort: "time", onSort })), buttons = tree.filter(n => n.type === "button");
    expect(buttons.map(b => [b.props.children, b.props["aria-pressed"]])).toEqual([["Reported time", true], ["Distance", false]]);
    buttons[0].props.onClick!(); expect(onSort).not.toHaveBeenCalled();
    buttons[1].props.onClick!(); expect(onSort).toHaveBeenCalledExactlyOnceWith("distance");
  });
});
