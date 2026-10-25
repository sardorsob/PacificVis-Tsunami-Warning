import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { STATION_IDS } from "../loader";
import { NoReference, StationCard } from "../StationCard";
import type { DemoGeometry, DemoManifest, DemoState, StationMetadata, StationRecords, StationSelection } from "../types";
import type { StoryLayers } from "./layers";
import { ClockBar } from "./ClockBar";
import { StoryView, type StoryViewProps } from "./StoryView";
import type { StoryParams } from "./url";

// Typed test-only inputs. Never imported by a runtime renderer or scientific bundle.
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
  event: { event_id: "event", origin_time_utc: "2011-03-11T05:46:24.120Z", latitude: 0, longitude: 0 },
  release: { release_id: "test", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy", allowed_uses: [], prohibited_uses: [] },
  default_state: { selectedStationId: "1617760", pinnedStationId: "saip", windowId: "common_day", productKey: "raw_value" },
  windows: [{ id: "common_day", label: "Test day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z" }],
  stations, assets: [], geometry_path: "geometry.json", input_fingerprints: [], config_sha256: "0".repeat(64),
  accounting: { source_observation_count: 20, exported_observation_count: 20, station_count: 10, rejected_observation_count: 0 },
} satisfies DemoManifest;
// Stations spread 2,000 km apart on one line; the event sits west of them.
const geometry: DemoGeometry = { schema_version: "1", source_crs: "EPSG:4326", display_crs: "+proj=eqearth +lon_0=-160", coordinate_order: "x,y", central_meridian: -160,
  coastline: [[[0, 0], [1, 1]]], bounds: [-1e7, -1e7, 1e7, 1e7],
  points: [{ id: "event", x: -6e6, y: 0 }, ...STATION_IDS.map((id, i) => ({ id, x: i * 2e6, y: 0 }))] };
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
const ready = (id: string): StationSelection => { const station = stations.find(s => s.station_id === id)!; return { station, status: "ready", records: records(station), error: null }; };
const noop = () => undefined;
export function input({ lensOverOcean = false, t = 7.5, compare = false, step = "explore" as StoryParams["step"], size = undefined as { w: number; h: number } | undefined,
  from = null as StoryParams["from"], issues = [] as string[], pinned = "saip" as string | null, at = null as StoryParams["at"],
  z = 1, view = "story" as DemoState["view"] } = {}): StoryViewProps {
  return {
    manifest, geometry, geometryError: null, layers, layersError: null, layersPending: null, onRetryLayers: noop,
    state: { view, selectedStationId: "1617760", pinnedStationId: pinned, windowId: "common_day", productKey: "raw_value" },
    selected: ready("1617760"), pinned: pinned ? ready(pinned) : null, onSelectStation: noop, onOpenEvidence: noop, onRetryStation: noop, onRetryGeometry: noop,
    params: { t, compare, step, at: at ?? (lensOverOcean ? [-3000, 9000] : null), z, from }, onNav: noop, restoreKey: 0,
    evidenceOpen: false, issues, onDismissIssues: noop, onState: noop, initialSize: size,
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

describe("Station lens — the story stage around one station", () => {
  const lens = (extra: Parameters<typeof input>[0] = {}) => input({ view: "radial", t: 7.5, ...extra });
  const common = (props: StoryViewProps) => ({ windowId: props.state.windowId, productKey: props.state.productKey, onOpenEvidence: noop,
    onRetryStation: noop, cursorMs: Date.parse(props.manifest.event.origin_time_utc) + 7.5 * 3_600_000 });
  it("shows A's and B's full cards on the shared clock", () => {
    const props = lens(), html = renderToStaticMarkup(<StoryView {...props}/>);
    expect(html).toContain(renderToStaticMarkup(<StationCard selection={props.selected} role="selected" {...common(props)}/>));
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
