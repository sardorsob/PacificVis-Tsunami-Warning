import { createHash } from "node:crypto";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { eventsIndex, localFetch, readDemoJson, readLayersBytes, readLayersJson, tohokuEntry } from "../integration-data";
import { decodeStation, validateGeometry, validateManifest } from "../loader";
import { RecordChart } from "../RecordChart";
import { linkedReports, loadArrivals } from "./arrivals";
import { ArrivalsView } from "./ArrivalsView";
import { loadLayers, nearestHours, validateCoastline, validateContours, validateLayersManifest } from "./layers";
import { validateSteps } from "./steps";
import { StoryView } from "./StoryView";
import { kicker } from "./ClockColumn";
import { eventOption } from "./ViewSwitch";
import { ThreeClocks } from "./ThreeClocks";
import { StationCard } from "../StationCard";
import { loadBasemap, loadGeometry, loadStation, loadViewManifest } from "../slices";
import { loadFirst } from "../DemoApp";
import { parseEvent, parseState } from "../state";
import { EventsView } from "./EventsView";
import type { AnySelection, AnyStation, DemoGeometry, EventEntry, StationSelection } from "../types";

const manifest = validateManifest(readDemoJson("manifest.json"), tohokuEntry);
const layers = validateLayersManifest(readLayersJson("manifest.json"), tohokuEntry);

describe("story view against the accepted local bundles", () => {
  it("loads the layers bundle the index pins, through its verified manifest, and refuses other manifest bytes", async () => {
    const loaded = await loadLayers(tohokuEntry, undefined, localFetch);
    expect(loaded.manifest).toEqual(layers); expect(loaded.contours.length).toBe(72);
    expect(loaded.manifest.contour_source_id).toBe("ncei-ttt-tohoku-layer17-geojson");
    await expect(loadLayers({ ...tohokuEntry, layers: { ...tohokuEntry.layers!, manifest_sha256: "0".repeat(64) } }, undefined, localFetch)).rejects.toThrow(/hash/);
  });
  it("verifies both layer assets byte-for-byte against their manifest", () => {
    for (const asset of layers.assets) {
      const bytes = readLayersBytes(asset.path);
      expect(bytes.byteLength).toBe(asset.bytes);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(asset.sha256);
    }
  });
  it("loads all 72 published contour features with the source's own hour gaps", () => {
    const contours = validateContours(readLayersJson("contours.json"), layers);
    expect(contours.length).toBe(72);
    const hours = [...new Set(contours.map(f => f.hours))];
    expect(hours).toEqual(layers.accounting.hours);
    expect(hours.includes(71) || hours.includes(72) || hours.includes(73)).toBe(false);
    expect(validateCoastline(readLayersJson("coastline.json"), layers).parts.length).toBe(layers.accounting.coastline_parts);
  });
  it("carries the G1 reading statement with the layer", () => {
    expect(layers.statement).toContain("not the full rupture");
    expect(layers.statement).toContain("not warning time");
    expect(layers.hours_semantics).toContain("USGS origin time");
  });
  it("opens steps 1–2 on the epicentre at every screen size, though DART 21418 is 556 km away", () => {
    const geometry = readDemoJson("geometry.json") as DemoGeometry, noop = () => undefined;
    const station = manifest.stations.find(s => s.station_id === manifest.default_state.selectedStationId)!;
    for (const initialSize of [{ w: 390, h: 844 }, { w: 667, h: 375 }, { w: 768, h: 1024 }, { w: 1440, h: 900 }]) {
      const html = renderToStaticMarkup(<StoryView manifest={manifest} geometry={geometry} geometryError={null} layers={null} layersError={null}
        layersPending={null} onRetryLayers={noop} state={{ view: "story", ...manifest.default_state }}
        selected={{ station, status: "loading", records: null, error: null }} pinned={null} onOpenEvidence={noop}
        onRetryStation={noop} onRetryGeometry={noop} params={{ t: 0, compare: false, step: 1, at: null, z: 1, from: null }}
        onNav={noop} restoreKey={0} evidenceOpen={false} issues={[]} onDismissIssues={noop} onState={noop} entry={tohokuEntry} events={eventsIndex.events} onEvent={noop} onAllEvents={noop} initialSize={initialSize}/>);
      expect(html, `${initialSize.w}×${initialSize.h}`).toContain('story-lens-title__name">Tōhoku epicentre<');
    }
  });
  it("loads the reported-times file the index pins and draws only what its rules allow, faint at 0 h and lit at 30 h", async () => {
    const arrivals = (await loadArrivals(tohokuEntry, undefined, localFetch))!, a = arrivals.accounting;
    expect([arrivals.reports.length, arrivals.places.length, a.ntwc_rows_with_both_times, a.ntwc_pairs_with_position, a.ncei_reported_durations])
      .toEqual([411, 280, 92, 8, 273]);
    await expect(loadArrivals({ ...tohokuEntry, arrivals: { ...tohokuEntry.arrivals!, sha256: "0".repeat(64) } }, undefined, localFetch)).rejects.toThrow(/hash/);
    // Expected from the file's own rules: a listed place and 0 ≤ minutes < 30 h; a ring per published estimate, a dot per reported time.
    const placed = arrivals.reports.filter(r => r.site_id !== null), drawn = (m: number | null) => m !== null && m >= 0 && m < 1800;
    const expected = (lit: (m: number) => boolean) => { const ok = (m: number | null) => drawn(m) && lit(m!);
      return { estimate: placed.filter(r => ok(r.estimate_minutes)).length, ntwc: placed.filter(r => r.source === "ntwc" && ok(r.reported_minutes)).length,
        tide: placed.filter(r => r.gauge_kind === "tide_gauge" && ok(r.reported_minutes)).length,
        deep: placed.filter(r => r.gauge_kind === "deep_ocean_gauge" && ok(r.reported_minutes)).length }; };
    const geometry = validateGeometry(readDemoJson("geometry.json"), manifest), noop = () => undefined;
    const station = manifest.stations.find(s => s.station_id === manifest.default_state.selectedStationId)!;
    const html = (t: number) => renderToStaticMarkup(<StoryView manifest={manifest} geometry={geometry} geometryError={null} layers={null} layersError={null}
      layersPending={null} onRetryLayers={noop} state={{ view: "story", ...manifest.default_state }} selected={{ station, status: "loading", records: null, error: null }}
      pinned={null} onOpenEvidence={noop} onRetryStation={noop} onRetryGeometry={noop} params={{ t, compare: false, step: "explore", at: null, z: 1, from: null }}
      onNav={noop} restoreKey={0} evidenceOpen={false} issues={[]} onDismissIssues={noop} onState={noop} entry={tohokuEntry} events={eventsIndex.events} onEvent={noop} onAllEvents={noop} initialSize={{ w: 390, h: 844 }} arrivals={arrivals}/>);
    // Map marks only: the column key draws the same glyphs.
    const tally = (s: string, litOnly: boolean) => { const out = { estimate: 0, ntwc: 0, tide: 0, deep: 0 }, map = s.slice(s.indexOf('class="story-reports"'));
      for (const m of map.slice(0, map.indexOf("</g>")).matchAll(/class="story-report story-report--(\w+)( story-report--on)?"/g))
        if (!litOnly || m[2]) out[m[1] as keyof typeof out]++;
      return out; };
    const start = html(0), end = html(30);
    expect(tally(start, false)).toEqual(expected(() => true));
    expect(tally(start, true)).toEqual(expected(m => m <= 0));
    expect(tally(end, true)).toEqual(expected(() => true));
    expect(end).toContain(`${a.ntwc_rows_with_both_times} estimate–reported pairs in the NTWC table · ${a.ntwc_pairs_with_position} with a reviewed position · `
      + `${a.ncei_reported_durations} NCEI reported times`);
    const times = (r: (typeof placed)[number]) => [r.reported_minutes, r.estimate_minutes].filter(m => m !== null);
    expect(placed.filter(r => times(r).some(m => m < 0))).toHaveLength(0);
    expect(end).toContain(`Listed reports not drawn on the map: ${arrivals.reports.length - placed.length} without a place · `
      + `${placed.filter(r => times(r).some(m => m >= 1800)).length} after the 30-hour clock ends.`);
  });
  it("lists every reported time in the Reported times view, NTWC and NCEI apart, with the file's own counts, in either order", async () => {
    const arrivals = (await loadArrivals(tohokuEntry, undefined, localFetch))!, a = arrivals.accounting, noop = () => undefined;
    const state = { view: "times" as const, ...manifest.default_state };
    const page = (sort: "time" | "distance") => renderToStaticMarkup(<ArrivalsView manifest={manifest} geometry={null} geometryError={null} layers={null}
      layersError={null} layersPending={null} onRetryLayers={noop} state={{ ...state, sort }} selected={{ station: manifest.stations[0], status: "loading",
        records: null, error: null }} pinned={null} onOpenEvidence={noop} onRetryStation={noop} onRetryGeometry={noop}
      params={{ t: 0, compare: false, step: "explore", at: null, z: 1, from: null }} onNav={noop} restoreKey={0} evidenceOpen={false} issues={[]}
      onDismissIssues={noop} onState={noop} entry={tohokuEntry} events={eventsIndex.events} onEvent={noop} onAllEvents={noop} arrivals={arrivals}/>);
    const ntwc = arrivals.reports.filter(r => r.source === "ntwc"), rows = (html: string) => (html.match(/class="ladder-row"/g) ?? []).length;
    for (const sort of ["time", "distance"] as const) {
      const html = page(sort), split = html.indexOf('aria-label="Reported by NCEI');
      expect([rows(html.slice(0, split)), rows(html.slice(split))], sort).toEqual([ntwc.length, a.ncei_reported_durations]);
    }
    expect([ntwc.length, a.ncei_reported_durations]).toEqual([138, 273]);
    const html = page("time");
    expect(html).toContain(`${a.ntwc_rows_with_both_times} estimate–reported pairs in the NTWC table · ${a.ntwc_pairs_with_position} with a reviewed position · `
      + `${ntwc.filter(r => r.site_id === null).length} NTWC reports without a place · ${a.ncei_reported_durations} NCEI reported times`);
    expect(html).toContain("92 estimate–reported pairs in the NTWC table · 8 with a reviewed position · 130 NTWC reports without a place · 273 NCEI reported times");
    // Listed but not drawn, from the file's own values: the one report after 30 h keeps its row and its note.
    const late = arrivals.reports.filter(r => [r.reported_minutes, r.estimate_minutes].some(m => m !== null && m >= 1800)).length;
    expect(html).toContain(`Listed rows not drawn on the ladder: ${late} after the 30-hour clock ends.`);
    expect(html.match(/class="ladder-row__note">Reported after the 30-hour clock ends\./g)).toHaveLength(late);
    expect(html.match(/class="story-lane__join"/g)).toHaveLength(ntwc.filter(r => r.reported_minutes !== null && r.estimate_minutes !== null).length);
  });
  it("gives a strip entry to exactly the story stations the file links, one lane per linked report", async () => {
    const arrivals = (await loadArrivals(tohokuEntry, undefined, localFetch))!;
    const linked = new Set(arrivals.places.flatMap(p => p.record ? [p.record.station_id] : []));
    for (const s of manifest.stations) {
      const html = renderToStaticMarkup(<ThreeClocks arrivals={arrivals} t={0} stations={[{ id: s.station_id, name: s.name }]}/>);
      expect((html.match(/class="story-lane"/g) ?? []).length, s.station_id).toBe(linkedReports(arrivals, s.station_id).length);
      expect(html.includes("No reported times are linked to this station."), s.station_id).toBe(!linked.has(s.station_id));
    }
    expect(manifest.stations.filter(s => linked.has(s.station_id)).length).toBeGreaterThan(0);
  });
  it("authors every guided step against real station ids", () => {
    expect(() => validateSteps(manifest.stations.map(s => s.station_id))).not.toThrow();
  });
  it("names published hours near Hilo without interpolating a time", () => {
    const contours = validateContours(readLayersJson("contours.json"), layers);
    const geometry = readDemoJson("geometry.json") as { points: { id: string; x: number; y: number }[] };
    const hilo = geometry.points.find(p => p.id === "1617760")!;
    const reading = nearestHours(contours, hilo.x, -hilo.y, 450_000);
    expect(reading).not.toBeNull();
    expect(Number.isInteger(reading!.a) && Number.isInteger(reading!.b)).toBe(true);
  });
  it("marks the story clock on Hilo's real record without dropping a point", () => {
    const station = manifest.stations.find(s => s.station_id === "1617760")!;
    const records = decodeStation(readDemoJson("stations/1617760.json"), station, manifest);
    const props = { station, records, windowId: "common_day", productKey: "raw_value" as const, role: "selected" as const };
    const cursorMs = Date.parse(manifest.event.origin_time_utc) + 7.5 * 3_600_000;
    const plain = renderToStaticMarkup(<RecordChart {...props}/>), timed = renderToStaticMarkup(<RecordChart {...props} cursorMs={cursorMs}/>);
    const dots = (html: string) => (html.match(/h0\.01/g) ?? []).length;
    expect(timed).toContain("clock-cursor");
    expect(dots(timed)).toBe(dots(plain));
    expect(dots(plain)).toBeGreaterThan(1000);
  });

  // Station lens (ported from the retired radial real-data tests): full cards on the shared clock, real values kept.
  const lensView = (selectedStationId: string, windowId: string) => {
    const geometry = validateGeometry(readDemoJson("geometry.json"), manifest), noop = () => undefined;
    const pick = (id: string): StationSelection => { const station = manifest.stations.find(s => s.station_id === id)!;
      return { station, status: "ready", error: null, records: decodeStation(readDemoJson(`stations/${id}.json`), station, manifest) }; };
    const state = { ...manifest.default_state, view: "radial" as const, selectedStationId, windowId };
    const props = { manifest, geometry, geometryError: null, layers: null, layersError: null, layersPending: null, onRetryLayers: noop, state,
      selected: pick(selectedStationId), pinned: pick(state.pinnedStationId!), onOpenEvidence: noop, onRetryStation: noop,
      onRetryGeometry: noop, params: { t: 7.5, compare: false, step: 1 as const, at: null, z: 1, from: null }, onNav: noop, restoreKey: 0,
      evidenceOpen: false, issues: [], onDismissIssues: noop, onState: noop, initialSize: { w: 1440, h: 900 }, entry: tohokuEntry, events: eventsIndex.events,
      onEvent: noop, onAllEvents: noop };
    const cursorMs = Date.parse(manifest.event.origin_time_utc) + 7.5 * 3_600_000;
    const card = (selection: StationSelection, role: "selected" | "pinned") => renderToStaticMarkup(<StationCard selection={selection} role={role}
      windowId={windowId} productKey={state.productKey} cursorMs={cursorMs} onOpenEvidence={noop} onRetryStation={noop}/>);
    return { html: renderToStaticMarkup(<StoryView {...props}/>), cards: [card(props.selected, "selected"), card(props.pinned, "pinned")] };
  };
  it("Station lens shows Hilo's and Saipan's real cards on the shared clock without reprocessing", () => {
    const { html, cards } = lensView("1617760", "common_day");
    for (const card of cards) expect(html).toContain(card);
    for (const value of ["98.0556", "44.7222", "53.0556"]) expect(html).toContain(value);
  });
  it("Station lens keeps station-specific full-source intervals and DART non-applicable grid support", () => {
    const { html, cards } = lensView("21418", "source_full");
    for (const card of cards) expect(html).toContain(card);
    for (const text of ["Full source record — station-specific bounds", "not a common comparison period", "Strict coastal-grid coverage",
      "Not applicable", "m water column"]) expect(html).toContain(text);
    expect(manifest.release)
      .toMatchObject({ arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy" });
  });
});

// Every listed event, opened the way DemoApp opens one: the manifest by its schema (or none), geometry and basemap, contours when listed,
// the reported-times file, and station A's record.
const noop = () => undefined, byId = (id: string) => eventsIndex.events.find(e => e.event_id === id)!;
async function open(entry: EventEntry) {
  const manifest = await loadViewManifest(entry, undefined, localFetch);
  const [geometry, basemap, layers, arrivals] = await Promise.all([loadGeometry(manifest, entry, undefined, localFetch), loadBasemap(eventsIndex, undefined, localFetch),
    entry.layers ? loadLayers(entry, undefined, localFetch) : null, loadArrivals(entry, undefined, localFetch)]);
  const { state, issues } = parseState(entry.event_id === eventsIndex.default_event_id ? "" : `?event=${entry.event_id}`, manifest);
  const station = (manifest.stations as readonly AnyStation[]).find(s => s.station_id === state.selectedStationId);
  const selected = station && manifest.schema_version !== null
    ? { station, status: "ready", error: null, records: await loadStation(manifest, station.station_id, undefined, localFetch) } as AnySelection : null;
  return { manifest, geometry, basemap, layers, arrivals, state, issues, selected };
}
const stage = (entry: EventEntry, o: Awaited<ReturnType<typeof open>>, t = 30, view: "story" | "radial" = "story", size = { w: 1440, h: 900 }) =>
  renderToStaticMarkup(<StoryView manifest={o.manifest} geometry={o.geometry}
  geometryError={null} basemap={o.basemap} layers={o.layers} layersError={null} layersPending={null} onRetryLayers={noop} state={{ ...o.state, view }} selected={o.selected}
  pinned={null} onOpenEvidence={noop} onRetryStation={noop} onRetryGeometry={noop} params={{ t, compare: false, step: "explore", at: null, z: 1, from: null }}
  onNav={noop} restoreKey={0} evidenceOpen={false} issues={[]} onDismissIssues={noop} onState={noop} entry={entry} events={eventsIndex.events} onEvent={noop} onAllEvents={noop}
  initialSize={size} arrivals={o.arrivals}/>);
const playOff = /<button[^>]*class="story-play"[^>]*disabled/;

describe("every listed event opens", () => {
  it("opens all 49 index entries through the app's loading path, with nothing to repair, and draws each on the stage", async () => {
    const kinds = { records: 0, schema2: 0, layers: 0, none: 0 };
    for (const entry of eventsIndex.events) {
      const o = await open(entry);
      expect(o.issues, entry.event_id).toEqual([]);
      if (o.manifest.schema_version === null) kinds.none++; else { kinds.records++; expect(o.selected?.records, entry.event_id).toBeTruthy(); }
      if (o.manifest.schema_version === "2") kinds.schema2++;
      if (o.layers) kinds.layers++;
      expect(stage(entry, o), entry.event_id).toContain(`<p class="story-kicker">${kicker(entry.origin_time_utc)}</p>`);
    }
    expect([eventsIndex.events.length, kinds]).toEqual([49, { records: 14, schema2: 13, layers: 8, none: 35 }]);
  }, 120_000);
  it("opens Illapel on La Jolla, whose strip gives NTWC's difference and names the record as this station's", async () => {
    const entry = byId("us20003k7a"), o = await open(entry), html = stage(entry, o, 7.5);
    expect(o.state.selectedStationId).toBe("9410230");
    expect(html).toContain('role="group" aria-label="Reported times linked to La Jolla"');
    expect(html).toContain("NTWC: reported 15 min after the published estimate · this station&#x27;s record.");
    expect(html).toContain("record from a station within 1 km, not verified as the same instrument");
    expect(o.layers?.contours.length).toBeGreaterThan(0);
  });
  it("opens Haida Gwaii (records, no contours listed) with the clock on and a calm note", async () => {
    const entry = byId("usp000juhz"), html = stage(entry, await open(entry), 7.5);
    expect(entry.layers).toBeNull();
    expect(html).not.toMatch(playOff);
    expect(html).toContain("No published travel-time contours are listed for this event.");
    expect(html).toContain('class="record-chart"');
  });
  it("opens Adak (no records, no contours) on its epicentre with its reported marks and no records", async () => {
    const entry = byId("usp0007jcu"), o = await open(entry), html = stage(entry, o);
    expect([entry.records, entry.layers, o.manifest.stations.length]).toEqual([null, null, 0]);
    expect(html).toContain('story-lens-title__name">Adak epicentre<');
    expect(html).toContain("No station records are published for this event.");
    const map = html.slice(html.indexOf('class="story-reports"'));
    expect((map.slice(0, map.indexOf("</g>")).match(/class="story-report /g) ?? []).length).toBeGreaterThan(0);
    expect(html).not.toMatch(playOff);
  });
});

describe("Checker round 1 on the real bundles", () => {
  const BIG = ["us20003k7a", "usp000juhz", "official20100227063411530_30"];
  it("gives the large events a Station select instead of chips, and keeps Tōhoku's ten chips", async () => {
    for (const id of BIG) {
      const entry = byId(id), o = await open(entry), html = stage(entry, o, 7.5);
      expect(html, id).not.toContain("story-chip");
      expect((html.match(/<select aria-label="Station">(.*?)<\/select>/)?.[1].match(/<option /g) ?? []).length, id).toBe(o.manifest.stations.length);
    }
    expect(stage(tohokuEntry, await open(tohokuEntry), 7.5).match(/class="story-chip/g)).toHaveLength(10);
  });
  it("keeps every map label of the eastern events inside the screen, in Story and Station lens, at 1440×900", async () => {
    for (const id of BIG) for (const view of ["story", "radial"] as const) {
      const entry = byId(id), html = stage(entry, await open(entry), 7.5, view);
      for (const m of html.matchAll(/<text x="([\d.-]+)" y="([\d.-]+)" text-anchor="(\w+)" class="story-label[^"]*">([^<]*)<\/text>/g)) {
        const [x, y] = [Number(m[1]), Number(m[2])];
        expect(y, `${id} ${view} ${m[4]}`).toBeLessThanOrEqual(900); expect(y).toBeGreaterThanOrEqual(0);
        expect(x).toBeGreaterThanOrEqual(0); expect(x).toBeLessThanOrEqual(1440);
      }
    }
  });
  it("aims a records-free event's lens at its epicentre on a desktop and on a phone", async () => {
    const entry = byId("usp0007jcu"), o = await open(entry);
    for (const size of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
      const html = stage(entry, o, 0, "story", size), [x, y] = html.match(/<path d="M([\d.-]+) ([\d.-]+)L[^"]*" class="story-epicentre"/)!.slice(1).map(Number);
      expect(html).toContain('story-lens-title__name">Adak epicentre<');
      expect([x > 0 && x < size.w, y > 0 && y < size.h], `${size.w}`).toEqual([true, true]);
    }
  });
  it("credits each event's own record providers and the reported-times sources", async () => {
    const credits = (html: string) => html.slice(html.indexOf('class="story-credits"'), html.indexOf("</p>", html.indexOf('class="story-credits"')));
    const tohoku = credits(stage(tohokuEntry, await open(tohokuEntry)));
    for (const p of new Set((await open(tohokuEntry)).manifest.stations.map(s => (s as { source: { publisher: string } }).source.publisher))) expect(tohoku).toContain(p);
    expect(tohoku).toContain("NOAA Center for Operational Oceanographic Products and Services");
    expect(tohoku).toContain("Reported times: NTWC and NCEI source records.");
    expect(credits(stage(byId("us20003k7a"), await open(byId("us20003k7a"))))).toContain("Records: NOAA CO-OPS · archived NTWC day files.");
    const adak = credits(stage(byId("usp0007jcu"), await open(byId("usp0007jcu"))));
    expect(adak).not.toContain("Records:"); expect(adak).toContain("Reported times: NTWC and NCEI source records.");
  });
  it("writes every listed magnitude with at least one decimal", () => {
    for (const e of eventsIndex.events) expect(eventOption(e), e.event_id).toMatch(/ · M\d+\.\d+$/);
  });
});

describe("All events on the real index", () => {
  const sum = (a: number[]) => a.reduce((n, v) => n + v, 0);
  const screen = async (size = { w: 1440, h: 900 }) => renderToStaticMarkup(<EventsView events={eventsIndex.events} selected={parseEvent("?view=events", eventsIndex).entry}
    order="date" has={null} basemap={await loadBasemap(eventsIndex, undefined, localFetch)} issues={[]} onDismissIssues={noop} restoreKey={0} onSelect={noop}
    onOrder={noop} onHas={noop} onOpen={noop} initialSize={size}/>);
  const rows = (html: string) => html.split('<li><button type="button" class="events-row"').slice(1);
  it("fetches only the index and the basemap for its first screen, within the plan's 300 KB budget", async () => {
    const asked: string[] = []; let bytes = 0;
    const request = async (u: string | URL | Request) => { asked.push(String(u)); const b = await (await localFetch(u)).arrayBuffer(); bytes += b.byteLength; return new Response(b); };
    const first = await loadFirst("?view=events", undefined, request);
    console.info("All events first screen", { files: asked, bytes });
    expect(asked).toEqual(["/data/events.json", `/data/${eventsIndex.basemap!.path}`]);
    expect(bytes).toBeLessThanOrEqual(300_000);
    expect([first.manifest, first.entry.event_id]).toEqual([null, tohokuEntry.event_id]);
  });
  it("lists all 49 events in date order, and every row's counts are the index's", async () => {
    const html = await screen(), list = rows(html);
    expect(list).toHaveLength(49);
    expect(html.match(/class="story-epicentre events-star"/g)).toHaveLength(49);
    list.forEach((row, i) => {
      const e = eventsIndex.events[i], c = e.counts!;
      expect(row, e.event_id).toContain(`<b>${e.label}</b>`);
      const m = /class="events-row__counts">NTWC: (\d+) reported, (\d+) pairs? · NCEI: (\d+) reported · (\d+) station records?( · published contours)?</.exec(row)!;
      expect(m.slice(1, 5).map(Number), e.event_id).toEqual([c.ntwc_reported, c.ntwc_pairs, c.ncei_reported, c.stations]);
      expect(!!m[5], e.event_id).toBe(!!e.layers);
    });
  });
  it("draws each row's hour strip from reported_per_hour: bar totals equal its sums, NTWC and NCEI in their own rows", async () => {
    rows(await screen()).forEach((row, i) => {
      const e = eventsIndex.events[i], [ntwc, ncei] = row.split('class="events-strip__row"').slice(1, 3);
      const bars = (s: string) => sum([...s.matchAll(/<rect data-n="(\d+)"/g)].map(m => Number(m[1])));
      expect([bars(ntwc), bars(ncei)], e.event_id).toEqual([sum(e.counts!.reported_per_hour.ntwc), sum(e.counts!.reported_per_hour.ncei)]);
    });
  });
  it("opens on Tōhoku under the lens, on a desktop and on a phone", async () => {
    for (const size of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
      const html = await screen(size);
      expect(html, `${size.w}`).toContain('<p class="story-lens-title__name">Tōhoku, Japan</p><p class="story-lens-title__sub">11 March 2011 · M9.1</p>');
      expect(html).toContain('aria-current="true"><span class="events-row__name"><b>Tōhoku, Japan</b>');
      expect(html).toContain("92 estimate–reported pairs in the NTWC table · 8 with a reviewed position · 130 NTWC reported times · 273 NCEI reported times · 10 station records");
    }
  });
});
