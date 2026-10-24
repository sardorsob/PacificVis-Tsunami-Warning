import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { RecordChart, type RecordChartProps } from "../RecordChart";
import { SupportView, type SupportViewProps } from "../SupportView";
import { STATION_IDS } from "../loader";
import type { DemoManifest, RadialProps, StationMetadata, StationRecords } from "../types";
import { RadialDemo } from "./RadialDemo";

// Typed test-only inputs. Never imported by a runtime renderer or scientific bundle.
const stations: StationMetadata[] = STATION_IDS.map(station_id => ({
  station_id, source_id: "test-only", station_type: "dart",
  name: `Test station ${station_id}`, units: "m", vertical_reference: "unknown",
  horizontal_datum: "unknown", coordinate_order: "longitude,latitude", time_basis: "UTC",
  latitude: 0, longitude: 0, observation_count: 1,
  products: [
    {key: "raw_value", label: "Test raw measurement", units: "m", available: true},
    {key: "residual_value", label: "Test residual", units: "m", available: false},
    {key: "fitted_value", label: "Test fitted", units: "m", available: false},
  ],
  source: {source_id: "test-only", title: "Test-only source", publisher: "Test publisher", accessed_on: "unknown", version_or_date: "unknown", license_or_terms: "unknown", processing_level: "test-only", sha256: "0".repeat(64), url: null},
}));
function records(station: StationMetadata): StationRecords {
  return {schema_version: "1", station_id: station.station_id, rows: [{
    observation_id: `test-${station.station_id}`, source_id: station.source_id, station_id: station.station_id,
    source_time: "2011-03-11T00:00:00Z", observed_at_utc: "2011-03-11T00:00:00Z",
    raw_value: 0, fitted_value: null, residual_value: null, units: "m", vertical_reference: "unknown",
    raw_status: "observed", residual_status: "structurally_not_applicable", grid_status: "not_applicable",
    qc_flags: {test_flag: true}, source_qc_status: "flagged",
  }], support: [{station_id: station.station_id, window_id: "common_day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z", accepted_sample_n: 1, valid_sample_n: 1, source_blank_n: 0, product_valid_n: {raw_value: 1, residual_value: 0, fitted_value: 0}, support_kind: "dart_actual_timestamps", strict_numerator_n: null, strict_denominator_n: null, strict_percent: null, cadence_seconds_counts: []}], coverage_spans: [], gap_blocks: []};
}
function input(): RadialProps {
  const manifest: DemoManifest = {
    schema_version: "1", exporter_version: "1", bundle_id: "test-only-radial", evidence_state: "internal_descriptive_only",
    event: {event_id: "test", origin_time_utc: "2011-03-11T05:46:24.120Z", latitude: 0, longitude: 0},
    release: {release_id: "test", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy", allowed_uses: [], prohibited_uses: []},
    default_state: {selectedStationId: stations[0].station_id, pinnedStationId: stations[1].station_id, windowId: "common_day", productKey: "raw_value"},
    windows: [{id: "common_day", label: "Test common day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z"}],
    stations, assets: [], geometry_path: "geometry.json", input_fingerprints: [], config_sha256: "0".repeat(64),
    accounting: {source_observation_count: 10, exported_observation_count: 10, station_count: 10, rejected_observation_count: 0},
  };
  return {manifest, geometry: null, geometryError: null, state: {view: "radial", ...manifest.default_state}, selected: {station: stations[0], status: "ready", records: records(stations[0]), error: null}, pinned: {station: stations[1], status: "ready", records: records(stations[1]), error: null}, onSelectStation: vi.fn(), onOpenEvidence: vi.fn(), onRetryStation: vi.fn(), onRetryGeometry: vi.fn()};
}
type NodeProps = {children?: ReactNode; onClick?: () => void; disabled?: boolean; "aria-label"?: string};
function nodes(node: ReactNode): ReactElement<NodeProps>[] {
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (!isValidElement<NodeProps>(node)) return [];
  return [node, ...nodes(node.props.children)];
}
function click(props: RadialProps, label: string) {
  const button = nodes(RadialDemo(props)).find(node => node.type === "button" && node.props["aria-label"] === label);
  expect(button, label).toBeDefined();
  button!.props.onClick!();
}
describe("portable radial renderer ownership", () => {
  it("keeps two exact chart inputs and two separately owned supports in three evidence facets", () => {
    const props = input();
    const tree = nodes(RadialDemo(props));
    const charts = tree.filter(node => node.type === RecordChart).map(node => node.props as RecordChartProps);
    const supports = tree.filter(node => node.type === SupportView).map(node => node.props as SupportViewProps);
    expect(charts.map(chart => [chart.station.station_id, chart.role, chart.windowId, chart.productKey])).toEqual([["1617760", "selected", "common_day", "raw_value"], ["1770000", "pinned", "common_day", "raw_value"]]);
    expect(charts[0].records).toBe(props.selected.records);
    expect(charts[1].records).toBe(props.pinned!.records);
    expect(supports.map(support => support.station.station_id)).toEqual(["1617760", "1770000"]);
    expect(supports[0].records).toBe(props.selected.records);
    expect(supports[1].records).toBe(props.pinned!.records);
    expect(tree.filter(node => node.type === "article")).toHaveLength(3);
  });
  it("moves only to named adjacent targets, stops at cohort edges, and never changes pin", () => {
    const props = input();
    const buttons = nodes(RadialDemo(props)).filter(node => node.type === "button");
    expect(buttons.find(node => node.props["aria-label"] === "Previous station target")?.props.disabled).toBe(true);
    click(props, "Next station target");
    expect(props.onSelectStation).toHaveBeenCalledExactlyOnceWith("1770000");
    expect(props.state.pinnedStationId).toBe("1770000");
    const middle = {...props, state: {...props.state, selectedStationId: "21418"}, selected: {...props.selected, station: stations[3]}};
    click(middle, "Previous station target");
    expect(props.onSelectStation).toHaveBeenLastCalledWith("21413");
    const last = {...props, state: {...props.state, selectedStationId: "valp"}, selected: {...props.selected, station: stations[9]}};
    expect(nodes(RadialDemo(last)).find(node => node.props["aria-label"] === "Next station target")?.props.disabled).toBe(true);
    expect(renderToStaticMarkup(<RadialDemo {...props}/>)).toContain("Test station 1770000");
  });
  it("opens each station’s evidence with its own identity and clears pin without substitution", () => {
    const props = input();
    click(props, "Rows & sources: Test station 1617760");
    expect(props.onOpenEvidence).toHaveBeenLastCalledWith("1617760");
    click(props, "Rows & sources: Test station 1770000");
    expect(props.onOpenEvidence).toHaveBeenLastCalledWith("1770000");
    const cleared = {...props, pinned: null, state: {...props.state, pinnedStationId: null}};
    expect(nodes(RadialDemo(cleared)).filter(node => node.type === RecordChart)).toHaveLength(1);
    expect(nodes(RadialDemo(cleared)).filter(node => node.type === SupportView)).toHaveLength(1);
    expect(renderToStaticMarkup(<RadialDemo {...cleared}/>)).toContain("No reference pinned");
  });
  it("retains DART non-applicability, real zero, unknown datum and safe source behavior", () => {
    const props = input();
    const unsafeStation = {...stations[0], source: {...stations[0].source, url: "javascript:alert(1)"}};
    const html = renderToStaticMarkup(<RadialDemo {...props} selected={{...props.selected, station: unsafeStation}}/>);
    expect(html).toContain("Not applicable");
    expect(html).toContain("First 0 at");
    expect(html).toContain("unknown");
    expect(html).toContain("Source QC retained");
    expect(html).not.toContain("javascript:");
    expect(html).toContain("Source link unavailable");
  });
  it("never renders retained measurements under loading/error identities and retries exact station", () => {
    const props = {...input(), pinned: null};
    const loading = {...props, selected: {...props.selected, status: "loading" as const}};
    expect(nodes(RadialDemo(loading)).filter(node => node.type === RecordChart || node.type === SupportView)).toHaveLength(0);
    expect(renderToStaticMarkup(<RadialDemo {...loading}/>)).toContain("Loading and verifying Test station 1617760");
    const failed = {...props, selected: {...props.selected, status: "error" as const, error: "test hash mismatch"}};
    expect(nodes(RadialDemo(failed)).filter(node => node.type === RecordChart || node.type === SupportView)).toHaveLength(0);
    click(failed, "Retry Test station 1617760");
    expect(props.onRetryStation).toHaveBeenCalledExactlyOnceWith("1617760");
    expect(renderToStaticMarkup(<RadialDemo {...failed}/>)).toContain("test hash mismatch");
  });
  it("keeps locator failure recoverable and same-station pin explicitly non-independent", () => {
    const props = input();
    const same = {...props, pinned: props.selected, state: {...props.state, pinnedStationId: "1617760"}, geometryError: "test locator mismatch"};
    click(same, "Retry locator");
    expect(props.onRetryGeometry).toHaveBeenCalledOnce();
    const html = renderToStaticMarkup(<RadialDemo {...same}/>);
    expect(html).toContain("same station");
    expect(html).toContain("not independent comparison evidence");
    expect(html).toContain("test locator mismatch");
  });
});
