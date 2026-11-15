import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NoReference, StationCard } from "../StationCard";
import type { DemoGeometry, DemoManifest, DemoState, EventEntry, StationMetadata, StationRecords, StationSelection } from "../types";
import type { StoryArrivals } from "./arrivals";
import { ArrivalsView } from "./ArrivalsView";
import type { StoryLayers } from "./layers";
import { ClockBar } from "./ClockBar";
import { NoRecordsPage, PairedView } from "./PairedView";
import { useStage } from "./StoryMap";
import { noRecordsView } from "../slices";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { StoryView, type StoryViewProps } from "./StoryView";
import { STORY_EVENT_ID } from "./steps";
import { parseStoryParams, type StoryParams } from "./url";

// Typed test-only inputs. Never imported by a runtime renderer or scientific bundle.
const STATION_IDS = ["1617760", "1770000", "21413", "21418", "32401", "46411", "9419750", "9461380", "saip", "valp"];
const stations: StationMetadata[] = STATION_IDS.map((station_id, i) => ({
  station_id, source_id: "test-only", station_type: i < 2 ? "dart" : "coastal", name: `Test station ${station_id}`, units: "m",
  vertical_reference: "unknown", horizontal_datum: "unknown", coordinate_order: "longitude,latitude", time_basis: "UTC", latitude: 0, longitude: 0, observation_count: 2,
  products: [
    { key: "raw_value", label: "Test raw measurement", units: "m", available: true },
    { key: "residual_value", label: "Test residual", units: "m", available: false },
    { key: "fitted_value", label: "Test fitted", units: "m", available: false },
  ],
  source: { source_id: "test-only", title: "Test-only source", publisher: "Test publisher", accessed_on: "unknown", version_or_date: "unknown", license_or_terms: "unknown", processing_level: "test-only", sha256: "0".repeat(64), url: null },
}));
const manifest = {
  schema_version: "1", exporter_version: "1", bundle_id: "test-only-story", evidence_state: "internal_descriptive_only",
  event: { event_id: STORY_EVENT_ID, origin_time_utc: "2011-03-11T05:46:24.120Z", latitude: 0, longitude: 0 },
  release: { release_id: "test", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy", allowed_uses: [], prohibited_uses: [] },
  default_state: { selectedStationId: "1617760", pinnedStationId: "saip", windowId: "common_day", productKey: "raw_value" },
  windows: [{ id: "common_day", label: "Test day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z" }],
  stations, assets: [], geometry_path: "geometry.json", input_fingerprints: [], config_sha256: "0".repeat(64),
  accounting: { source_observation_count: 20, exported_observation_count: 20, station_count: 10, rejected_observation_count: 0 },
} satisfies DemoManifest;
// Stations spread 2,000 km apart on one line; the event sits west of them.
const geometry: DemoGeometry = { schema_version: "1", source_crs: "EPSG:4326", display_crs: "+proj=eqearth +lon_0=-160", coordinate_order: "x,y", central_meridian: -160,
  coastline: [[[0, 0], [1, 1]]], bounds: [-1e7, -1e7, 1e7, 1e7],
  points: [{ id: STORY_EVENT_ID, x: -6e6, y: 0 }, ...STATION_IDS.map((id, i) => ({ id, x: i * 2e6, y: 0 }))] };
const layers: StoryLayers = {
  manifest: {} as StoryLayers["manifest"],
  contours: [{ hours: 5, index: true, parts: [[[-1e6, -3e6], [-1e6, 3e6]]] }, { hours: 6, index: false, parts: [[[-5e5, -3e6], [-5e5, 3e6]]] }],
  coastline: { parts: [[[0, 0], [1000, 0], [0, 1000], [0, 0]]], closed: [true] },
};
function records(station: StationMetadata): StationRecords {
  const row = (at: string, raw: number) => ({ observation_id: at, source_id: "test-only", station_id: station.station_id, source_time: at, observed_at_utc: at,
    raw_value: raw, fitted_value: null, residual_value: null, units: "m", vertical_reference: "unknown", raw_status: "observed" as const,
    residual_status: "structurally_not_applicable" as const, grid_status: "on_grid" as const, qc_flags: {}, source_qc_status: "not_reported" as const });
  return { schema_version: "1", station_id: station.station_id, rows: [row("2011-03-11T03:00:00Z", 1), row("2011-03-11T20:00:00Z", 2)],
    support: [{ station_id: station.station_id, window_id: "common_day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z", accepted_sample_n: 2,
      valid_sample_n: 2, source_blank_n: 0, product_valid_n: { raw_value: 2, residual_value: 0, fitted_value: 0 }, support_kind: "coastal_exact_grid", expected_n: 1440, cadence_seconds: 60,
      source_grid_anchor_utc: "2011-03-11T00:00:00Z", absent_n: 1438, off_grid_n: 0, off_grid_valid_n: 0, exact_valid_n: 2, sample_density_numerator_n: 2, sample_density_denominator_n: 1440,
      sample_density_percent: 0.14, supported_start_utc: "2011-03-11T00:00:00Z", supported_end_utc_exclusive: "2011-03-12T00:00:00Z", first_grid_utc: "2011-03-11T00:00:00Z",
      last_grid_utc: "2011-03-11T23:59:00Z", first_valid_raw_utc: "2011-03-11T03:00:00Z", last_valid_raw_utc: "2011-03-11T20:00:00Z", strict_numerator_n: 2, strict_denominator_n: 1440, strict_percent: 0.14 }],
    coverage_spans: [], gap_blocks: [] };
}
// The index entries the views get: the open event (its label, origin, magnitude and listed bundles) and the events the select offers.
const ref = (bundle_id: string) => ({ bundle_id, manifest_sha256: "0".repeat(64), manifest_bytes: 1 });
export const tohoku: EventEntry = { event_id: STORY_EVENT_ID, label: "Tōhoku, Japan", origin_time_utc: "2011-03-11T05:46:24.120Z", latitude: 0, longitude: 0,
  magnitude: 9.1, magnitude_type: "mww", records: ref("test-only-story"), layers: ref("test-only-layers"), arrivals: null };
const illapel: EventEntry = { event_id: "us20003k7a", label: "Illapel, Chile", origin_time_utc: "2015-09-16T22:54:32.860Z", latitude: 0, longitude: 0,
  magnitude: 8.3, magnitude_type: "mww", records: ref("test-only-illapel"), layers: ref("test-only-illapel-layers"), arrivals: null };
const ready = (id: string): StationSelection => { const station = stations.find(s => s.station_id === id)!; return { station, status: "ready", records: records(station), error: null }; };
const noop = () => undefined;
export function input({ lensOverOcean = false, t = 7.5, compare = false, step = "explore" as StoryParams["step"], size = undefined as { w: number; h: number } | undefined,
  from = null as StoryParams["from"], issues = [] as string[], pinned = "saip" as string | null, at = null as StoryParams["at"],
  z = 1, view = "story" as DemoState["view"] } = {}): StoryViewProps {
  return {
    manifest, geometry, geometryError: null, layers, layersError: null, layersPending: null, onRetryLayers: noop,
    state: { view, selectedStationId: "1617760", pinnedStationId: pinned, windowId: "common_day", productKey: "raw_value" },
    selected: ready("1617760"), pinned: pinned ? ready(pinned) : null, onOpenEvidence: noop, onRetryStation: noop, onRetryGeometry: noop,
    params: { t, compare, step, at: at ?? (lensOverOcean ? [-3000, 9000] : null), z, from }, onNav: noop, restoreKey: 0,
    evidenceOpen: false, issues, onDismissIssues: noop, onState: noop, initialSize: size, entry: tohoku, events: [tohoku, illapel], onEvent: noop,
  };
}

describe("story view — stage, lens and arms", () => {
  it("renders the published-estimate caveat and an honest open-ocean state", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ lensOverOcean: true })}/>);
    expect(html).toContain("NOAA/NCEI published travel-time estimates");
    expect(html).toContain("No station record here");
    expect(html).toContain("Open Pacific");
    expect(html).not.toMatch(/arrival time:|arrived at|warning time:/i);
  });
  it("names the station under the lens and marks the clock on its record", () => {
    const html = renderToStaticMarkup(<StoryView {...input()}/>);
    expect(html).toContain("Test station 1617760");
    expect(html).toContain("clock-cursor");
    expect(html).toContain("not an arrival pick");
  });
  it("keeps records and the map when the contour layer fails", () => {
    const html = renderToStaticMarkup(<StoryView {...input()} layers={null} layersError="asset hash mismatch"/>);
    expect(html).toContain("Published contour layer unavailable");
    expect(html).toContain("Test station 1617760");
    expect(html).not.toContain("story-contour");
  });
});

describe("story view — clock, legend and compare", () => {
  it("shows the clock reading, its UTC day and the not-an-arrival legend", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ t: 7.5 })}/>);
    expect(html).toContain("+7 h 30 min");
    expect(html).toContain("13:16 UTC");
    expect(html).toContain("Friday 11 March 2011");
    expect(html).toContain("Not wave height, not an arrival, not warning time.");
    expect(html).toContain("Samples per hour in Test station 1617760");
  });
  it("stacks A and B with one clock and station-local heights when comparing", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ compare: true })}/>);
    expect(html).toContain("heights stay station-local");
    expect(html).toContain("B · Test station saip");
    expect((html.match(/class="clock-cursor"/g) ?? []).length).toBeGreaterThanOrEqual(4);
  });
  it("disables the clock without the contour layer", () => {
    const html = renderToStaticMarkup(<StoryView {...input()} layers={null} layersError="missing"/>);
    expect(html).toMatch(/<button[^>]*class="story-play"[^>]*disabled/);
  });
});

describe("story view — guided steps and narrow layout", () => {
  it("opens a step with its counter, title, Back and Next", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: 1, t: 0, lensOverOcean: true })}/>);
    expect(html).toContain("1 of 6");
    expect(html).toContain("05:46 UTC, 11 March 2011");
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>Back</);
    expect(html).toMatch(/>Next</);
    expect(html).toContain("Skip to free exploration");
    expect(html).not.toContain("Station records");
  });
  it("offers free exploration with chips and a way back to the story", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: "explore" })}/>);
    expect(html).toContain("Station records");
    expect(html).toContain("Back to the guided story");
  });
  it("guides only the story's own event: any other event opens in free exploration, without step checks", () => {
    const base = input({ step: 4 }), other = { ...manifest, event: { ...manifest.event, event_id: "other-event" },
      stations: stations.filter(s => s.station_id !== "21418") };
    const props = { ...base, manifest: other, geometry: { ...geometry, points: geometry.points.map(p => p.id === STORY_EVENT_ID ? { ...p, id: "other-event" } : p) } };
    const html = renderToStaticMarkup(<StoryView {...props}/>);
    expect(html).not.toContain("4 of 6"); expect(html).not.toContain("Back to the guided story"); expect(html).not.toContain("unknown station");
    expect(html).toContain("Station records");
    expect(renderToStaticMarkup(<StoryView {...base}/>)).toContain("4 of 6");
  });
  it("parses a step link as free exploration for an unguided event", () => {
    expect(parseStoryParams("?step=4&from=3", false)).toEqual({ params: { t: 0, compare: false, step: "explore", at: null, z: 1, from: null }, issues: [] });
    expect(parseStoryParams("", false).params.step).toBe("explore");
    expect(parseStoryParams("?step=explore&t=3&cmp=1", false).params).toMatchObject({ step: "explore", t: 3, compare: true });
    expect(parseStoryParams("?step=4").params).toMatchObject({ step: 4, t: 7.5 });
  });
  it("ends the story with Explore instead of Next", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: 6, t: 12, lensOverOcean: true })}/>);
    expect(html).toContain("6 of 6");
    expect(html).toMatch(/>Explore</);
    expect(html).not.toMatch(/>Next</);
  });
  it("moves controls and evidence into a bottom sheet on a phone, without tilt or arm leaders", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: 4, size: { w: 390, h: 844 } })}/>);
    expect(html).toContain("story--narrow");
    expect(html).toContain("story-sheet story-sheet--narrow");
    expect(html).toContain("Next station");
    expect(html).toContain("4 of 6");
    expect(html).toContain('<g class="story-leads" aria-hidden="true"></g>');
  });
  it("wires the wide layout into the stage: lens cards, scale, capped arms and lens leads", () => {
    const lens = renderToStaticMarkup(<StoryView {...input({ view: "radial", size: { w: 1440, h: 900 } })}/>);
    expect(lens.match(/width:402px/g)).toHaveLength(2);         // Station lens cards widen into the room at 1440
    expect(lens.match(/<line[^>]*y2="258"/g)).toHaveLength(2);   // leads end in the card headers (cy − r + 6), not below a short card
    expect(renderToStaticMarkup(<StoryView {...input({ size: { w: 1920, h: 1080 } })}/>)).toContain("--ui:1.25");
    const short = renderToStaticMarkup(<StoryView {...input({ size: { w: 1280, h: 700 } })}/>);
    expect(short.match(/max-height:338px/g)).toHaveLength(2);    // side arms stop above the zoom buttons, then scroll
    expect(short).toContain("max-height:130px");                 // the read arm stops above the clock bar
  });
  it("opens the sheet on the page title, once, before the step or the clock", () => {
    for (const view of ["story", "radial"] as const) {
      const html = renderToStaticMarkup(<StoryView {...input({ step: view === "story" ? 4 : "explore", size: { w: 390, h: 844 }, view })}/>);
      const sheet = html.slice(html.indexOf("story-sheet story-sheet--narrow"));
      expect(html.match(/<h1/g)).toHaveLength(1);
      expect(sheet.indexOf("<h1")).toBeGreaterThan(-1);
      expect(sheet.indexOf("<h1")).toBeLessThan(sheet.indexOf(view === "story" ? "4 of 6" : "story-clockbar"));
    }
  });
});

describe("story view — reduced motion", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("replaces animated play with a one-hour step and never tilts", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("prefers-reduced-motion"), media: query }));
    const html = renderToStaticMarkup(<StoryView {...input()}/>);
    expect(html).toContain('aria-label="Step the published clock forward one hour"');
    expect(html).toContain(">+1 h<");
    expect(html).not.toContain("story--cine");
  });
});

describe("story view — exits, cancels and repairs", () => {
  it("offers Rows & sources for a station record, not over open ocean", () => {
    expect(renderToStaticMarkup(<StoryView {...input()}/>)).toContain("Rows &amp; sources");
    expect(renderToStaticMarkup(<StoryView {...input({ lensOverOcean: true })}/>)).not.toContain("Rows &amp; sources");
  });
  it("labels Compare as closable when on, and never offers A as B", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ compare: true })}/>);
    expect(html).toContain("Close compare ✕");
    expect(html).not.toMatch(/<option value="1617760"/);
    expect(renderToStaticMarkup(<StoryView {...input({ pinned: null })}/>)).toContain("Choose B…");
  });
  it("lets the reader leave the story view and resume the step they left", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: "explore", from: 4 })}/>);
    expect(html).toContain(">Paired<");
    expect(html).toContain(">Station lens<");
    expect(html).toContain("Back to the guided story (step 4)");
  });
  it("the lens subject depends on the lens point and zoom, not the screen size", () => {
    // 600 km from the second station: a phone lens shows more map but must not capture more.
    for (const size of [{ w: 390, h: 844 }, { w: 667, h: 375 }, { w: 1440, h: 900 }])
      expect(renderToStaticMarkup(<StoryView {...input({ at: [2600, 0], size })}/>)).toContain('story-lens-title__name">Open Pacific<');
  });
  it("zoomed out, the lens still names the same subject on every screen", () => {
    // 550 km from the second station: zoomed out to 0.6 the capture must not grow past 400 km, nor depend on clamping.
    for (const size of [{ w: 390, h: 844 }, { w: 1440, h: 900 }])
      expect(renderToStaticMarkup(<StoryView {...input({ at: [2550, 0], z: 0.6, size })}/>)).toContain('story-lens-title__name">Open Pacific<');
  });
  it("under reduced motion a play step offers its end instead of hiding the control", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: noop, removeEventListener: noop }));
    try {
      const html = renderToStaticMarkup(<StoryView {...input({ step: 2, t: 0, lensOverOcean: true })}/>);
      expect(html).not.toContain("▶ Play this step");
      expect(html).toContain("Show this step at +8 h");
    } finally { vi.unstubAllGlobals(); }
  });
  it("an Explore link without a lens point keeps the lens where the story left it", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: "explore", from: 3 })}/>);
    expect(html).toContain('story-lens-title__name">Test station 21418<');
  });
  it("shows a dismissible note when the link was repaired", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ issues: ["Zoom limited to 0.25–20."] })}/>);
    expect(html).toContain("This link was repaired");
    expect(html).toContain("Zoom limited to 0.25–20.");
    expect(html).toMatch(/>Dismiss</);
  });
  it("offers Play this step on step 2 only before it has run", () => {
    expect(renderToStaticMarkup(<StoryView {...input({ step: 2, t: 0, lensOverOcean: true })}/>)).toContain("▶ Play this step");
    expect(renderToStaticMarkup(<StoryView {...input({ step: 2, t: 8, lensOverOcean: true })}/>)).not.toContain("▶ Play this step");
  });
  it("offers visible zoom and reset controls for touch and mouse readers", () => {
    const html = renderToStaticMarkup(<StoryView {...input()}/>);
    for (const label of ["Zoom in", "Zoom out", "Reset view"]) expect(html).toContain(`aria-label="${label}"`);
  });
  it("disables the one-hour step at the end of the clock", () => {
    const bar = (t: number) => renderToStaticMarkup(<ClockBar t={t} playing={false} disabled={false} originUtc="2011-03-11T05:46:24.120Z" reduced
      onToggle={noop} onSeek={noop}/>);
    expect(bar(30)).toMatch(/<button[^>]*disabled=""[^>]*>\+1 h</);
    expect(bar(29)).not.toMatch(/<button[^>]*disabled=""[^>]*>\+1 h</);
  });
  it("says when the contour layer is loading or retrying", () => {
    expect(renderToStaticMarkup(<StoryView {...input()} layers={null} layersPending="loading"/>)).toContain("Loading the published contour layer…");
    expect(renderToStaticMarkup(<StoryView {...input()} layers={null} layersPending="retrying"/>)).toContain("Retrying the published contour layer…");
  });
  it("does not narrate every render: the live region starts empty", () => {
    const html = renderToStaticMarkup(<StoryView {...input()}/>);
    expect(html).toMatch(/<p class="story-sr" aria-live="polite"><\/p>/);
  });
  it("keeps Back focusable on step 1 instead of disabling it", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: 1, t: 0, lensOverOcean: true })}/>);
    expect(html).toMatch(/<button type="button" aria-disabled="true">Back</);
  });
});

describe("map labels around the lens", () => {
  it("drop the origin label when the lens sits on the epicentre (its title names it)", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ step: 1, t: 0, at: [-6000, 0] })}/>);
    expect(html).toContain('story-lens-title__name">Tōhoku epicentre<');
    expect(html).not.toContain("Tōhoku origin · 05:46 UTC");
  });
});

describe("Station lens — the story stage around one station", () => {
  const lens = (extra: Parameters<typeof input>[0] = {}) => input({ view: "radial", t: 7.5, ...extra });
  const common = (props: StoryViewProps) => ({ windowId: props.state.windowId, productKey: props.state.productKey, onOpenEvidence: noop,
    onRetryStation: noop, cursorMs: Date.parse(props.manifest.event.origin_time_utc) + 7.5 * 3_600_000 });
  it("shows A's and B's full cards on the shared clock", () => {
    const props = lens(), html = renderToStaticMarkup(<StoryView {...props}/>);
    expect(html).toContain(renderToStaticMarkup(<StationCard selection={props.selected!} role="selected" {...common(props)}/>));
    expect(html).toContain(renderToStaticMarkup(<StationCard selection={props.pinned!} role="pinned" {...common(props)}/>));
  });
  it("clears B without substitution: one chart, one support, and the no-reference card", () => {
    const html = renderToStaticMarkup(<StoryView {...lens({ pinned: null })}/>);
    expect(html).toContain(renderToStaticMarkup(<NoReference/>));
    expect(html.match(/class="record-chart"/g)).toHaveLength(1);
    expect(html.match(/class="support-view"/g)).toHaveLength(1);
  });
  it("has station tools and the view switch, and none of the guided story's controls", () => {
    const html = renderToStaticMarkup(<StoryView {...lens()}/>);
    for (const text of ["Previous station target", "Pinned reference B", "UTC window"]) expect(html).toContain(text);
    expect(html).toMatch(/aria-pressed="true">Station lens</);
    for (const text of [" of 6<", "Skip to free exploration", "Back to the guided story", "⇄ Compare", "Play this step"]) expect(html).not.toContain(text);
  });
  it("keeps the lens on station A even when the URL's lens point is open ocean", () => {
    expect(renderToStaticMarkup(<StoryView {...lens({ lensOverOcean: true })}/>)).toContain('story-lens-title__name">Test station 1617760<');
  });
  it("keeps a failed map recoverable, with a way to another view", () => {
    const html = renderToStaticMarkup(<StoryView {...lens()} geometry={null} geometryError="test locator mismatch"/>);
    for (const text of ["test locator mismatch", "Retry map", ">Paired<"]) expect(html).toContain(text);
  });
  it("never words a contour as an arrival", () => {
    expect(renderToStaticMarkup(<StoryView {...lens()}/>)).not.toMatch(/arrival time:|arrived at|warning time:/i);
  });
});

// The contract's synthetic example, unvalidated here: these tests check the wiring, arrivals.test.tsx the file.
const arrivals = JSON.parse(readFileSync(new URL("../../../../docs/data/examples/story-arrivals.example.json", import.meta.url), "utf8")) as StoryArrivals;
describe("story view — reported times", () => {
  it("draws the reported-times marks on the map and their key in the column, in the story and the Station lens", () => {
    for (const view of ["story", "radial"] as const) {
      const html = renderToStaticMarkup(<StoryView {...input({ view })} arrivals={arrivals}/>), map = html.slice(html.indexOf('class="story-reports"'));
      expect(map.slice(0, map.indexOf("</g>")).match(/class="story-report /g), view).toHaveLength(5);   // the key's glyphs are not map marks
      expect(html).toContain("NTWC published estimate");
    }
  });
  it("shows the event without marks and says the reported-times file was rejected", () => {
    const html = renderToStaticMarkup(<StoryView {...input()} arrivals="rejected"/>);
    expect(html).toContain("The reported-times file was rejected");
    expect(html).toContain("Test station 1617760");
    expect(html).not.toContain("story-report");
  });
  it("adds nothing about reported times while the file loads", () => {
    expect(renderToStaticMarkup(<StoryView {...input()} arrivals={null}/>)).not.toMatch(/story-report|story-key|reported-times/);
  });
  // The example's linked places, re-linked to the test stations: Example Harbor (NTWC) to A, Example Bay (NCEI, within 1 km) to B.
  const linked: StoryArrivals = { ...arrivals, places: arrivals.places.map((p, i) => i > 1 ? p
    : { ...p, record: { station_id: i ? "saip" : "1617760", link: i ? "within_1km" : "same_provider_id" } }) };
  const group = (name: string) => `role="group" aria-label="Reported times linked to ${name}"`;
  it("puts A's three-clocks strip in the record arm above its record, also while the record loads or after it failed", () => {
    const html = renderToStaticMarkup(<StoryView {...input()} arrivals={linked}/>);
    expect(html).toContain(group("Test station 1617760"));
    expect(html).toContain("NTWC: reported 15 min after the published estimate · this station&#x27;s record.");
    expect(html.indexOf(group("Test station 1617760"))).toBeLessThan(html.indexOf('class="record-chart"'));
    expect(html).not.toContain(group("Test station saip"));
    const station = ready("1617760").station;
    for (const selected of [{ station, status: "loading" as const, records: null, error: null }, { station, status: "error" as const, records: null, error: "test" }])
      expect(renderToStaticMarkup(<StoryView {...input()} selected={selected} arrivals={linked}/>)).toContain("NTWC: reported 15 min after the published estimate · this station&#x27;s record.");
    expect(renderToStaticMarkup(<StoryView {...input({ lensOverOcean: true })} arrivals={linked}/>)).not.toContain("Reported times linked to");
  });
  it("in Compare stacks B's strip under A's, above both records, each named with its straight-line distance", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ compare: true })} arrivals={linked}/>);
    const a = html.indexOf("<b>Test station 1617760</b> · 1,113.2 km in a straight line from the epicentre");
    const b = html.indexOf("<b>Test station saip</b> · 1,565.1 km in a straight line from the epicentre");
    expect(a).toBeGreaterThan(-1); expect(b).toBeGreaterThan(a); expect(b).toBeLessThan(html.indexOf('class="record-chart"'));
    expect(html).toContain("record from a station within 1 km, not verified as the same instrument.");
  });
  it("gives each Station lens card its own station's strip", () => {
    const html = renderToStaticMarkup(<StoryView {...input({ view: "radial" })} arrivals={linked}/>);
    for (const name of ["Test station 1617760", "Test station saip"]) expect(html).toContain(group(name));
  });
});

describe("Reported times (?view=times) — every listed report on the shared clock", () => {
  const times = (extra: Parameters<typeof input>[0] = {}) => input({ view: "times", t: 7.5, ...extra });
  const visible = (html: string) => html.replace(/<[^>]*>/g, " ");
  it("lists the rows under the view switch, with the clock bar and its line at the clock", () => {
    const html = renderToStaticMarkup(<ArrivalsView {...times()} arrivals={arrivals}/>);
    expect(html).toContain('<main class="story story--paired story--ladder" aria-label="Reported times">');
    expect(html).toContain('<h1 class="story-title">Reported times</h1>');
    expect(html).toMatch(/aria-pressed="true">Reported times</);
    expect(html).toContain("2 estimate–reported pairs in the NTWC table");
    expect(html.match(/class="ladder-row"/g)).toHaveLength(5);
    expect(html).toContain('style="--clock:25%"');
    expect(html).toContain("story-clockbar");
    expect(visible(html)).not.toMatch(/arrival|measured|error|wrong|late|warning time/i);
  });
  it("sorts by the URL's order", () => {
    const html = renderToStaticMarkup(<ArrivalsView {...times()} state={{ ...times().state, sort: "distance" }} arrivals={arrivals}/>);
    expect(html.indexOf("<b>Example Point</b>")).toBeLessThan(html.indexOf("<b>Example Unplaced Town</b>"));
    expect(html).toMatch(/aria-pressed="true">Distance</);
  });
  it("says in one plain sentence when the file is loading, absent or rejected", () => {
    const say = (a: StoryViewProps["arrivals"]) => renderToStaticMarkup(<ArrivalsView {...times()} arrivals={a}/>);
    expect(say(undefined)).toContain('<p role="status" class="story-alert">Loading the reported-times file…</p>');
    expect(say(null)).toContain("This event has no reported-times file, so there are no published estimates or reported times to list.");
    expect(say("rejected")).toContain("The reported-times file was rejected, so no published estimates or reported times are shown.");
    for (const a of [undefined, null, "rejected" as const]) expect(say(a)).not.toContain("ladder-row");
  });
  it("keeps the URL repair note and disables the clock without the contour layer", () => {
    const html = renderToStaticMarkup(<ArrivalsView {...times({ issues: ["Invalid sort: reported time restored."] })} layers={null} arrivals={arrivals}/>);
    expect(html).toContain("Invalid sort: reported time restored.");
    expect(html).toMatch(/class="story-play" disabled=""/);
  });
});

describe("Paired — records first, on the shared clock", () => {
  const paired = (extra: Parameters<typeof input>[0] = {}) => input({ view: "paired", t: 7.5, ...extra });
  const cardOf = (props: StoryViewProps, role: "selected" | "pinned") => renderToStaticMarkup(<StationCard selection={role === "selected"
    ? props.selected! : props.pinned!} role={role} windowId={props.state.windowId} productKey={props.state.productKey} onOpenEvidence={noop}
    onRetryStation={noop} cursorMs={Date.parse(props.manifest.event.origin_time_utc) + 7.5 * 3_600_000}/>);
  it("shows A's and B's full cards on the shared clock", () => {
    const props = paired(), html = renderToStaticMarkup(<PairedView {...props}/>);
    expect(html).toContain(cardOf(props, "selected"));
    expect(html).toContain(cardOf(props, "pinned"));
  });
  it("names every station on the map band by its role", () => {
    const html = renderToStaticMarkup(<PairedView {...paired()}/>);
    expect(html.match(/class="paired-station[^"]*"/g)).toHaveLength(10);
    expect(html).toContain('aria-label="Selected A: Test station 1617760 (1617760)"');
    expect(html).toContain('aria-label="Pinned reference B: Test station saip (saip). Make it A"');
    expect(html).toContain('aria-label="Make Test station 21418 (21418) A"');
  });
  it("keeps the records when the map fails, with Retry map", () => {
    const props = paired(), html = renderToStaticMarkup(<PairedView {...props} geometry={null} geometryError="test locator mismatch"/>);
    for (const text of [cardOf(props, "selected"), "test locator mismatch", "Retry map"]) expect(html).toContain(text);
  });
  it("keeps the records when the contour layer fails, with Retry contours and the clock disabled", () => {
    const props = paired(), html = renderToStaticMarkup(<PairedView {...props} layers={null} layersError="asset hash mismatch"/>);
    for (const text of [cardOf(props, "selected"), "Published contour layer unavailable", "Retry contours"]) expect(html).toContain(text);
    expect(html).toMatch(/class="story-play" disabled=""/);
  });
  it("shows the link repair note, clears B without substitution, and presses Paired", () => {
    const html = renderToStaticMarkup(<PairedView {...paired({ pinned: null, issues: ["Zoom limited to 0.25–20."] })}/>);
    for (const text of ["This link was repaired", renderToStaticMarkup(<NoReference/>)]) expect(html).toContain(text);
    expect(html.match(/class="record-chart"/g)).toHaveLength(1);
    expect(html).toMatch(/aria-pressed="true">Paired</);
  });
  it("steps the clock one hour under reduced motion", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: noop, removeEventListener: noop }));
    try { expect(renderToStaticMarkup(<PairedView {...paired()}/>)).toContain("+1 h"); } finally { vi.unstubAllGlobals(); }
  });
  it("never words a contour as an arrival, and says the white line is the clock", () => {
    const html = renderToStaticMarkup(<PairedView {...paired()}/>);
    expect(html).not.toMatch(/arrival time:|arrived at|warning time:/i);
    expect(html).toContain("The white line on each record is the shared clock");
  });
});

describe("the event select — beside the view switch on the stage, in the page header elsewhere", () => {
  const select = (html: string) => html.match(/<label class="story-event"><span>Event<\/span><select aria-label="Event">(.*?)<\/select><\/label>/)?.[1] ?? null;
  it("sits in the top-right panel with the view switch, in the story and the Station lens, on the open event", () => {
    for (const view of ["story", "radial"] as const) for (const size of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
      const html = renderToStaticMarkup(<StoryView {...input({ view, size })}/>), panel = html.slice(html.indexOf("story-panel story-compare"));
      expect(select(panel), `${view} ${size.w}`).toContain('<option value="official20110311054624120_30" selected="">Tōhoku, Japan · 11 March 2011 · M9.1</option>');
      expect(panel.indexOf('class="story-event"')).toBeGreaterThan(panel.indexOf('class="story-views"'));
    }
  });
  it("gives the wide panel the room the layout sets, so the four views keep one row", () => {
    expect(renderToStaticMarkup(<StoryView {...input({ size: { w: 1440, h: 900 } })}/>)).toMatch(/class="story-panel story-compare"[^>]*style="width:348px"/);
  });
  it("sits in the page header beside the view switch in Paired and Reported times", () => {
    for (const html of [renderToStaticMarkup(<PairedView {...input({ view: "paired" })}/>), renderToStaticMarkup(<ArrivalsView {...input({ view: "times" })} arrivals={arrivals}/>)]) {
      const head = html.slice(html.indexOf('<header class="paired-head">'), html.indexOf("</header>"));
      expect(select(head)).toContain("Illapel, Chile · 16 September 2015 · M8.3");
      expect(head).toContain('class="story-views"');
    }
  });
});

describe("copy from the index entry and the manifest — no Tōhoku literals outside its steps", () => {
  // The same test stations, opened as Illapel: its own origin and entry; nothing else changes.
  const ILLAPEL_ORIGIN = "2015-09-16T22:54:32.860Z";
  const asIllapel = (props: StoryViewProps): StoryViewProps => ({ ...props, entry: illapel,
    manifest: { ...manifest, event: { ...manifest.event, event_id: illapel.event_id, origin_time_utc: ILLAPEL_ORIGIN } },
    geometry: { ...geometry, points: geometry.points.map(p => p.id === STORY_EVENT_ID ? { ...p, id: illapel.event_id } : p) } });
  const views = (props: StoryViewProps) => [renderToStaticMarkup(<StoryView {...props}/>), renderToStaticMarkup(<StoryView {...props} state={{ ...props.state, view: "radial" }}/>),
    renderToStaticMarkup(<PairedView {...props}/>), renderToStaticMarkup(<ArrivalsView {...props} arrivals={arrivals}/>)];
  const visible = (html: string) => html.replace(/<option[^>]*>[^<]*<\/option>/g, "").replace(/<[^>]*>/g, " ");
  it("keeps Tōhoku's copy as it was", () => {
    const wide = input({ size: { w: 1440, h: 900 } }), html = renderToStaticMarkup(<StoryView {...wide}/>);
    expect(html).toContain("Tōhoku origin · 05:46 UTC");
    expect(html).toContain("NOAA/NCEI travel-time contours, one line per hour after the 05:46 UTC Tōhoku origin.");
    const origin = renderToStaticMarkup(<StoryView {...input({ step: 1, t: 0, at: [-6000, 0] })}/>);
    expect(origin).toContain('story-lens-title__name">Tōhoku epicentre<');
    expect(origin).toContain("USGS origin 05:46:24 UTC · M9.1 · the published clock starts here");
    for (const page of views(wide)) expect(page).toContain('<p class="story-kicker">Pacific · 11 March 2011</p>');
  });
  it("words Illapel from its own entry and origin, with no Tōhoku date, time or name", () => {
    const wide = asIllapel(input({ size: { w: 1440, h: 900 } })), html = renderToStaticMarkup(<StoryView {...wide}/>);
    expect(html).toContain("Illapel origin · 22:54 UTC");
    expect(html).toContain("NOAA/NCEI travel-time contours, one line per hour after the 22:54 UTC Illapel origin.");
    const origin = renderToStaticMarkup(<StoryView {...asIllapel(input({ at: [-6000, 0] }))}/>);
    expect(origin).toContain('story-lens-title__name">Illapel epicentre<');
    expect(origin).toContain("USGS origin 22:54:32 UTC · M8.3 · the published clock starts here");
    for (const page of views(wide)) {
      expect(page).toContain('<p class="story-kicker">Pacific · 16 September 2015</p>');
      expect(visible(page)).not.toMatch(/Tōhoku|11 March|05:46|2011(?!-03-1[12])/);   // the test stations' records keep their own 2011 dates
    }
  });
  it("counts the stations in the map's description instead of naming ten", () => {
    expect(renderToStaticMarkup(<StoryView {...input()}/>)).toContain("with 10 station records.");
  });
});

describe("an event with no published contours keeps the clock; a contour bundle that fails does not", () => {
  const none = (extra: Parameters<typeof input>[0] = {}): StoryViewProps => ({ ...input(extra), entry: { ...tohoku, layers: null }, layers: null });
  const playOff = /<button[^>]*class="story-play"[^>]*disabled/, sliderOff = /<input type="range"[^>]*disabled/;
  const NOTE = "No published travel-time contours are listed for this event.";
  it("plays and seeks with no contours listed, drops the contour source from the clock bar and says so calmly once", () => {
    for (const html of [renderToStaticMarkup(<StoryView {...none()}/>), renderToStaticMarkup(<StoryView {...none({ view: "radial" })}/>),
      renderToStaticMarkup(<PairedView {...none({ view: "paired" })}/>), renderToStaticMarkup(<ArrivalsView {...none({ view: "times" })} arrivals={arrivals}/>)]) {
      expect(html).not.toMatch(playOff); expect(html).not.toMatch(sliderOff);
      expect(html).toContain('aria-label="Play the clock"');
      expect(html).not.toContain("NOAA/NCEI published contours");
      expect(html.split(NOTE)).toHaveLength(2);
      expect(html).not.toMatch(/Published contour layer unavailable|Retry contours|Loading the published contour layer/);
    }
  });
  it("words the stage without contours: no published clock, contour line, legend or contour credit, and the 1:110m basemap", () => {
    const html = renderToStaticMarkup(<StoryView {...none({ size: { w: 1440, h: 900 } })}/>);
    for (const text of ["one line per hour", "Colour shows the published hour", "NOAA/NCEI travel-time contours:", "1:50m"]) expect(html).not.toContain(text);
    expect(html).toContain("Natural Earth 1:110m");
    const origin = renderToStaticMarkup(<StoryView {...none({ at: [-6000, 0] })}/>);
    expect(origin).toContain("USGS origin 05:46:24 UTC · M9.1<"); expect(origin).not.toMatch(/published clock|NOAA\/NCEI/);
    const ocean = renderToStaticMarkup(<StoryView {...none({ lensOverOcean: true })}/>);
    expect(ocean).not.toMatch(/NOAA\/NCEI published travel-time estimates|nearest published contour|Published clock here/);
    expect(ocean).toContain("no published contours for this event");
  });
  it("lights the reported marks as the clock passes them", () => {
    const lit = (t: number) => (renderToStaticMarkup(<StoryView {...none({ t })} arrivals={arrivals}/>).match(/story-report--on/g) ?? []).length;
    expect(lit(30)).toBeGreaterThan(lit(0));
  });
  it("keeps today's failed-layer state when a listed contour bundle fails: clock off, Retry contours", () => {
    const html = renderToStaticMarkup(<StoryView {...input()} layers={null} layersError="asset hash mismatch"/>);
    expect(html).toMatch(playOff); expect(html).toMatch(sliderOff);
    expect(html).toContain("Retry contours"); expect(html).not.toContain(NOTE);
    expect(renderToStaticMarkup(<StoryView {...input()} layers={null} layersPending="loading"/>)).toMatch(playOff);
  });
});

describe("an event with no records bundle opens on the stage", () => {
  const adak: EventEntry = { event_id: "usp0007jcu", label: "Adak, Alaska", origin_time_utc: "1996-06-10T04:03:35.480Z", latitude: 51.564, longitude: -177.632,
    magnitude: 7.9, magnitude_type: "mwc", records: null, layers: null, arrivals: null, x: -1376848, y: 6141947 };
  const none = noRecordsView(adak);
  const stage = (extra: Parameters<typeof input>[0] = {}): StoryViewProps => ({ ...input(extra), entry: adak, manifest: none, layers: null, selected: null, pinned: null,
    geometry: { points: [{ id: adak.event_id, x: adak.x!, y: adak.y! }], coastline: [] }, basemap: { parts: [[[0, 0], [1000, 0], [0, 1000], [0, 0]]], closed: [true] },
    state: { ...input(extra).state, ...none.default_state }, params: { ...input(extra).params, at: null }, arrivals, events: [adak, tohoku, illapel] });
  const NOTE = "No station records are published for this event.";
  it("shows the basemap, the epicentre under the lens, the reported marks, the clock and the key, and says it has no records", () => {
    for (const size of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
      const html = renderToStaticMarkup(<StoryView {...stage({ size, t: 30 })}/>), map = html.slice(html.indexOf('class="story-reports"'));
      expect(html).toContain('story-lens-title__name">Adak epicentre<');
      expect(html).toContain("USGS origin 04:03:35 UTC · M7.9<");
      const [x, y] = html.match(/<path d="M([\d.-]+) ([\d.-]+)L[^"]*" class="story-epicentre"/)!.slice(1).map(Number);   // the map's star, on screen
      expect(x).toBeGreaterThan(0); expect(x).toBeLessThan(size.w); expect(y).toBeGreaterThan(0); expect(y).toBeLessThan(size.h);
      expect(html).toContain(NOTE);
      expect(map.slice(0, map.indexOf("</g>")).match(/class="story-report [^"]*story-report--on"/g)).toHaveLength(5);
      expect(html).toContain("2 estimate–reported pairs in the NTWC table");
      expect(html).toContain('class="story-land" d="M0 0L1000 0L0 1000L0 0Z"');
      expect(html).not.toMatch(/<button[^>]*class="story-play"[^>]*disabled/);
      for (const text of ["⇄ Compare", "Choose B", "Station records", "Previous station", "Rows &amp; sources", "Back to the guided story"]) expect(html).not.toContain(text);
      expect(html).toContain("with no station records.");
    }
  });
  it("lists every report in Reported times, as for any event", () => {
    const html = renderToStaticMarkup(<ArrivalsView {...stage({ view: "times" })}/>);
    expect(html.match(/class="ladder-row"/g)).toHaveLength(5);
    expect(html).toContain("internal descriptive evidence only");
    expect(html).not.toContain("null ·");
  });
  // A hook-free page: walk its elements to press its buttons (no DOM needed).
  const tree = (node: ReactNode): ReactElement<{ children?: ReactNode; onClick?: () => void }>[] => Array.isArray(node) ? node.flatMap(tree)
    : !isValidElement<{ children?: ReactNode; onClick?: () => void }>(node) ? [] : [node, ...(typeof node.type === "function"
      ? tree((node.type as (p: unknown) => ReactNode)(node.props)) : []), ...tree(node.props.children)];
  it("gives Paired and Station lens a plain note with a way to Story and to Reported times", () => {
    for (const view of ["paired", "radial"] as const) {
      const onState = vi.fn(), props = { ...stage({ view, t: 4 }), onState }, html = renderToStaticMarkup(<NoRecordsPage {...props}/>);
      expect(html).toContain(`${NOTE} ${view === "paired" ? "Paired records" : "Station lens"} shows station records; Story and Reported times show this event&#x27;s reported times.`);
      expect(html).toContain("Adak, Alaska · 10 June 1996 · M7.9");
      expect(html).toContain("Pacific · 10 June 1996");
      const buttons = tree(NoRecordsPage(props)).filter(n => n.type === "button");
      buttons.find(b => b.props.children === "Story")!.props.onClick!();
      buttons.find(b => b.props.children === "Reported times")!.props.onClick!();
      expect(onState.mock.calls.map(([patch, live]) => [patch, live.t, live.a])).toEqual([[{ view: "story" }, 4, ""], [{ view: "times" }, 4, ""]]);
    }
  });
});

describe("Station lens keeps every control in view: the reported-times key starts closed there", () => {
  it("folds the key into a closed <details> in Station lens and leaves it open in the story, its marks and counts inside either way", () => {
    const keyOf = (view: DemoState["view"], size = { w: 1440, h: 900 }) => {
      const html = renderToStaticMarkup(<StoryView {...input({ view, size })} arrivals={arrivals}/>), at = html.indexOf('class="story-legend story-key"');
      return html.slice(html.lastIndexOf("<details", at), html.indexOf("</details>", at));
    };
    for (const size of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
      expect(keyOf("radial", size)).toMatch(/^<details class="story-legend story-key"><summary>Reported times and published estimates<\/summary>/);
      expect(keyOf("story", size)).toMatch(/^<details class="story-legend story-key" open=""><summary>/);
    }
    for (const text of ["NTWC published estimate", "2 estimate–reported pairs in the NTWC table"]) expect(keyOf("radial")).toContain(text);
  });
});

describe("Checker round 1 — station picker, epicentre aim, provider credit", () => {
  // Thirteen stations: one more than the chips are kept for.
  const ids = Array.from({ length: 13 }, (_, i) => `s${String(i + 1).padStart(2, "0")}`);
  const many: DemoManifest = { ...manifest, stations: ids.map(station_id => ({ ...stations[0], station_id, name: `Many ${station_id}` })),
    default_state: { ...manifest.default_state, selectedStationId: "s01", pinnedStationId: "s02" } };
  const manyProps = (extra: Parameters<typeof input>[0] = {}): StoryViewProps => ({ ...input(extra), manifest: many,
    geometry: { ...geometry, points: [geometry.points[0], ...ids.map((id, i) => ({ id, x: i * 2e6, y: 0 }))] },
    state: { ...input(extra).state, selectedStationId: "s01", pinnedStationId: "s02" },
    selected: { station: many.stations[0], status: "ready", records: records(many.stations[0]), error: null }, pinned: null });
  it("picks a station from a native select labelled Station when an event has more than 12, and keeps the chips up to 12", () => {
    const html = renderToStaticMarkup(<StoryView {...manyProps({ size: { w: 1440, h: 900 } })}/>);
    expect(html).not.toContain("story-chip");
    const select = html.match(/<label class="story-event"><span>Station<\/span><select aria-label="Station">(.*?)<\/select><\/label>/)?.[1] ?? "";
    expect(select.match(/<option /g)).toHaveLength(13);
    expect(select).toContain('<option value="s01" selected="">Many s01</option>');
    const ocean = renderToStaticMarkup(<StoryView {...manyProps({ at: [1000, 9000] })}/>);
    expect(ocean).toContain('<option value="" selected="">No station under the lens</option>');
    expect(renderToStaticMarkup(<StoryView {...input({ step: "explore" })}/>).match(/class="story-chip/g)).toHaveLength(10);   // Tōhoku as built
  });
  it("knows an event's epicentre from the index before its map loads, so the lens aims there from the first render", () => {
    const Probe = ({ entry }: { entry: EventEntry }) => { const { epicentre } = useStage(noRecordsView(entry), null, null, null, entry); return <p>{epicentre.join(",")}</p>; };
    const adak = { ...tohoku, event_id: "usp0007jcu", records: null, layers: null, x: -1376848, y: 6141947 };
    expect(renderToStaticMarkup(<Probe entry={adak}/>)).toBe("<p>-1376848,-6141947</p>");
  });
  it("credits the record providers the bundle names, and the reported-times sources when the event has a file", () => {
    const credits = (props: StoryViewProps) => { const html = renderToStaticMarkup(<StoryView {...props}/>); return html.slice(html.indexOf('class="story-credits"')); };
    expect(credits(input())).toContain("Records: Test publisher.");
    expect(credits(input())).not.toContain("Reported times:");
    const withFile = { ...input(), entry: { ...tohoku, arrivals: { path: "story-arrivals-v2/x.json", sha256: "0".repeat(64), bytes: 1 } } };
    expect(credits(withFile)).toContain("Reported times: NTWC and NCEI source records.");
  });
});
