import { readFileSync } from "node:fs";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventsDemo, LoadedDemo } from "../DemoApp";
import { eventsSearch, parseEventsState, parseState, routeSearch, serializeState, stepSearch } from "../state";
import type { DemoManifest, EventCounts, EventEntry, EventsIndex } from "../types";
import type { StoryArrivals } from "./arrivals";
import { ArrivalsView } from "./ArrivalsView";
import { EventsView, type EventsViewProps } from "./EventsView";
import { reduce, stepFocus, type NavContext, type NavEvent, type StoryNav } from "./nav";
import { STEPS, STORY_EVENT_ID, stepBody, validateSteps, type StepData } from "./steps";
import { StepPanel, StoryView, type StoryViewProps } from "./StoryView";
import { parseStoryParams } from "./url";

// Records the props DemoApp's writers hand the views, and still renders the real views.
const seen = vi.hoisted(() => ({ story: null as unknown, times: null as unknown, events: null as unknown }));
vi.mock("./StoryView", async importOriginal => {
  const m = await importOriginal<typeof import("./StoryView")>();
  return { ...m, StoryView: (p: StoryViewProps) => { seen.story = p; return m.StoryView(p); } };
});
vi.mock("./ArrivalsView", async importOriginal => {
  const m = await importOriginal<typeof import("./ArrivalsView")>();
  return { ...m, ArrivalsView: (p: StoryViewProps) => { seen.times = p; return m.ArrivalsView(p); } };
});
vi.mock("./EventsView", async importOriginal => {
  const m = await importOriginal<typeof import("./EventsView")>();
  return { ...m, EventsView: (p: EventsViewProps) => { seen.events = p; return m.EventsView(p); } };
});

// Typed test-only inputs. The contract's synthetic example, re-linked to the story's stations: Example Bay (NCEI, within 1 km) to Hilo and the
// deep-ocean gauge (NCEI) to Saipan, with the times and distances the copy's parentheses give.
const example = JSON.parse(readFileSync(new URL("../../../../docs/data/examples/story-arrivals.example.json", import.meta.url), "utf8")) as StoryArrivals;
const relinked = (hiloLink: "within_1km" | "same_provider_id" = "within_1km"): StoryArrivals => ({ ...example,
  places: example.places.map(p => p.site_id.startsWith("ncei-native:a") ? { ...p, distance_km: 6309.6, record: { station_id: "1617760", link: hiloLink } }
    : p.site_id.startsWith("ncei-native:b") ? { ...p, distance_km: 2577.7, record: { station_id: "saip", link: "within_1km" } } : p),
  reports: example.reports.map(r => r.report_id === "example-ncei-0001:1" ? { ...r, reported_minutes: 476 }
    : r.report_id === "example-ncei-0001:2" ? { ...r, reported_minutes: 197 } : r) });
// Tōhoku's accounting as the copy's parentheses give it; Illapel's Hilo row (NTWC, this station's record) with the exporter's difference.
const tohokuFile: StoryArrivals = { ...example, accounting: { ...example.accounting, ntwc_rows_with_both_times: 92, ntwc_pairs_with_position: 8, ncei_reported_durations: 273 } };
const illapelFile: StoryArrivals = { ...example,
  places: example.places.map(p => p.site_id === "coops:0000001" ? { ...p, record: { station_id: "1617760", link: "same_provider_id" } } : p),
  reports: example.reports.map(r => r.report_id === "example-event-a:1:1"
    ? { ...r, estimate_utc: "2015-09-17T13:09:00Z", reported_utc: "2015-09-17T13:20:00Z", reported_minus_estimate_minutes: 11 } : r) };
const hours = () => Array.from({ length: 30 }, () => 0);
const counts = (ntwc_pairs: number, ntwc_pairs_with_position: number): EventCounts => ({ ntwc_pairs, ntwc_pairs_with_position, ntwc_reported: 0, ncei_reported: 0,
  stations: 0, reported_per_hour: { ntwc: hours(), ncei: hours() } });
const ref = (bundle_id: string) => ({ bundle_id, manifest_sha256: "0".repeat(64), manifest_bytes: 1 });
const adak: EventEntry = { event_id: "usp0007jcu", label: "Adak, Alaska", origin_time_utc: "1996-06-10T04:03:35.480Z", latitude: 0, longitude: 0, magnitude: 7.9,
  magnitude_type: "mwc", records: null, layers: null, arrivals: null, x: -1376848, y: 6141947, counts: counts(0, 0) };
const tohoku: EventEntry = { event_id: STORY_EVENT_ID, label: "Tōhoku, Japan", origin_time_utc: "2011-03-11T05:46:24.120Z", latitude: 0, longitude: 0,
  magnitude: 9.1, magnitude_type: "mww", records: ref("records-tohoku"), layers: ref("layers-tohoku"), arrivals: null, x: -4947802, y: 4729696, counts: counts(92, 8) };
const illapel: EventEntry = { event_id: "us20003k7a", label: "Illapel, Chile", origin_time_utc: "2015-09-16T22:54:32.860Z", latitude: 0, longitude: 0,
  magnitude: 8.3, magnitude_type: "mww", records: ref("records-illapel"), layers: ref("layers-illapel"), arrivals: null, x: 7861041, y: -3951167, counts: counts(67, 53) };
const index: EventsIndex = { schema_version: "2", evidence_state: "internal_descriptive_only", default_event_id: STORY_EVENT_ID, events: [adak, tohoku, illapel],
  basemap: { path: "basemap-v1/coastline.json", bytes: 1, sha256: "0".repeat(64) } };
const coast = { parts: [[[0, 0], [1000, 0], [0, -1000], [0, 0]]], closed: [true] } as EventsViewProps["basemap"];
const manifestFor = (entry: EventEntry, ids: string[]): DemoManifest => ({ schema_version: "1", exporter_version: "1", bundle_id: `test-${entry.event_id}`,
  evidence_state: "internal_descriptive_only", event: { event_id: entry.event_id, origin_time_utc: entry.origin_time_utc, latitude: 0, longitude: 0 },
  release: { release_id: "test", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy", allowed_uses: [], prohibited_uses: [] },
  default_state: { selectedStationId: ids[0], pinnedStationId: ids[1], windowId: "common_day", productKey: "raw_value" },
  windows: [{ id: "common_day", label: "Test day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z" }],
  stations: ids.map(station_id => ({ station_id, source_id: "test", station_type: "coastal" as const, name: `Test ${station_id}`, units: "m", vertical_reference: "unknown",
    horizontal_datum: "unknown", coordinate_order: "test", time_basis: "UTC", latitude: 0, longitude: 0, observation_count: 0, products: [],
    source: { source_id: "test", title: "test", publisher: "test", accessed_on: "unknown", version_or_date: "unknown", license_or_terms: "unknown", processing_level: "test", sha256: "0".repeat(64), url: null } })),
  assets: [], geometry_path: "geometry.json", input_fingerprints: [], config_sha256: "0".repeat(64),
  accounting: { source_observation_count: 0, exported_observation_count: 0, station_count: ids.length, rejected_observation_count: 0 } });
const tohokuManifest = manifestFor(tohoku, ["1617760", "saip", "21418"]), illapelManifest = manifestFor(illapel, ["9410230", "1617760"]);
const step = (id: number) => STEPS.find(s => s.id === id)!;
const data = (arrivals: StoryArrivals | null, extra: Partial<StepData> = {}): StepData => ({ events: index.events, entry: tohoku, arrivals, ...extra });
const noop = () => undefined;
// A hook-free piece: walk its elements to press its buttons (no DOM needed).
type Node = ReactElement<{ children?: ReactNode; onClick?: () => void; ref?: (el: unknown) => void; id?: string; "aria-disabled"?: boolean }>;
const tree = (node: ReactNode): Node[] => Array.isArray(node) ? node.flatMap(tree) : !isValidElement<Node["props"]>(node) ? []
  : [node, ...(typeof node.type === "function" ? tree((node.type as (p: unknown) => ReactNode)(node.props)) : []), ...tree(node.props.children)];
const buttons = (nodes: Node[]) => nodes.filter(n => n.type === "button").map(n => n.props.children);

const STEP4 = "Hilo's tide gauge records raw water level, tide included, on its own vertical scale. The white line marks the story clock on its record; it is a "
  + "time on the clock, not a reported time.";
const STEP5 = "Saipan's record has gaps, stretches with no samples at all. A gap is a missing sample, not a zero. Hilo and Saipan use different instruments "
  + "and datums, so their heights are not compared.";

describe("copy sweep v2 in the step copy", () => {
  it("rewrites the last sentences of steps 2, 3 and 4 and the whole of step 6", () => {
    expect(stepBody(step(2), data(null))).toBe("NOAA/NCEI's travel-time map draws one line for each hour after the earthquake, calculated from ocean depth. "
      + "It is a published model estimate of travel time for the first wave only, with no wave height.");
    expect(stepBody(step(3), data(null))).toBe("DART 21418 sits on the deep seafloor east of Japan and records the water column above it. Its record is shown "
      + "as measured, point by point. No time is picked from this record.");
    expect(stepBody(step(4), data(null))).toBe(STEP4);
    expect(step(6).title).toBe("A contour is a published estimate");
    expect(stepBody(step(6), data(null))).toBe("Two times are easy to mix up: the published travel time on this map and the time a source reported for a "
      + "place. Neither is a validated arrival time, and neither is when a warning was issued. The data cannot say which one is off.");
    expect(step(6).lens).toEqual({ point: "between-10-11" });
  });
  it("keeps none of the old wording", () => {
    const all = STEPS.map(s => `${s.title} ${stepBody(s, data(relinked()))}`).join(" ");
    for (const old of ["first arrival only", "No arrival is picked here", "a time, not an arrival", "A contour is not an arrival", "Three clocks",
      "the time people were warned"]) expect(all).not.toContain(old);
  });
});

describe("steps 4 and 5: the added lines, read from the reported-times file", () => {
  it("step 4 adds Hilo's NCEI reported time from the place linked within 1 km to station 1617760", () => {
    expect(stepBody(step(4), data(relinked()))).toBe(`${STEP4} NCEI reports a time for Hilo of 7 h 56 min after NCEI's origin. The clock has not reached it yet.`);
  });
  it("step 5 adds each strip's own place's NCEI reported time with its straight-line distance", () => {
    expect(stepBody(step(5), data(relinked()))).toBe(`${STEP5} Each strip carries its own place's NCEI reported time: Saipan, 2,578 km in a straight line `
      + "from the epicentre, at 3 h 17 min after NCEI's origin; Hilo, 6,310 km, at 7 h 56 min after NCEI's origin.");
  });
  it("leaves the added lines out, with no placeholder, when the file is missing or rejected, or names no such report", () => {
    for (const file of [null, { ...example, places: [], reports: [] }]) {
      expect(stepBody(step(4), data(file))).toBe(STEP4);
      expect(stepBody(step(5), data(file))).toBe(STEP5);
    }
    expect(stepBody(step(4), data(relinked("same_provider_id")))).toBe(STEP4);   // only the place linked within 1 km
  });
});

describe("the ten steps", () => {
  it("run 0 → 9; 1–6 keep their authored state; 0 and 9 are All events, 7 Tōhoku's Reported times, 8 Illapel's story", () => {
    expect(STEPS.map(s => s.id)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    STEPS.forEach((s, i) => expect(s.id).toBe(i));
    expect(STEPS.map(s => [s.event === STORY_EVENT_ID ? "tohoku" : s.event, s.view])).toEqual([["tohoku", "events"], ...Array(6).fill(["tohoku", "story"]),
      ["tohoku", "times"], ["us20003k7a", "story"], [null, "events"]]);
    expect(STEPS.slice(1, 7).map(s => [s.t, s.lens, s.compare, s.b])).toEqual([[0, { point: "epicentre" }, false, null], [8, { point: "epicentre" }, false, null],
      [1, { station: "21418" }, false, null], [7.5, { station: "1617760" }, false, null], [7.5, { station: "1617760" }, true, "saip"],
      [12, { point: "between-10-11" }, false, null]]);
    expect(step(7)).toMatchObject({ t: 30, sort: "time", play: null });
    expect(step(8)).toMatchObject({ t: 14.5, lens: { station: "1617760" }, compare: false, play: null });
    expect(STEPS.map(s => s.title).slice(7)).toEqual(["Tōhoku, station by station", "The same question, another earthquake", "Choose an event"]);
    expect(step(0).title).toBe("Many earthquakes, one question");
  });
  it("checks each event's own steps against its stations", () => {
    expect(() => validateSteps(["1617760", "saip", "21418"])).not.toThrow();
    expect(() => validateSteps(["9410230", "1617760"], illapel.event_id)).not.toThrow();
    expect(() => validateSteps(["9410230"], illapel.event_id)).toThrow(/step 9 names unknown station 1617760/);
    expect(() => validateSteps([], adak.event_id)).not.toThrow();
  });
});

describe("the computed copy of steps 0, 7 and 8", () => {
  it("step 0 counts the events, their years and the index's NTWC pairs", () => {
    expect(stepBody(step(0), data(null))).toBe("Each star is one of 3 Pacific earthquakes from 1996 to 2015. For each, the archives list an NTWC published estimate "
      + "of a time at a coastal place, a reported time there, or both. Across these earthquakes, 159 NTWC table rows have both times, and 61 of them have a "
      + "reviewed position and are drawn. Where both exist, the app shows how many minutes they differ by. The story starts with one earthquake.");
  });
  it("step 7 reads Tōhoku's accounting, and leaves it out without the file", () => {
    expect(stepBody(step(7), data(tohokuFile))).toBe("One row for each report. 92 NTWC table rows have both a published estimate and a reported time, and the "
      + "row says how many minutes they differ by, not which one is off; 8 have a reviewed position and appear on the map. NCEI's 273 reported times are a "
      + "separate source, listed with no estimate and never compared with NTWC's.");
    expect(stepBody(step(7), data(null))).toBe("One row for each report.");
  });
  it("step 8 reads Illapel's entry and its Hilo row: the exporter's difference, the estimate's own UTC day; without the file only the entry", () => {
    const d = data(illapelFile, { entry: illapel });
    expect(stepBody(step(8), d)).toBe("Illapel, Chile earthquake of 16 September 2015 (UTC). At Hilo, NTWC's published estimate was 13:09 UTC on 17 September and "
      + "its reported time 13:20 UTC: they differ by 11 minutes. NCEI's reported time for Hilo is a separate source and is not combined with them.");
    expect(stepBody(step(8), { ...d, arrivals: null })).toBe("Illapel, Chile earthquake of 16 September 2015 (UTC).");
    expect(stepBody(step(8), { ...d, arrivals: relinked() })).toBe("Illapel, Chile earthquake of 16 September 2015 (UTC).");   // no NTWC row at Hilo
  });
  it("step 9 is fixed copy", () => {
    expect(stepBody(step(9), data(null))).toBe("Pick any earthquake on the map or in the list. Events with station records open with a record under the lens; "
      + "events with only reported times show their marks as the clock plays.");
  });
});

describe("links: a plain link opens step 0; a step on the wrong event or side of All events is repaired; old links are unchanged", () => {
  it("opens step 0 on All events from a plain link", () => {
    for (const plain of ["", "?"]) expect(routeSearch(plain, index)).toEqual({ search: "?view=events&step=0", issues: [] });
    expect(parseEventsState("?view=events&step=0")).toEqual({ state: { order: "date", has: null, step: 0 }, issues: [] });
  });
  it("keeps every link that names a step or a view as it is, and today's step links serialize byte-identically", () => {
    const old = ["?view=story&selected=1617760&pinned=saip&window=common_day&product=raw_value&t=0&cmp=0&step=1",
      "?view=story&selected=21418&pinned=saip&window=common_day&product=raw_value&t=1&cmp=0&step=3&at=-4282,3827&z=2.25",
      "?view=story&selected=1617760&pinned=saip&window=common_day&product=raw_value&t=7.5&cmp=0&step=4",
      "?view=paired&selected=1617760&pinned=saip&window=common_day&product=raw_value&t=7.5&cmp=1&step=5",
      "?view=times&selected=1617760&pinned=saip&window=common_day&product=raw_value&sort=distance&t=7.5&cmp=0&step=4",
      "?view=story&selected=1617760&pinned=saip&window=common_day&product=raw_value&t=12&cmp=0&step=explore&from=6",
      "?view=events", "?event=us20003k7a&view=story&t=0&cmp=0&step=explore", "?step=4", "?view=story"];
    for (const url of old) expect(routeSearch(url, index), url).toEqual({ search: url, issues: [] });
    for (const url of old.slice(0, 6)) {
      const { state, issues } = parseState(url, tohokuManifest), story = parseStoryParams(url, STORY_EVENT_ID);
      expect([issues, story.issues], url).toEqual([[], []]);
      expect(serializeState(state, story.params)).toBe(url);
    }
    expect(parseStoryParams("?step=4", STORY_EVENT_ID).params).toMatchObject({ step: 4, t: 7.5, compare: false });
  });
  it("opens step 8 from an Illapel link and step 7 from a Tōhoku link, each as authored", () => {
    expect(routeSearch("?event=us20003k7a&step=8", index)).toEqual({ search: "?event=us20003k7a&step=8", issues: [] });
    expect(parseStoryParams("?event=us20003k7a&step=8", illapel.event_id)).toEqual({ params: { t: 14.5, compare: false, step: 8, at: null, z: 1, from: null }, issues: [] });
    expect(routeSearch("?step=7", index)).toEqual({ search: "?step=7&view=times", issues: [] });   // a step link need not name its view
    expect(parseStoryParams("?step=7&view=times", STORY_EVENT_ID).params).toMatchObject({ step: 7, t: 30 });
    expect(routeSearch("?step=9", index)).toEqual({ search: "?step=9&view=events", issues: [] });
    expect(parseStoryParams("", illapel.event_id).params.step).toBe("explore");   // any other link to another event opens in Explore, as today
  });
  it("repairs a step named on another event to that step's own event, with a note", () => {
    expect(routeSearch("?step=8", index)).toEqual({ search: "?step=8&event=us20003k7a", issues: ["Invalid event for story step 9: Illapel, Chile restored."] });
    expect(routeSearch("?event=usp0007jcu&view=story&step=4", index)).toEqual({ search: "?view=story&step=4",
      issues: ["Invalid event for story step 5: Tōhoku, Japan restored."] });
    expect(routeSearch("?event=us20003k7a&view=times&step=7", index).search).toBe("?view=times&step=7");
  });
  it("repairs a step on the wrong side of All events to its own view, with a note", () => {
    expect(routeSearch("?view=story&step=0", index)).toEqual({ search: "?view=events&step=0", issues: ["Invalid view for story step 1: All events restored."] });
    expect(routeSearch("?event=us20003k7a&view=paired&step=9", index)).toEqual({ search: "?event=us20003k7a&view=events&step=9",
      issues: ["Invalid view for story step 10: All events restored."] });
    expect(routeSearch("?view=events&step=4", index)).toEqual({ search: "?view=story&step=4", issues: ["Invalid view for story step 5: Story restored."] });
    expect(routeSearch("?view=events&step=7", index).search).toBe("?view=times&step=7");
  });
  it("opens Explore with a note when the step's own event is not listed", () => {
    const alone: EventsIndex = { ...index, events: [adak, tohoku] };
    expect(routeSearch("?step=8", alone)).toEqual({ search: "?step=8", issues: [] });
    expect(parseStoryParams("?step=8", STORY_EVENT_ID)).toEqual({ params: { t: 0, compare: false, step: "explore", at: null, z: 1, from: null },
      issues: ["Invalid event for story step 9: free exploration opened."] });
  });
  it("writes a step entered from elsewhere on its own event and view, at its authored clock", () => {
    expect([0, 1, 7, 8].map(id => stepSearch(id as 0, index, illapel))).toEqual(["?view=events&step=0", "?view=story&t=0&cmp=0&step=1",
      "?view=times&t=30&cmp=0&step=7", "?event=us20003k7a&view=story&t=14.5&cmp=0&step=8"]);
    expect([stepSearch(9, index, illapel), stepSearch(9, index, tohoku)]).toEqual(["?event=us20003k7a&view=events&step=9", "?view=events&step=9"]);
  });
  it("carries the step and the step to resume in All events links", () => {
    expect(eventsSearch(illapel.event_id, { order: "magnitude", has: null, step: 9 })).toBe("?event=us20003k7a&view=events&order=magnitude&step=9");
    expect(eventsSearch(null, { order: "date", has: null, from: 0 })).toBe("?view=events&from=0");
    expect(parseEventsState("?view=events&from=9")).toEqual({ state: { order: "date", has: null, from: 9 }, issues: [] });
    expect(parseEventsState("?view=events&step=4&from=x")).toEqual({ state: { order: "date", has: null },
      issues: ["Invalid story step: free exploration opened.", "Invalid resume step: ignored."] });
  });
});

// The writers (DemoApp's LoadedDemo and EventsDemo) under a stubbed window: every history write is recorded, and history.state follows it.
const write = (s: unknown, _title: string, _url: string) => { history.state = s; };
const history = { state: null as unknown, pushState: vi.fn(write), replaceState: vi.fn(write), back: vi.fn() };
const stub = (search: string, state: unknown) => {
  history.state = state; history.pushState.mockClear(); history.replaceState.mockClear(); history.back.mockClear(); stepFocus.step = null;
  seen.story = seen.times = seen.events = null;
  vi.stubGlobal("window", { location: { search, pathname: "/demos.html", hash: "" }, history, innerWidth: 1440, innerHeight: 900, setTimeout: () => 0 });
};
const writes = () => [...history.pushState.mock.calls.map(c => ["push", c[0], c[2]]), ...history.replaceState.mock.calls.map(c => ["replace", c[0], c[2]])];
function event(search: string, entry: EventEntry, state: unknown = null) {
  stub(search, state);
  const onEventChange = vi.fn(), manifest = entry === illapel ? illapelManifest : tohokuManifest;
  renderToStaticMarkup(<LoadedDemo index={index} entry={entry} manifest={manifest} issues={[]} onEventChange={onEventChange}/>);
  const p = (seen.times ?? seen.story) as StoryViewProps;
  const send = (ev: NavEvent) => p.onNav(reduce({ ...p.params, a: p.state.selectedStationId, b: p.state.pinnedStationId }, ev,
    { motionOK: true, stationIds: manifest.stations.map(s => s.station_id), prevEntryStep: (history.state as { prev?: never } | null)?.prev ?? null } as NavContext));
  return { p, send, onEventChange };
}
function allEvents(search: string, state: unknown = null) {
  stub(search, state);
  const onLeave = vi.fn();
  renderToStaticMarkup(<EventsDemo index={index} entry={search.includes("us20003k7a") ? illapel : tohoku} basemap={coast} issues={[]} onLeave={onLeave}/>);
  return { p: seen.events as EventsViewProps, onLeave };
}
const T = "selected=1617760&pinned=saip&window=common_day&product=raw_value";
afterEach(() => vi.unstubAllGlobals());

describe("Next and Back across views, events and All events (the navigation contract)", () => {
  it("Next from 6 pushes step 7 on Reported times, sorted by reported time, at 30 h", () => {
    const { send, onEventChange } = event(`?view=story&${T}&t=12&cmp=0&step=6`, tohoku, { step: 6, prev: 5 });
    send({ type: "next" });
    expect(writes()).toEqual([["push", { step: 7, prev: 6 }, `/demos.html?view=times&${T}&t=30&cmp=0&step=7`]]);
    expect([onEventChange.mock.calls.length, stepFocus.step]).toEqual([0, 7]);
  });
  it("Back from 7 goes back when the previous entry is step 6, else replaces it with step 6 on the story view", () => {
    event(`?view=times&${T}&t=30&cmp=0&step=7`, tohoku, { step: 7, prev: 6 }).send({ type: "back" });
    expect([history.back.mock.calls.length, writes()]).toEqual([1, []]);
    event(`?view=times&${T}&t=30&cmp=0&step=7`, tohoku, { step: 7, prev: null }).send({ type: "back" });
    expect(writes()).toEqual([["replace", { step: 6, prev: null }, `/demos.html?view=story&${T}&t=12&cmp=0&step=6`]]);
  });
  it("Return to step 7 restores reported-time order and 30 h without a new entry", () => {
    event(`?view=times&${T}&sort=distance&t=4&cmp=0&step=7`, tohoku, { step: 7, prev: 6 }).send({ type: "returnToStep" });
    expect(writes()).toEqual([["replace", { step: 7, prev: 6 }, `/demos.html?view=times&${T}&t=30&cmp=0&step=7`]]);
  });
  it("Next from 7 pushes step 8 and loads Illapel through the event-change path", () => {
    const { send, onEventChange } = event(`?view=times&${T}&t=30&cmp=0&step=7`, tohoku, { step: 7, prev: 6 });
    send({ type: "next" });
    expect(writes()).toEqual([["push", { step: 8, prev: 7 }, "/demos.html?event=us20003k7a&view=story&t=14.5&cmp=0&step=8"]]);
    expect([onEventChange.mock.calls.length, stepFocus.step]).toEqual([1, 8]);
  });
  it("Back from 8 goes back to step 7 when it is the previous entry, else replaces and loads Tōhoku's step 7", () => {
    const I = "selected=1617760&pinned=9410230&window=common_day&product=raw_value";
    event(`?event=us20003k7a&view=story&${I}&t=14.5&cmp=0&step=8`, illapel, { step: 8, prev: 7 }).send({ type: "back" });
    expect([history.back.mock.calls.length, writes()]).toEqual([1, []]);
    const { send, onEventChange } = event(`?event=us20003k7a&view=story&${I}&t=14.5&cmp=0&step=8`, illapel, { step: 8, prev: null });
    send({ type: "back" });
    expect(writes()).toEqual([["replace", { step: 7, prev: null }, "/demos.html?view=times&t=30&cmp=0&step=7"]]);
    expect(onEventChange).toHaveBeenCalledTimes(1);
  });
  it("Next from 8 pushes step 9: All events with Illapel still selected", () => {
    const { send, onEventChange } = event("?event=us20003k7a&view=story&selected=1617760&pinned=9410230&window=common_day&product=raw_value&t=14.5&cmp=0&step=8",
      illapel, { step: 8, prev: 7 });
    send({ type: "next" });
    expect(writes()).toEqual([["push", { step: 9, prev: 8 }, "/demos.html?event=us20003k7a&view=events&step=9"]]);
    expect(onEventChange).toHaveBeenCalledTimes(1);
  });
  it("Back from 1 goes to step 0 on All events: back when it is the previous entry, else a replace that loads All events", () => {
    event(`?view=story&${T}&t=0&cmp=0&step=1`, tohoku, { step: 1, prev: 0 }).send({ type: "back" });
    expect([history.back.mock.calls.length, writes()]).toEqual([1, []]);
    const { send, onEventChange } = event(`?view=story&${T}&t=0&cmp=0&step=1`, tohoku, { step: 1, prev: null });
    send({ type: "back" });
    expect(writes()).toEqual([["replace", { step: 0, prev: null }, "/demos.html?view=events&step=0"]]);
    expect([onEventChange.mock.calls.length, stepFocus.step]).toEqual([1, 0]);
  });
  it("within the story view, Next and Back write as before", () => {
    event(`?view=story&${T}&t=0&cmp=0&step=1`, tohoku, { step: 1, prev: 0 }).send({ type: "next" });
    expect(writes()).toEqual([["push", { step: 2, prev: 1 }, `/demos.html?view=story&${T}&t=0&cmp=0&step=2`]]);
    expect(stepFocus.step).toBeNull();
  });
  it("on All events, Next from 0 pushes step 1 and loads Tōhoku's story; Back on 0 does nothing", () => {
    const { p, onLeave } = allEvents("?view=events&step=0", { step: 0, prev: null });
    p.onStep("back");
    expect(writes()).toEqual([]);
    p.onStep("next");
    expect(writes()).toEqual([["push", { step: 1, prev: 0 }, "/demos.html?view=story&t=0&cmp=0&step=1"]]);
    expect([onLeave.mock.calls.length, stepFocus.step]).toEqual([1, 1]);
  });
  it("on All events, Back from 9 goes back to step 8 when it is the previous entry, else replaces and loads Illapel's step 8", () => {
    allEvents("?event=us20003k7a&view=events&step=9", { step: 9, prev: 8 }).p.onStep("back");
    expect([history.back.mock.calls.length, writes()]).toEqual([1, []]);
    const { p, onLeave } = allEvents("?event=us20003k7a&view=events&step=9", { step: 9, prev: null });
    p.onStep("back");
    expect(writes()).toEqual([["replace", { step: 8, prev: null }, "/demos.html?event=us20003k7a&view=story&t=14.5&cmp=0&step=8"]]);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });
});

describe("Skip to free exploration keeps the event and the view; Back to the guided story resumes the step left", () => {
  it("from step 0 or 9 stays on All events, out of the story, and resumes there", () => {
    for (const [search, url] of [["?view=events&step=0", "/demos.html?view=events&from=0"], ["?event=us20003k7a&view=events&step=9",
      "/demos.html?event=us20003k7a&view=events&from=9"]] as const) {
      const id = search.endsWith("0") ? 0 : 9, { p, onLeave } = allEvents(search, { step: id, prev: null });
      p.onStep("explore");
      expect(writes()).toEqual([["push", { step: "explore", prev: id }, url]]);
      expect(onLeave).not.toHaveBeenCalled();
      const back = allEvents(url.slice("/demos.html".length), { step: "explore", prev: id });
      expect([back.p.step, back.p.from]).toEqual([undefined, id]);
      back.p.onStep("resumeStory");
      expect(writes()).toEqual([["push", { step: id, prev: "explore" }, `/demos.html${search}`]]);
    }
  });
  it("from step 7 goes to Reported times in Explore", () => {
    event(`?view=times&${T}&t=30&cmp=0&step=7`, tohoku, { step: 7, prev: 6 }).send({ type: "explore" });
    expect(writes()).toEqual([["push", { step: "explore", prev: 7 }, `/demos.html?view=times&${T}&t=30&cmp=0&step=explore&from=7`]]);
  });
  it("from step 8 goes to Illapel's story in Explore", () => {
    const I = "selected=1617760&pinned=9410230&window=common_day&product=raw_value";
    event(`?event=us20003k7a&view=story&${I}&t=14.5&cmp=0&step=8`, illapel, { step: 8, prev: 7 }).send({ type: "explore" });
    expect(writes()).toEqual([["push", { step: "explore", prev: 8 }, `/demos.html?event=us20003k7a&view=story&${I}&t=14.5&cmp=0&step=explore&from=8`]]);
  });
});

describe("the step panel in every view", () => {
  const panel = (id: number, onNav = noop as (t: string) => void, canReturn = true) => StepPanel({ step: step(id), body: "Body.", onNav, canReturn });
  it("numbers the steps by position, 1 to 10, and gives title, body, Back, Next and Skip", () => {
    const html = renderToStaticMarkup(panel(0, noop, false));
    expect(html).toContain('aria-label="Story step 1 of 10"');
    expect(html).toContain('<p class="story-kicker">1 of 10</p><h2 class="story-step__title" id="story-step-title" tabindex="-1">Many earthquakes, one question</h2>');
    expect(html).toMatch(/<button type="button" aria-disabled="true">Back<\/button><button type="button">Next<\/button>/);
    expect(buttons(tree(panel(0, noop, false)))).toEqual(["Back", "Next", "Skip to free exploration"]);
    expect(buttons(tree(panel(7)))).toEqual(["Back", "Next", "Return to this step", "Skip to free exploration"]);
    expect(renderToStaticMarkup(panel(9))).toContain("10 of 10");
  });
  it("has no Next on step 9: the story ends there", () => {
    expect(buttons(tree(panel(9, noop, false)))).toEqual(["Back", "Skip to free exploration"]);
    expect(reduce({ step: 9, from: null, t: 0, compare: false, at: null, z: 1, a: "", b: null }, { type: "next" }, { motionOK: true, stationIds: [] }))
      .toMatchObject({ history: "none", effects: [] });
  });
  it("presses each control once", () => {
    const pressed: string[] = [], nodes = tree(panel(7, t => pressed.push(t)));
    for (const label of ["Back", "Next", "Return to this step", "Skip to free exploration"]) nodes.find(n => n.type === "button" && n.props.children === label)!.props.onClick!();
    expect(pressed).toEqual(["back", "next", "returnToStep", "explore"]);
  });
  it("moves focus to the heading of a step entered across a remount, once", () => {
    const heading = () => tree(panel(8)).find(n => n.props.id === "story-step-title")!, el = { focus: vi.fn() };
    stepFocus.step = 7; heading().props.ref!(el);
    expect(el.focus).not.toHaveBeenCalled();
    stepFocus.step = 8; heading().props.ref!(el); heading().props.ref!(el);
    expect(el.focus).toHaveBeenCalledTimes(1);
    expect(stepFocus.step).toBeNull();
  });
  it("shows step 0 and step 9 on All events, with the index's copy, and a way back after Skip", () => {
    const view = (extra: Partial<EventsViewProps>) => renderToStaticMarkup(<EventsView events={index.events} selected={tohoku} order="date" has={null} basemap={coast}
      issues={[]} onDismissIssues={noop} restoreKey={0} onSelect={noop} onOrder={noop} onHas={noop} onOpen={noop} onStep={noop} initialSize={{ w: 1440, h: 900 }} {...extra}/>);
    const zero = view({ step: 0 });
    expect(zero).toContain("1 of 10");
    expect(zero).toContain("Each star is one of 3 Pacific earthquakes from 1996 to 2015.");
    expect(zero).not.toContain("Return to this step");
    const nine = view({ step: 9, selected: illapel });
    expect(nine).toContain("10 of 10"); expect(nine).toContain("Choose an event"); expect(nine).toContain("Open this event");
    expect(view({ from: 9 })).toContain(">Back to the guided story (step 10)</button>");
    expect(view({})).not.toMatch(/story-step|Back to the guided story/);
    for (const size of [{ w: 390, h: 844 }]) expect(view({ step: 0, initialSize: size })).toContain("1 of 10");
  });
  it("shows step 7 on Tōhoku's Reported times page with its accounting, and a way back after Skip", () => {
    const props = (params: Partial<StoryViewProps["params"]>): StoryViewProps => ({ manifest: tohokuManifest, geometry: null, geometryError: null, layers: null,
      layersError: null, layersPending: null, onRetryLayers: noop, state: { view: "times", ...tohokuManifest.default_state, sort: "time" }, selected: null, pinned: null,
      onOpenEvidence: noop, onRetryStation: noop, onRetryGeometry: noop, params: { t: 30, compare: false, step: 7, at: null, z: 1, from: null, ...params }, onNav: noop,
      restoreKey: 0, evidenceOpen: false, issues: [], onDismissIssues: noop, onState: noop, entry: tohoku, events: index.events, onEvent: noop, onAllEvents: noop,
      arrivals: tohokuFile });
    const html = renderToStaticMarkup(<ArrivalsView {...props({})}/>);
    expect(html).toContain("8 of 10"); expect(html).toContain("Tōhoku, station by station");
    expect(html).toContain("One row for each report. 92 NTWC table rows have both a published estimate and a reported time");
    expect(html).toContain("Return to this step");
    expect(renderToStaticMarkup(<ArrivalsView {...props({ step: "explore", from: 7 })}/>)).toContain(">Back to the guided story (step 8)</button>");
    expect(renderToStaticMarkup(<ArrivalsView {...props({ step: 4 })}/>)).not.toMatch(/story-step|Back to the guided story/);   // a step carried from Story, as today
  });
  it("shows step 8 on Illapel's story view, and in Explore from it the way back", () => {
    const html = renderToStaticMarkup(<StoryView manifest={illapelManifest} geometry={{ points: [{ id: illapel.event_id, x: 7861041, y: 3951167 }, { id: "9410230", x: 0, y: 0 },
      { id: "1617760", x: 460310, y: -2509744 }], coastline: [] }} geometryError={null} layers={null} layersError={null} layersPending={null} onRetryLayers={noop}
      state={{ view: "story", ...illapelManifest.default_state, selectedStationId: "1617760" }} selected={null} pinned={null} onOpenEvidence={noop} onRetryStation={noop}
      onRetryGeometry={noop} params={{ t: 14.5, compare: false, step: 8, at: null, z: 1, from: null }} onNav={noop} restoreKey={0} evidenceOpen={false} issues={[]}
      onDismissIssues={noop} onState={noop} entry={illapel} events={index.events} onEvent={noop} onAllEvents={noop} arrivals={illapelFile} initialSize={{ w: 1440, h: 900 }}/>);
    expect(html).toContain("9 of 10"); expect(html).toContain("The same question, another earthquake");
    expect(html).toContain("At Hilo, NTWC&#x27;s published estimate was 13:09 UTC on 17 September");
    expect(html).toContain('story-lens-title__name">Test 1617760<');
    expect(html).not.toContain("unknown station");
  });
});
