import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { STATION_IDS } from "../loader";
import type { DemoGeometry, DemoManifest, StationMetadata, StationRecords, StationSelection } from "../types";
import type { StoryLayers } from "./layers";
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
export function input({ lensOverOcean = false, t = 7.5, compare = false, step = "explore" as StoryParams["step"], size = undefined as { w: number; h: number } | undefined } = {}): StoryViewProps {
  return {
    manifest, geometry, geometryError: null, layers, layersError: null, onRetryLayers: noop,
    state: { view: "story", selectedStationId: "1617760", pinnedStationId: "saip", windowId: "common_day", productKey: "raw_value" },
    selected: ready("1617760"), pinned: ready("saip"), onSelectStation: noop, onOpenEvidence: noop, onRetryStation: noop, onRetryGeometry: noop,
    params: { t, compare, step }, onParams: noop, onPinStation: noop,
    initialCentre: lensOverOcean ? [-3e6, 9e6] : undefined, initialSize: size,
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
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Back</);
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

