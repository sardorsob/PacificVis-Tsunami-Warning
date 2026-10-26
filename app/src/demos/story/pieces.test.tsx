import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { RecordChart, type RecordChartProps } from "../RecordChart";
import { NoReference, StationCard, type StationCardProps } from "../StationCard";
import { SupportView, type SupportViewProps } from "../SupportView";
import { STATION_IDS } from "../loader";
import type { StationMetadata, StationRecords, StationSelection } from "../types";
import { StationTools, type StationToolsProps } from "./StationTools";
import { ViewSwitch } from "./ViewSwitch";

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
const card = (selection: StationSelection, extra: Partial<StationCardProps> = {}): StationCardProps => ({
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
});
