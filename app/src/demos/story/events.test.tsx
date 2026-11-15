import { createHash } from "node:crypto";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventsDemo, loadFirst } from "../DemoApp";
import { eventsSearch, isEventsView, openSearch, parseEvent, parseEventsState, parseState, serializeState } from "../state";
import type { DemoManifest, EventCounts, EventEntry, EventsIndex } from "../types";
import { countsLine, EventList, EventsView, HourStrip, shortCounts, shownEvents, sortEvents, stepEvent, type EventListProps, type EventsViewProps } from "./EventsView";
import { parseStoryParams } from "./url";

// Records the props DemoApp's writer hands the view, and still renders the real view.
const seen = vi.hoisted(() => ({ props: null as unknown }));
vi.mock("./EventsView", async importOriginal => {
  const m = await importOriginal<typeof import("./EventsView")>();
  return { ...m, EventsView: (p: EventsViewProps) => { seen.props = p; return m.EventsView(p); } };
});

// Typed test-only inputs: five events in index order (by origin), with schema-2 positions and counts.
const hours = (at: Record<number, number>) => Array.from({ length: 30 }, (_, h) => at[h] ?? 0);
const counts = (c: Partial<EventCounts> = {}): EventCounts => ({ ntwc_pairs: 0, ntwc_pairs_with_position: 0, ntwc_reported: 0, ncei_reported: 0, stations: 0,
  reported_per_hour: { ntwc: hours({}), ncei: hours({}) }, ...c });
const ref = (bundle_id: string) => ({ bundle_id, manifest_sha256: "0".repeat(64), manifest_bytes: 1 });
const event = (event_id: string, label: string, origin_time_utc: string, magnitude: number, x: number, y: number, extra: Partial<EventEntry> = {}): EventEntry =>
  ({ event_id, label, origin_time_utc, latitude: 0, longitude: 0, magnitude, magnitude_type: "mww", records: null, layers: null, arrivals: null, x, y, counts: counts(), ...extra });
const adak = event("usp0007jcu", "Adak, Alaska", "1996-06-10T04:03:35.480Z", 7.9, -1376848, 6141947,
  { counts: counts({ ncei_reported: 16, reported_per_hour: { ntwc: hours({}), ncei: hours({ 2: 10, 3: 6 }) } }) });
const maule = event("official20100227063411530_30", "Maule, Chile", "2010-02-27T06:34:11.530Z", 8.8, 7572371, -4481726,
  { records: ref("records-maule"), layers: ref("layers-maule"), counts: counts({ ncei_reported: 138, stations: 43, reported_per_hour: { ntwc: hours({}), ncei: hours({ 1: 40, 20: 2 }) } }) });
const tohoku = event("official20110311054624120_30", "Tōhoku, Japan", "2011-03-11T05:46:24.120Z", 9.1, -4947802, 4729696,
  { records: ref("records-tohoku"), layers: ref("layers-tohoku"), arrivals: { path: "story-arrivals-v2/official20110311054624120_30.json", sha256: "c".repeat(64), bytes: 1 },
    counts: counts({ ntwc_pairs: 92, ntwc_pairs_with_position: 8, ntwc_reported: 130, ncei_reported: 273, stations: 10,
      reported_per_hour: { ntwc: hours({ 0: 3, 7: 13 }), ncei: hours({ 0: 33, 1: 29 }) } }) });
const illapel = event("us20003k7a", "Illapel, Chile", "2015-09-16T22:54:32.860Z", 8.3, 7861041, -3951167,
  { records: ref("records-illapel"), layers: ref("layers-illapel"),
    counts: counts({ ntwc_pairs: 67, ntwc_pairs_with_position: 53, ntwc_reported: 110, ncei_reported: 119, stations: 36 }) });
const kirakira = event("us20007z80", "Kirakira, Solomon Islands", "2016-12-08T17:38:46.280Z", 7.8, -3674400, -1368415,
  { records: ref("records-kirakira"), counts: counts({ ntwc_pairs: 5, ntwc_pairs_with_position: 5, ntwc_reported: 10, stations: 5 }) });
const events = [adak, maule, tohoku, illapel, kirakira];
const ids = (list: readonly EventEntry[] | null) => list?.map(e => e.event_id);
const coastBytes = new TextEncoder().encode(JSON.stringify({ schema_version: "1", source_id: "natural-earth-110m-coastline", parts: [[[0, 0], [1000, 0], [0, 1000], [0, 0]]], closed: [true] }));
const index: EventsIndex = { schema_version: "2", evidence_state: "internal_descriptive_only", default_event_id: tohoku.event_id, events,
  basemap: { path: "basemap-v1/coastline.json", bytes: coastBytes.byteLength, sha256: createHash("sha256").update(coastBytes).digest("hex") } };
const coast = { parts: [[[0, 0], [1000, 0], [0, -1000], [0, 0]]], closed: [true] } as EventsViewProps["basemap"];
const noop = () => undefined;
// A hook-free piece: walk its elements to press its buttons (no DOM needed).
type Node = ReactElement<{ children?: ReactNode; onClick?: () => void; onChange?: (e: { target: { value: string } }) => void; "aria-label"?: string }>;
const tree = (node: ReactNode): Node[] => Array.isArray(node) ? node.flatMap(tree) : !isValidElement<Node["props"]>(node) ? []
  : [node, ...(typeof node.type === "function" ? tree((node.type as (p: unknown) => ReactNode)(node.props)) : []), ...tree(node.props.children)];

describe("All events in the URL — view=events, order and has", () => {
  it("knows the mode from the URL's (first) view", () => {
    expect(["?view=events", "?event=us20003k7a&view=events", "?view=events&view=story"].map(isEventsView)).toEqual([true, true, true]);
    expect(["", "?view=story", "?view=times&order=magnitude", "?view=story&view=events"].map(isEventsView)).toEqual([false, false, false, false]);
  });
  it("writes only what is not the default (Tōhoku, date order, all events) and reads back every order and filter", () => {
    expect(parseEventsState("?view=events")).toEqual({ state: { order: "date", has: null }, issues: [] });
    expect(eventsSearch(null, { order: "date", has: null })).toBe("?view=events");
    const url = eventsSearch(illapel.event_id, { order: "magnitude", has: "pairs" });
    expect(url).toBe("?event=us20003k7a&view=events&order=magnitude&has=pairs");
    expect(parseEvent(url, index)).toEqual({ entry: illapel, issues: [] });
    for (const order of ["date", "magnitude", "reports"] as const) for (const has of [null, "records", "contours", "pairs", "ncei"] as const)
      expect(parseEventsState(eventsSearch(null, { order, has }))).toEqual({ state: { order, has }, issues: [] });
  });
  it("repairs an invalid or repeated order or filter with a note", () => {
    expect(parseEventsState("?view=events&order=size&has=everything")).toEqual({ state: { order: "date", has: null },
      issues: ["Invalid order: date order restored.", "Invalid filter: all events shown."] });
    expect(parseEventsState("?view=events&order=reports&order=date").issues).toEqual(["Repeated URL field “order”: first value used."]);
    expect(parseEventsState("?view=events&view=story").issues).toEqual(["Repeated URL field “view”: first value used."]);
  });
  it("ignores station, window, product, sort and clock fields visibly, repairs a step All events does not have, and the URL it writes leaves them out", () => {
    const url = "?view=events&selected=21418&pinned=saip&window=common_day&product=raw_value&sort=distance&t=3&cmp=1&step=2&at=1,2&z=2&from=3&extra=x";
    expect(parseEventsState(url)).toEqual({ state: { order: "date", has: null }, issues: [
      ...["selected", "pinned", "window", "product", "sort", "t", "cmp", "at", "z"].map(k => `URL field “${k}” does not apply to All events and was ignored.`),
      "Unknown URL field “extra” was ignored.", "Invalid story step: free exploration opened.", "Invalid resume step: ignored."] });
    expect(eventsSearch(null, parseEventsState(url).state)).toBe("?view=events");
  });
  it("says that order and has belong to All events when another view's link carries them", () => {
    expect(parseState("?view=story&order=magnitude&has=records", manifest).issues).toEqual(["order", "has"].map(k => `URL field “${k}” applies only to All events and was ignored.`));
  });
  it("keeps every link today's views write byte-identical, and none of them opens All events", () => {
    const old = ["?view=story&selected=1617760&pinned=saip&window=common_day&product=raw_value&t=0&cmp=0&step=1",
      "?view=times&selected=21418&pinned=&window=common_day&product=raw_value&sort=distance&t=7.25&cmp=0&step=explore&at=1,2&z=2&from=4",
      "?event=us20003k7a&view=radial&selected=1617760&pinned=saip&window=common_day&product=raw_value&t=4.5&cmp=1&step=explore"];
    for (const url of old) {
      const { state, issues } = parseState(url, manifest), event = parseEvent(url, index).entry;
      expect([isEventsView(url), issues]).toEqual([false, []]);
      expect(serializeState(state, parseStoryParams(url).params, event === tohoku ? null : event.event_id)).toBe(url);
    }
  });
});
// Two stations: enough for parseState to read today's station fields.
const manifest: DemoManifest = { schema_version: "1", exporter_version: "1", bundle_id: "test-only", evidence_state: "internal_descriptive_only",
  event: { event_id: tohoku.event_id, origin_time_utc: tohoku.origin_time_utc, latitude: 0, longitude: 0 },
  release: { release_id: "test", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy", allowed_uses: [], prohibited_uses: [] },
  default_state: { selectedStationId: "1617760", pinnedStationId: "saip", windowId: "common_day", productKey: "raw_value" },
  windows: [{ id: "common_day", label: "Test day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z" }],
  stations: ["1617760", "21418", "saip"].map(station_id => ({ station_id, source_id: "test", station_type: "coastal" as const, name: station_id, units: "m", vertical_reference: "unknown",
    horizontal_datum: "unknown", coordinate_order: "test", time_basis: "UTC", latitude: 0, longitude: 0, observation_count: 0, products: [],
    source: { source_id: "test", title: "test", publisher: "test", accessed_on: "unknown", version_or_date: "unknown", license_or_terms: "unknown", processing_level: "test", sha256: "0".repeat(64), url: null } })),
  assets: [], geometry_path: "geometry.json", input_fingerprints: [], config_sha256: "0".repeat(64),
  accounting: { source_observation_count: 0, exported_observation_count: 0, station_count: 3, rejected_observation_count: 0 } };

describe("the event list's order and filter", () => {
  it("orders by date (the index's order), by magnitude or by number of reported times, largest first", () => {
    expect(ids(sortEvents(events, "date"))).toEqual(ids(events));
    expect(ids(sortEvents(events, "magnitude"))).toEqual(ids([tohoku, maule, illapel, adak, kirakira]));
    // NTWC + NCEI reported counts only order the rows: 403, 229, 138, 16, 10
    expect(ids(sortEvents(events, "reports"))).toEqual(ids([tohoku, illapel, maule, adak, kirakira]));
    expect(ids(events)).toEqual(ids([adak, maule, tohoku, illapel, kirakira])); // sorting never reorders the index
  });
  it("filters by each kind of listed evidence, in the current order", () => {
    expect(ids(shownEvents(events, "date", null))).toEqual(ids(events));
    expect(ids(shownEvents(events, "date", "records"))).toEqual(ids([maule, tohoku, illapel, kirakira]));
    expect(ids(shownEvents(events, "date", "contours"))).toEqual(ids([maule, tohoku, illapel]));
    expect(ids(shownEvents(events, "magnitude", "pairs"))).toEqual(ids([tohoku, illapel, kirakira]));
    expect(ids(shownEvents(events, "reports", "ncei"))).toEqual(ids([tohoku, illapel, maule, adak]));
  });
  it("steps through the current order and filter, wrapping at the ends, from a hidden selection too", () => {
    const step = (order: "date" | "magnitude" | "reports", has: "contours" | null, from: EventEntry, d: 1 | -1) => stepEvent(events, order, has, from.event_id, d)?.event_id;
    expect([step("date", null, tohoku, 1), step("date", null, tohoku, -1)]).toEqual([illapel.event_id, maule.event_id]);
    expect([step("magnitude", null, tohoku, 1), step("magnitude", null, tohoku, -1)]).toEqual([maule.event_id, kirakira.event_id]);
    expect([step("date", "contours", adak, 1), step("date", "contours", kirakira, 1), step("date", "contours", adak, -1)]).toEqual([maule.event_id, maule.event_id, illapel.event_id]);
    expect(stepEvent([tohoku, adak], "date", "contours", tohoku.event_id, 1)).toBeNull(); // the selected event is the only one shown
  });
});

describe("the fixed wording of the counts", () => {
  it("states the index's counts in full in the arms, NTWC and NCEI apart", () => {
    expect(countsLine(tohoku.counts!)).toBe("92 estimate–reported pairs in the NTWC table · 8 with a reviewed position · 130 NTWC reported times · 273 NCEI reported times · 10 station records");
    expect(countsLine(counts({ ntwc_pairs: 1, ntwc_reported: 1, ncei_reported: 1, stations: 1 })))
      .toBe("1 estimate–reported pair in the NTWC table · 0 with a reviewed position · 1 NTWC reported time · 1 NCEI reported time · 1 station record");
  });
  it("shortens them per source in a row, and names listed contours", () => {
    expect(shortCounts(tohoku)).toBe("NTWC: 130 reported, 92 pairs · NCEI: 273 reported · 10 station records · published contours");
    expect(shortCounts(adak)).toBe("NTWC: 0 reported, 0 pairs · NCEI: 16 reported · 0 station records");
    expect(shortCounts(kirakira)).toBe("NTWC: 10 reported, 5 pairs · NCEI: 0 reported · 5 station records");
  });
});

describe("the two-row hour strip", () => {
  const rows = (html: string) => html.split('class="events-strip__row"').slice(1);
  const bars = (row: string) => [...row.matchAll(/<rect data-n="(\d+)"/g)].map(m => Number(m[1]));
  it("draws NTWC above NCEI, one bar per source and clock hour, never adding the two", () => {
    const html = renderToStaticMarkup(<HourStrip perHour={tohoku.counts!.reported_per_hour}/>), [ntwc, ncei] = rows(html);
    expect(ntwc).toContain(">NTWC<"); expect(ncei).toContain(">NCEI<");
    expect([bars(ntwc), bars(ncei)]).toEqual([[3, 13], [33, 29]]);   // hour 0 has 3 and 33, never 36
    expect(html).not.toContain('data-n="36"');
    expect(rows(renderToStaticMarkup(<HourStrip perHour={adak.counts!.reported_per_hour}/>)).map(bars)).toEqual([[], [10, 6]]);
  });
  it("labels each row with its own total on the 30-hour clock and puts the clock bar's hour ticks under the arm's strip", () => {
    const html = renderToStaticMarkup(<HourStrip perHour={tohoku.counts!.reported_per_hour} big/>);
    expect(html).toContain('aria-label="NTWC: 16 reported times by clock hour, 0 to 30 h"');
    expect(html).toContain('aria-label="NCEI: 62 reported times by clock hour, 0 to 30 h, counted from NCEI&#x27;s origin"');
    for (const h of [0, 5, 10, 15, 20, 25, 30]) expect(html).toContain(`>${h} h</text>`);
    expect(renderToStaticMarkup(<HourStrip perHour={tohoku.counts!.reported_per_hour}/>)).not.toContain(" h</text>");
  });
});

describe("the event list", () => {
  const list = (extra: Partial<EventListProps> = {}) => {
    const onSelect = vi.fn(), onOrder = vi.fn(), onHas = vi.fn();
    const props: EventListProps = { events, selected: tohoku, order: "date", has: null, onSelect, onOrder, onHas, ...extra };
    return { onSelect, onOrder, onHas, nodes: tree(EventList(props)), html: renderToStaticMarkup(<EventList {...props}/>) };
  };
  const row = (nodes: Node[], e: EventEntry) => nodes.find(n => n.type === "li" && n.key === e.event_id)!.props.children as Node;
  const button = (nodes: Node[], text: string) => nodes.find(n => n.type === "button" && n.props.children === text)!;
  it("lists every event as a button in an ordered list: label, full UTC date, magnitude, counts and strip; the selected row is marked", () => {
    const { html } = list();
    expect(html.match(/<li><button type="button" class="events-row"/g)).toHaveLength(5);
    expect(html.match(/aria-current="true"/g)).toHaveLength(1);
    expect(html).toContain('<button type="button" class="events-row" aria-current="true"><span class="events-row__name"><b>Tōhoku, Japan</b></span>'
      + '<span class="events-row__meta">11 March 2011 · M9.1</span><span class="events-row__counts">NTWC: 130 reported, 92 pairs · NCEI: 273 reported · 10 station records · published contours</span>');
    expect(html).toContain("<b>Maule, Chile</b></span><span class=\"events-row__meta\">27 February 2010 · M8.8</span>");
    expect(html.indexOf("<ol")).toBeLessThan(html.indexOf("events-row"));
  });
  it("says how many of all the events it shows", () => {
    expect(list().html).toContain(">5 of 5 events<");
    expect(list({ has: "contours" }).html).toContain(">3 of 5 events<");
    expect(list({ has: "contours" }).html.match(/class="events-row"/g)).toHaveLength(3);
  });
  it("pressing a row (a native button: click, Enter or Space) selects it with one push; pressing the selected row does nothing", () => {
    const { nodes, onSelect } = list();
    row(nodes, illapel).props.onClick!();
    row(nodes, tohoku).props.onClick!();
    expect(onSelect.mock.calls).toEqual([[illapel.event_id, "push"]]);
  });
  it("orders with three pressed buttons and filters with a select, each an explicit change", () => {
    const { nodes, onOrder, onHas } = list();
    button(nodes, "Magnitude").props.onClick!(); button(nodes, "Number of reported times").props.onClick!(); button(nodes, "Date").props.onClick!();
    expect(onOrder.mock.calls).toEqual([["magnitude"], ["reports"]]);
    const show = nodes.find(n => n.type === "select" && n.props["aria-label"] === "Show")!;
    show.props.onChange!({ target: { value: "records" } }); show.props.onChange!({ target: { value: "" } });
    expect(onHas.mock.calls).toEqual([["records"], [null]]);
    expect(list().html).toContain('<option value="" selected="">All events</option><option value="records">With station records</option><option value="contours">With published contours</option>'
      + '<option value="pairs">With estimate–reported pairs</option><option value="ncei">With NCEI reported times</option>');
  });
  it("Previous and Next step through the current order and filter with one push each", () => {
    const { nodes, onSelect } = list({ order: "magnitude" });
    button(nodes, "Next event ›").props.onClick!(); button(nodes, "‹ Previous event").props.onClick!();
    expect(onSelect.mock.calls).toEqual([[maule.event_id, "push"], [kirakira.event_id, "push"]]);
  });
  it("keeps a selected event the filter hides, and says so in one line", () => {
    const { html } = list({ selected: adak, has: "contours" });
    expect(html).toContain("The selected event, Adak, Alaska, is hidden by this filter.");
    expect(html).not.toContain("aria-current");
    expect(list().html).not.toContain("hidden by this filter");
  });
});

describe("the All events stage", () => {
  const view = (extra: Partial<EventsViewProps> = {}) => renderToStaticMarkup(<EventsView events={events} selected={tohoku} order="date" has={null} basemap={coast}
    issues={[]} onDismissIssues={noop} restoreKey={0} onSelect={noop} onOrder={noop} onHas={noop} onOpen={noop} onStep={noop} initialSize={{ w: 1440, h: 900 }} {...extra}/>);
  const sizes = [{ w: 1440, h: 900 }, { w: 390, h: 844 }];
  it("puts every epicentre on the basemap, rests the lens on the selected one, and names only the lens subject", () => {
    for (const initialSize of sizes) {
      const html = view({ initialSize });
      expect(html.match(/class="story-epicentre events-star"/g), `${initialSize.w}`).toHaveLength(5);
      expect(html).toContain('class="story-land" d="M0 0L1000 0L0 -1000L0 0Z"');
      expect(html).toContain('<p class="story-lens-title__name">Tōhoku, Japan</p><p class="story-lens-title__sub">11 March 2011 · M9.1</p>');
      expect(html).not.toContain('class="story-label');
      expect(html).toContain("the lens is on Tōhoku, Japan · 11 March 2011 · M9.1.");
    }
    expect(view({ selected: illapel })).toContain('<p class="story-lens-title__name">Illapel, Chile</p><p class="story-lens-title__sub">16 September 2015 · M8.3</p>');
  });
  it("shows the selected event's counts, its contour line, its hour strip and one sentence of reading guidance in the arms", () => {
    const html = view();
    expect(html).toContain(countsLine(tohoku.counts!));
    expect(html).toContain(">Published contours listed<");
    expect(html).toContain("Bars count reported times by clock hour after the origin; NCEI hours count from NCEI&#x27;s origin.");
    expect(html).toContain('aria-label="NTWC: 16 reported times by clock hour, 0 to 30 h"');
    expect(view({ selected: adak })).toContain(">No published contours listed<");
  });
  it("replaces the view switch with Open this event, keeps the event select, and has no clock", () => {
    for (const initialSize of sizes) {
      const html = view({ initialSize }), panel = html.slice(html.indexOf("story-panel story-compare"));
      expect(html).not.toContain('class="story-views"');
      expect(panel).toMatch(/^story-panel story-compare"[^>]*><button type="button" class="events-open">Open this event<\/button>/);
      expect(panel).toContain('<option value="official20110311054624120_30" selected="">Tōhoku, Japan · 11 March 2011 · M9.1</option>');
      expect(html).not.toMatch(/story-clockbar|type="range"|All events<\/button>/);
    }
  });
  it("lists the events in the column when wide and in the phone sheet under the map at 390×844", () => {
    const wide = view(), phone = view({ initialSize: { w: 390, h: 844 } });
    expect(wide).toMatch(/<aside class="story-column events-column"[^>]*>.*class="events-list"/);
    expect(wide).not.toContain('class="story-sheet ');
    const sheet = phone.slice(phone.indexOf('class="story-sheet story-sheet--narrow'));
    expect(sheet).toContain('class="events-list"');
    expect(sheet.match(/class="events-row"/g)).toHaveLength(5);
    expect(phone.indexOf('class="story-map"')).toBeLessThan(phone.indexOf('class="story-sheet '));
  });
  it("keeps a selected event the filter hides under the lens and in the arms", () => {
    const html = view({ selected: adak, has: "contours" });
    expect(html).toContain('<p class="story-lens-title__name">Adak, Alaska</p>');
    expect(html).toContain("The selected event, Adak, Alaska, is hidden by this filter.");
    expect(html).toContain(">3 of 5 events<");
  });
  it("shows the link repair note with Dismiss", () => {
    expect(view({ issues: ["Invalid order: date order restored."] })).toContain("<li>Invalid order: date order restored.</li>");
  });
  it("never words a time as an arrival, a measurement, an error, late or a warning time", () => {
    for (const initialSize of sizes) for (const selected of events) {
      const visible = view({ initialSize, selected }).replace(/<[^>]*>/g, " ");
      expect(visible).not.toMatch(/\b(arrivals?|measured|error|wrong|late|warning time)\b/i);
    }
  });
});

describe("DemoApp's All events writer", () => {
  const history = { state: null as unknown, pushState: vi.fn(), replaceState: vi.fn() };
  afterEach(() => { vi.unstubAllGlobals(); history.pushState.mockReset(); history.replaceState.mockReset(); });
  const open = (search: string) => {
    vi.stubGlobal("window", { location: { search, pathname: "/demos.html", hash: "" }, history, innerWidth: 1440, innerHeight: 900 });
    const onLeave = vi.fn(), { entry, issues } = parseEvent(search, index);
    renderToStaticMarkup(<EventsDemo index={index} entry={entry} basemap={coast} issues={issues} onLeave={onLeave}/>);
    return { p: seen.props as EventsViewProps, onLeave };
  };
  const urls = (f: typeof history.pushState) => f.mock.calls.map(c => c[2]);
  it("opens on the URL's event, order and filter", () => {
    const { p } = open("?event=us20003k7a&view=events&order=reports&has=pairs");
    expect([p.selected, p.order, p.has, p.issues]).toEqual([illapel, "reports", "pairs", []]);
    expect(open("?view=events&t=3").p.issues).toEqual(["URL field “t” does not apply to All events and was ignored."]);
  });
  it("a pick pushes one entry, a lens settle replaces it, and order and filter push, each with the screen's whole URL", () => {
    const { p } = open("?view=events&order=magnitude");
    p.onSelect(illapel.event_id, "push");
    expect(urls(history.pushState)).toEqual(["/demos.html?event=us20003k7a&view=events&order=magnitude"]);
    p.onSelect(adak.event_id, "replace");
    expect(urls(history.replaceState)).toEqual(["/demos.html?event=usp0007jcu&view=events&order=magnitude"]);
    p.onSelect(tohoku.event_id, "push");   // already selected: nothing written
    p.onOrder("reports"); p.onHas("records");
    expect(urls(history.pushState)).toEqual(["/demos.html?event=us20003k7a&view=events&order=magnitude", "/demos.html?view=events&order=reports",
      "/demos.html?view=events&order=magnitude&has=records"]);
  });
  it("Open this event pushes the selected event's Story view in free exploration, then hands over to DemoApp", () => {
    const { p, onLeave } = open("?event=us20003k7a&view=events&has=pairs");
    p.onOpen();
    expect(urls(history.pushState)).toEqual(["/demos.html?event=us20003k7a&view=story&t=0&cmp=0&step=explore"]);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });
  it("builds the Story link through the event-change path: the event's defaults, free exploration, the default event omitted", () => {
    expect(openSearch(tohoku, index)).toBe("?view=story&t=0&cmp=0&step=explore");
    expect(openSearch(adak, index)).toBe("?event=usp0007jcu&view=story&t=0&cmp=0&step=explore");
    expect(parseStoryParams(openSearch(tohoku, index)).params.step).toBe("explore");
    expect(parseEvent(openSearch(adak, index), index)).toEqual({ entry: adak, issues: [] });
  });
});

describe("the first screen's requests", () => {
  it("All events fetches only the events index and the shared basemap, never a records, contours or reported-times file", async () => {
    const asked: string[] = [];
    const request = async (u: string | URL | Request) => { asked.push(String(u)); return new Response(String(u) === "/data/events.json" ? JSON.stringify(index) : coastBytes); };
    const first = await loadFirst("?event=us20003k7a&view=events", undefined, request);
    expect(asked).toEqual(["/data/events.json", "/data/basemap-v1/coastline.json"]);
    expect(first.manifest).toBeNull();
    expect(first.entry.event_id).toBe(illapel.event_id);
    expect(first.manifest === null && first.basemap.parts).toHaveLength(1);
    // Any other view loads its event's records instead (none for an event without a records bundle), and no basemap here.
    asked.length = 0; await loadFirst("?event=usp0007jcu&view=story", undefined, request);
    expect(asked).toEqual(["/data/events.json"]);
  });
});
