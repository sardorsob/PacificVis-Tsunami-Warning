import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { RecordChart, SliceChart, type RecordChartProps } from "../RecordChart";
import type { SliceRecords, SliceRow, SliceStation } from "../slices";
import { NoReference, StationCard, type StationCardProps } from "../StationCard";
import { SliceSupport, SupportView, type SupportViewProps } from "../SupportView";
import type { AnySelection, StationMetadata, StationRecords, StationSelection } from "../types";
import type { Pt } from "./layers";
import { Lens } from "./Lens";
import { StationTools, type StationToolsProps } from "./StationTools";
import type { MapStation } from "./StoryMap";
import { EventSelect, eventOption, magnitudeText, ViewSwitch } from "./ViewSwitch";
import { placeLabel } from "./StoryMap";
import type { EventEntry } from "../types";
// The Tōhoku station ids, as typed test-only input.
const STATION_IDS = ["1617760", "1770000", "21413", "21418", "32401", "46411", "9419750", "9461380", "saip", "valp"];

// Typed test-only inputs (moved from the retired radial tests). Never imported by a runtime renderer or scientific bundle.
const stations: StationMetadata[] = STATION_IDS.map(station_id => ({
  station_id, source_id: "test-only", station_type: "dart", name: `Test station ${station_id}`, units: "m", vertical_reference: "unknown",
  horizontal_datum: "unknown", coordinate_order: "longitude,latitude", time_basis: "UTC", latitude: 0, longitude: 0, observation_count: 1,
  products: [
    { key: "raw_value", label: "Test raw measurement", units: "m", available: true },
    { key: "residual_value", label: "Test residual", units: "m", available: false },
    { key: "fitted_value", label: "Test fitted", units: "m", available: false },
  ],
  source: { source_id: "test-only", title: "Test-only source", publisher: "Test publisher", accessed_on: "unknown", version_or_date: "unknown",
    license_or_terms: "unknown", processing_level: "test-only", sha256: "0".repeat(64), url: null },
}));
function records(station: StationMetadata): StationRecords {
  return { schema_version: "1", station_id: station.station_id, rows: [{
    observation_id: `test-${station.station_id}`, source_id: station.source_id, station_id: station.station_id,
    source_time: "2011-03-11T00:00:00Z", observed_at_utc: "2011-03-11T00:00:00Z",
    raw_value: 0, fitted_value: null, residual_value: null, units: "m", vertical_reference: "unknown",
    raw_status: "observed", residual_status: "structurally_not_applicable", grid_status: "not_applicable",
    qc_flags: { test_flag: true }, source_qc_status: "flagged",
  }], support: [{ station_id: station.station_id, window_id: "common_day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z",
    accepted_sample_n: 1, valid_sample_n: 1, source_blank_n: 0, product_valid_n: { raw_value: 1, residual_value: 0, fitted_value: 0 },
    support_kind: "dart_actual_timestamps", strict_numerator_n: null, strict_denominator_n: null, strict_percent: null, cadence_seconds_counts: [] }],
  coverage_spans: [], gap_blocks: [] };
}
const ready = (s: StationMetadata): StationSelection => ({ station: s, status: "ready", records: records(s), error: null });
const card = (selection: AnySelection, extra: Partial<StationCardProps> = {}): StationCardProps => ({
  selection, role: "selected", windowId: "common_day", productKey: "raw_value", cursorMs: Date.parse("2011-03-11T12:00:00Z"),
  onOpenEvidence: vi.fn(), onRetryStation: vi.fn(), ...extra });

type NodeProps = { children?: ReactNode; onClick?: () => void; onChange?: (e: { target: { value: string } }) => void; disabled?: boolean;
  "aria-label"?: string; value?: string };
/** Walks a hook-free component's element tree (no DOM needed). */
function nodes(node: ReactNode): ReactElement<NodeProps>[] {
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (!isValidElement<NodeProps>(node)) return [];
  const own = typeof node.type === "function" && !(node.type === RecordChart || node.type === SupportView)
    ? nodes((node.type as (p: unknown) => ReactNode)(node.props)) : [];
  return [node, ...own, ...nodes(node.props.children)];
}
const byLabel = (tree: ReactElement<NodeProps>[], label: string) => tree.find(n => n.props["aria-label"] === label);

describe("StationCard — one station's full record on the shared clock", () => {
  it("passes the exact records to one chart and one support, both with the clock cursor", () => {
    const props = card(ready(stations[0])), tree = nodes(StationCard(props));
    const chart = tree.find(n => n.type === RecordChart)!.props as unknown as RecordChartProps;
    const support = tree.find(n => n.type === SupportView)!.props as unknown as SupportViewProps;
    expect([chart.station.station_id, chart.role, chart.windowId, chart.productKey, chart.compact])
      .toEqual(["1617760", "selected", "common_day", "raw_value", undefined]);
    expect(chart.records).toBe(props.selection.records);
    expect(support.records).toBe(props.selection.records);
    expect(chart.cursorMs).toBe(props.cursorMs);
    expect(support.cursorMs).toBe(props.cursorMs);
    expect(renderToStaticMarkup(<StationCard {...props}/>)).toContain('aria-label="Selected: Test station 1617760"');
  });
  it("retains DART non-applicability, real zero, unknown datum, QC and safe source links", () => {
    const unsafe = { ...stations[0], source: { ...stations[0].source, url: "javascript:alert(1)" } };
    const html = renderToStaticMarkup(<StationCard {...card({ ...ready(stations[0]), station: unsafe })}/>);
    for (const text of ["Not applicable", "First 0 at", "unknown", "Source QC retained", "Source link unavailable"]) expect(html).toContain(text);
    expect(html).not.toContain("javascript:");
  });
  it("opens evidence with its own identity, and only once the record is verified", () => {
    const props = card(ready(stations[1]), { role: "pinned" });
    byLabel(nodes(StationCard(props)), "Rows & sources: Test station 1770000")!.props.onClick!();
    expect(props.onOpenEvidence).toHaveBeenCalledExactlyOnceWith("1770000");
    const loading = card({ station: stations[1], status: "loading", records: null, error: null });
    expect(byLabel(nodes(StationCard(loading)), "Rows & sources: Test station 1770000")!.props.disabled).toBe(true);
  });
  it("never shows measurements under loading or error, and retries the exact station", () => {
    const loading = card({ station: stations[0], status: "loading", records: null, error: null });
    expect(nodes(StationCard(loading)).filter(n => n.type === RecordChart || n.type === SupportView)).toHaveLength(0);
    expect(renderToStaticMarkup(<StationCard {...loading}/>)).toContain("Loading and verifying Test station 1617760 records…");
    const failed = card({ station: stations[0], status: "error", records: null, error: "test hash mismatch" });
    expect(nodes(StationCard(failed)).filter(n => n.type === RecordChart || n.type === SupportView)).toHaveLength(0);
    byLabel(nodes(StationCard(failed)), "Retry Test station 1617760")!.props.onClick!();
    expect(failed.onRetryStation).toHaveBeenCalledExactlyOnceWith("1617760");
    expect(renderToStaticMarkup(<StationCard {...failed}/>)).toContain("test hash mismatch");
  });
  it("says plainly when no reference is pinned", () => {
    expect(renderToStaticMarkup(<NoReference/>)).toContain("No reference pinned");
  });
});

describe("StationTools — stations, B, window and product", () => {
  const tools = (selectedStationId: string, extra: Partial<StationToolsProps> = {}): StationToolsProps => ({
    stations, windows: [{ id: "common_day", label: "Test day", start_utc: "", end_utc_exclusive: "" }, { id: "source_full", label: "Full", start_utc: "",
      end_utc_exclusive: "" }], selectedStationId, pinnedStationId: "1770000", windowId: "common_day", productKey: "raw_value",
    onSelect: vi.fn(), onPin: vi.fn(), onWindow: vi.fn(), onProduct: vi.fn(), ...extra });
  it("moves A only to named adjacent targets, stops at the ends, and never pins", () => {
    const first = tools("1617760"), tree = nodes(StationTools(first));
    expect(byLabel(tree, "Previous station target: Start of station list")!.props.disabled).toBe(true);
    byLabel(tree, "Next station target: Test station 1770000")!.props.onClick!();
    expect(first.onSelect).toHaveBeenCalledExactlyOnceWith("1770000");
    expect(first.onPin).not.toHaveBeenCalled();
    const middle = tools("21418");
    byLabel(nodes(StationTools(middle)), "Previous station target: Test station 21413")!.props.onClick!();
    expect(middle.onSelect).toHaveBeenCalledExactlyOnceWith("21413");
    expect(byLabel(nodes(StationTools(tools("valp"))), "Next station target: End of station list")!.props.disabled).toBe(true);
    expect(renderToStaticMarkup(<StationTools {...first}/>)).toContain("Test station 1770000");
  });
  it("labels each target on its own line above the full station name", () => {
    const html = renderToStaticMarkup(<StationTools {...tools("21418")}/>);
    expect(html).toContain("<small>← Previous</small><span>Test station 21413</span>");
    expect(html).toContain("<small>Next →</small><span>Test station 32401</span>");
  });
  it("never offers A as B, and clears B without substituting one", () => {
    const props = tools("1617760"), html = renderToStaticMarkup(<StationTools {...props}/>);
    const bSelect = html.slice(html.indexOf("Pinned reference B"));
    expect(bSelect).not.toMatch(/<option value="1617760"/);
    expect(bSelect).toContain("No reference pinned");
    byLabel(nodes(StationTools(props)), "Pinned reference B")!.props.onChange!({ target: { value: "" } });
    expect(props.onPin).toHaveBeenCalledExactlyOnceWith(null);
  });
  it("names a full-source window as station-specific and an unavailable product as unavailable", () => {
    const html = renderToStaticMarkup(<StationTools {...tools("1617760", { windowId: "source_full" })}/>);
    expect(html).toContain("station-specific bounds; not a common comparison period");
    expect(html).toContain("Test residual · unavailable at this station");
  });
});

describe("Lens — in-lens station names", () => {
  const station = (id: string, name: string, xy: Pt): MapStation => ({ id, name, type: "coastal", xy });
  const lens = (variant: "a" | "b") => renderToStaticMarkup(<svg><Lens id="t" view={{ k: 1, tx: 0, ty: 0 }} cx={100} cy={100} centre={[0, 0]}
    r={60} mag={1} stations={[station("c", "Hilo", [0, 0]), station("rim", "Kahului Harbor", [0, -48])]} epicentre={[999, 999]} variant={variant}/></svg>);
  it("names a station centred under its marker only when the whole name fits inside the rim, and only in the A lens", () => {
    const a = lens("a");
    expect(a).toContain('text-anchor="middle" class="story-label story-label--strong">Hilo<');
    expect(a).not.toContain("Kahului Harbor");   // its baseline fits, but the top of the text would cross the rim
    expect(lens("b")).not.toContain(">Hilo<");
  });
});

describe("ViewSwitch", () => {
  it("marks the current view and switches only to another one", () => {
    const onView = vi.fn(), tree = nodes(ViewSwitch({ view: "paired", onView }));
    const button = (label: string) => tree.find(n => n.type === "button" && n.props.children === label)!;
    expect((button("Paired").props as { "aria-pressed"?: boolean })["aria-pressed"]).toBe(true);
    button("Paired").props.onClick!();
    expect(onView).not.toHaveBeenCalled();
    button("Station lens").props.onClick!();
    expect(onView).toHaveBeenCalledExactlyOnceWith("radial");
  });
  it("offers the Reported times view after the other three, and presses it when it is the view", () => {
    const onView = vi.fn(), labels = (view: Parameters<typeof ViewSwitch>[0]["view"]) => nodes(ViewSwitch({ view, onView }))
      .filter(n => n.type === "button").map(n => `${n.props.children}${(n.props as { "aria-pressed"?: boolean })["aria-pressed"] ? " (on)" : ""}`);
    expect(labels("story")).toEqual(["Story (on)", "Paired", "Station lens", "Reported times"]);
    expect(labels("times")).toEqual(["Story", "Paired", "Station lens", "Reported times (on)"]);
    nodes(ViewSwitch({ view: "story", onView })).find(n => n.props.children === "Reported times")!.props.onClick!();
    expect(onView).toHaveBeenCalledExactlyOnceWith("times");
  });
});

// A typed schema-2 test-only station and record (records schema 2: one display window, one raw product, drawn as segments).
export const sliceStation: SliceStation = { station_id: "9410230", display_station_key: "coops:9410230", name: "Test La Jolla", product: "one_minute_water_level",
  latitude: 32.867, longitude: -117.257, units: "m", vertical_datum: "STND", source: { source_id: "test-src", sha256: "a".repeat(64), url: null },
  coverage_fraction: 0.8032407407407407, longest_supported_minutes: 1067, coverage_rule_id: "test-rule", rows: 4 };
const DISPLAY = { id: "display" as const, label: "6 hours before to 30 hours after the origin", start_utc: "2015-09-16T16:54:32.860Z",
  end_utc_exclusive: "2015-09-18T04:54:32.860Z" };
const at = (h: number) => Date.parse("2015-09-16T22:54:32.860Z") + h * 3_600_000;
const sliceRow = (h: number, v: number | null): SliceRow => ({ event_id: "test", source_id: "test-src", station_key: "coops-9410230", sensor: "unknown",
  timestamp_utc: new Date(at(h)).toISOString(), numeric_value: v, value_state: v === null ? "blank" : "finite_numeric", timestamp_state: "reported_utc",
  duplicate_timestamp: false, units: "m", vertical_datum: "STND", qc_state: "not_provided", qc_json: {} });
export const sliceRecords: SliceRecords = { station_id: "9410230", window: DISPLAY,
  rows: [sliceRow(1, 1), sliceRow(2, 2), sliceRow(2.5, null), sliceRow(3, 1.5)],
  segments: [[{ t: at(1), v: 1 }, { t: at(2), v: 2 }], [{ t: at(3), v: 1.5 }]],
  counts: { rows: 4, blank: 1, duplicates_dropped: 1, outside_window: 0, backward_steps: 0 } };
const paths = (html: string) => [...html.matchAll(/<path d="([^"]*)" class="record-points[^"]*"/g)].map(m => m[1]);

describe("SliceChart — a schema-2 record, one line per segment", () => {
  it("never joins a line across a segment boundary: one move per segment, no sorting or filling", () => {
    const [d] = paths(renderToStaticMarkup(<SliceChart station={sliceStation} records={sliceRecords} role="selected"/>));
    expect(d.match(/M/g)).toHaveLength(2);
    expect(d.match(/L/g)).toHaveLength(1);
    expect(d.match(/h0\.01/g)).toHaveLength(1);   // the one-point segment is a dot
  });
  it("keeps every point when the clock line splits a segment, dimming only what follows it", () => {
    const html = renderToStaticMarkup(<SliceChart station={sliceStation} records={sliceRecords} role="selected" cursorMs={at(1.5)}/>), [before, after] = paths(html);
    expect(html).toContain('class="clock-cursor"');
    expect(html).toContain("record-points--after");
    expect(before.match(/M/g)).toHaveLength(1);                      // only the first point is at or before the clock
    expect(after.match(/M/g)).toHaveLength(2); expect(after.match(/L/g)).toHaveLength(1);   // the dimmed line starts at that point
  });
  it("names its product, units and datum, and says so plainly when the file has no rows", () => {
    const html = renderToStaticMarkup(<SliceChart station={sliceStation} records={sliceRecords} role="selected"/>);
    for (const text of ["One-minute water level", "(m)", "Datum: STND"]) expect(html).toContain(text);
    const empty = renderToStaticMarkup(<SliceChart station={{ ...sliceStation, rows: 0 }} records={{ ...sliceRecords, rows: [], segments: [],
      counts: { rows: 0, blank: 0, duplicates_dropped: 0, outside_window: 0, backward_steps: 0 } }} role="selected"/>);
    expect(empty).toContain("This record has no rows in the display window.");
    expect(empty).not.toContain("record-points");
  });
});

describe("SliceSupport and StationCard — what a schema-2 bundle has, and nothing it lacks", () => {
  it("states the coverage of the display window with its rule, the longest supported stretch, the rows and the decoder's counts", () => {
    const html = renderToStaticMarkup(<SliceSupport station={sliceStation} records={sliceRecords}/>);
    for (const text of ["80.3% of the display window", "rule test-rule", "1,067 min", "4 rows", "1 blank row", "1 repeated timestamp", "0 backward time steps"])
      expect(html).toContain(text);
  });
  it("heads the card with the product and hides the schema-1-only source fields", () => {
    const html = renderToStaticMarkup(<StationCard {...card({ station: sliceStation, status: "ready", records: sliceRecords, error: null })}/>);
    for (const text of ["Test La Jolla", "One-minute water level", "vertical datum STND", "test-src", "Rows &amp; sources", "80.3%"]) expect(html).toContain(text);
    for (const text of ["undefined", "time basis", "horizontal datum", "Coastal tide gauge", "Deep-ocean DART", "Source: "]) expect(html).not.toContain(text);
  });
});

describe("EventSelect — every listed event, by origin time", () => {
  const event = (event_id: string, label: string, origin_time_utc: string, magnitude: number): EventEntry => ({ event_id, label, origin_time_utc,
    latitude: 0, longitude: 0, magnitude, magnitude_type: "mww", records: null, layers: null, arrivals: null });
  // The index lists events by origin instant (validateIndex); two share a label within a year, so the date is always the full UTC date.
  const events = [event("a", "Shingū, Japan", "2004-09-05T10:07:07.820Z", 7.2), event("b", "Shingū, Japan", "2004-09-05T14:57:18.610Z", 7.4),
    event("c", "Illapel, Chile", "2015-09-16T22:54:32.860Z", 8.3), event("d", "Tokachi-Oki, Japan", "2003-12-31T23:59:59.5Z", 8.16)];
  it("writes each option as label · full UTC date · magnitude", () => {
    expect(eventOption(events[2])).toBe("Illapel, Chile · 16 September 2015 · M8.3");
    expect(eventOption(events[3])).toBe("Tokachi-Oki, Japan · 31 December 2003 · M8.16");
  });
  it("is a native select labelled Event, in the index's origin order, on the open event, and changes only to another event", () => {
    const onEvent = vi.fn(), tree = nodes(EventSelect({ events: events.slice(0, 3), value: "b", onEvent }));
    const select = tree.find(n => n.type === "select")!;
    expect(tree.find(n => n.type === "label")).toBeDefined();
    // Its accessible name is "Event", not the selected option's text.
    expect(renderToStaticMarkup(<EventSelect events={events.slice(0, 3)} value="b" onEvent={onEvent}/>)).toMatch(/<label[^>]*><span>Event<\/span><select aria-label="Event"/);
    expect(nodes(select.props.children).filter(n => n.type === "option").map(n => n.props.value)).toEqual(["a", "b", "c"]);
    expect(select.props.value).toBe("b");
    select.props.onChange!({ target: { value: "b" } }); expect(onEvent).not.toHaveBeenCalled();
    select.props.onChange!({ target: { value: "c" } }); expect(onEvent).toHaveBeenCalledExactlyOnceWith("c");
  });
});

describe("magnitude text — at least one decimal, the source value never rounded", () => {
  it("writes 7 as M7.0 and keeps 8.16 and 8.3 as given", () => {
    expect([7, 8.16, 8.3, 9.1, 8].map(magnitudeText)).toEqual(["7.0", "8.16", "8.3", "9.1", "8.0"]);
    expect(eventOption({ event_id: "x", label: "Gisborne, New Zealand", origin_time_utc: "2016-09-01T16:37:57.300Z", latitude: 0, longitude: 0, magnitude: 7,
      magnitude_type: "mww", records: null, layers: null, arrivals: null })).toBe("Gisborne, New Zealand · 1 September 2016 · M7.0");
  });
});

describe("map labels stay inside the screen", () => {
  const ORIGIN = "Illapel origin · 22:54 UTC";
  it("leaves out a label whose point is below the bottom edge, as it does past the other edges", () => {
    expect(placeLabel(1207, 1017, ORIGIN, 1440, [], "side", [], 900)).toBeNull();
    expect(placeLabel(1207, 600, ORIGIN, 1440, [], "side", [], 900)).not.toBeNull();
  });
  it("keeps a label whose point is just on screen above the bottom edge", () => {
    expect(placeLabel(600, 905, ORIGIN, 1440, [], "side", [], 900)!.y).toBeLessThanOrEqual(896);
  });
  it("flips a bold label near the right edge before it runs past it, and never pushes one past the left edge", () => {
    expect(placeLabel(1250, 400, ORIGIN, 1440, [], "side", [], 900, true)!.anchor).toBe("end");
    expect(placeLabel(1250, 400, ORIGIN, 1440, [], "side", [], 900)!.anchor).toBe("start");   // the plain estimate still fits
    const flipped = placeLabel(170, 400, "x".repeat(40), 200, [], "side", [], 900, true)!;
    expect(flipped.anchor).toBe("end"); expect(flipped.x - (40 * 7.2 + 4)).toBeGreaterThanOrEqual(-200);
  });
});
