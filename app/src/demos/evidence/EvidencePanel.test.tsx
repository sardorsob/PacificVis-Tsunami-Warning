import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidencePanel } from "./EvidencePanel";
import { evidencePage } from "./paging";
import type { CoastalSupport, DemoManifest, EvidenceProps, Observation, StationMetadata, StationRecords } from "../types";

// Explicit test-only inputs; never an application fallback or ignored-bundle import.
const station: StationMetadata = {
  station_id: "test", source_id: "source-test", station_type: "coastal", name: "Test station",
  units: "m", vertical_reference: "unknown", horizontal_datum: "unknown", coordinate_order: "longitude,latitude",
  time_basis: "UTC", latitude: 0, longitude: 0, observation_count: 3,
  products: [{ key: "raw_value", label: "Raw test level", units: "m", available: true }, { key: "residual_value", label: "Publisher test residual", units: "m", available: false }, { key: "fitted_value", label: "Publisher test fitted tide", units: "m", available: false }],
  source: { source_id: "source-test", title: "Test source title", publisher: "Test publisher", accessed_on: "2026-10-24", version_or_date: "Test version", license_or_terms: "Test terms", processing_level: "Test processing", sha256: "a".repeat(64), url: "https://example.org/records" },
};
const row = (id: string, observed_at_utc: string, value: number | null): Observation => ({ observation_id: id, source_id: station.source_id, station_id: station.station_id, source_time: observed_at_utc, observed_at_utc, raw_value: value, fitted_value: null, residual_value: null, units: "m", vertical_reference: "unknown", raw_status: value === null ? "source_blank" : "observed", residual_status: "source_blank", grid_status: "on_grid", qc_flags: {}, source_qc_status: "not_reported" });
const rows: Observation[] = [
  { ...row("zero-row", "2011-03-11T00:00:00Z", 0), qc_flags: { out_of_range: "T" }, source_qc_status: "flagged" },
  row("blank-row", "2011-03-11T00:01:00Z", null),
  { ...row("off-grid-row", "2011-03-11T00:02:30.123456Z", 1.23456789), grid_status: "off_grid" },
  row("excluded-end", "2011-03-12T00:00:00Z", 9),
];
const support: CoastalSupport = { station_id: "test", window_id: "common_day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z", accepted_sample_n: 3, valid_sample_n: 2, source_blank_n: 1, product_valid_n: { raw_value: 2, residual_value: 0, fitted_value: 0 }, support_kind: "coastal_exact_grid", strict_numerator_n: 1, strict_denominator_n: 1440, strict_percent: 0.0694, expected_n: 1440, cadence_seconds: 60, source_grid_anchor_utc: "2011-03-11T00:00:00Z", absent_n: 1438, off_grid_n: 1, off_grid_valid_n: 1, exact_valid_n: 1, sample_density_numerator_n: 2, sample_density_denominator_n: 1440, sample_density_percent: 0.1389, supported_start_utc: "unknown", supported_end_utc_exclusive: "unknown", first_grid_utc: "unknown", last_grid_utc: "unknown", first_valid_raw_utc: "unknown", last_valid_raw_utc: "unknown" };
const records: StationRecords = { schema_version: "1", station_id: "test", rows, support: [support, { ...support, window_id: "source_full", end_utc_exclusive: "2011-03-12T00:00:00.000001Z" }], coverage_spans: [], gap_blocks: [] };
const manifest: DemoManifest = { schema_version: "1", exporter_version: "1", bundle_id: "test-only", evidence_state: "internal_descriptive_only", event: { event_id: "test-event", origin_time_utc: "2011-03-11T05:46:24.120Z", latitude: 0, longitude: 0 }, release: { release_id: "test-release", arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy", allowed_uses: [], prohibited_uses: [] }, default_state: { selectedStationId: "test", pinnedStationId: null, windowId: "common_day", productKey: "raw_value" }, windows: [{ id: "common_day", label: "Common day" }, { id: "source_full", label: "Full source" }], stations: [station], assets: [], geometry_path: "geometry.json", input_fingerprints: [{ path: "private-do-not-display", sha256: "b".repeat(64) }], config_sha256: "c".repeat(64), accounting: { source_observation_count: 4, exported_observation_count: 4, station_count: 1, rejected_observation_count: 0 } };
const props: EvidenceProps = { manifest, station, records, windowId: "common_day", productKey: "raw_value", onClose: () => {} };
const render = (overrides: Partial<EvidenceProps> = {}) => renderToStaticMarkup(<EvidencePanel {...props} {...overrides} />);

describe("portable exact evidence panel", () => {
  it("retains zero, source blank, flagged and off-grid inputs without rounding values or filtering to chart points", () => {
    const html = render();
    expect(html).toContain('<th scope="row">zero-row</th><td>0</td>');
    expect(html).toContain("blank-row</th><td>null</td>");
    expect(html).toContain("off-grid-row</th><td>1.23456789</td>");
    expect(html).toContain("2011-03-11T00:02:30.123456Z");
    for (const text of ["source_blank", "flagged", "out_of_range", "off_grid", "not_reported"]) expect(html).toContain(text);
    expect(html).not.toContain("excluded-end");
    expect(html).toContain("Raw test level (m)");
  });
  it("uses the selected product, keeps nulls explicit and does not substitute raw values", () => {
    const html = render({ productKey: "residual_value" });
    expect(html).toContain("Publisher test residual (m)");
    expect(html).toContain("zero-row</th><td>null</td>");
    expect(html).toContain("Unavailable for this station");
    expect(html).toContain("0 non-null selected-product values / 3 source rows");
  });
  it("shows allowlisted provenance and explicit unknowns without leaking fingerprint paths", () => {
    const html = render();
    for (const text of ["Test publisher", "Test source title", "2026-10-24", "Test version", "Test terms", "Test processing", "a".repeat(64), "Horizontal datum", "Vertical reference", "Source time basis", "unknown", "UTC"]) expect(html).toContain(text);
    expect(html).toContain('href="https://example.org/records"');
    expect(html).not.toContain("private-do-not-display");
    expect(html).toContain("not proof of scientific validity");
    expect(html).toContain("Descriptive records, not validated arrivals or warning time.");
  });
  it.each([null, "javascript:alert(1)", "http://example.org", "https://name:secret@example.org", "https://example.org/?token=secret"])("does not create a publisher link for unsafe or absent URL %s", url => {
    const html = render({ station: { ...station, source: { ...station.source, url } } });
    expect(html).not.toContain("href=");
    expect(html).not.toContain("secret");
    expect(html).toContain("Publisher link unavailable");
  });
  it("preserves reviewed coastal denominators separately from product counts", () => {
    const html = render();
    expect(html).toContain("0.0694% (1/1440)");
    expect(html).toContain("0.1389% (2/1440)");
    expect(html).toContain("2 non-null selected-product values / 3 source rows");
    expect(html).toContain("Off-grid samples do not fill exact-grid gaps");
  });
  it("keeps DART coastal percentages not applicable rather than inferring completeness", () => {
    const dart = { station_id: "test", window_id: "common_day", start_utc: support.start_utc, end_utc_exclusive: support.end_utc_exclusive, accepted_sample_n: 3, valid_sample_n: 2, source_blank_n: 1, product_valid_n: support.product_valid_n, support_kind: "dart_actual_timestamps" as const, strict_numerator_n: null, strict_denominator_n: null, strict_percent: null, cadence_seconds_counts: [{ seconds: 15, count: 2 }] };
    const html = render({ records: { ...records, support: [dart] } });
    expect(html).toContain("Strict coastal-grid coverage: Not applicable");
    expect(html).toContain("15s × 2");
    expect(html).not.toContain("0%");
  });
  it("labels full-source bounds as station-specific and retains its final row", () => {
    const html = render({ windowId: "source_full" });
    expect(html).toContain("Full source record — station-specific bounds");
    expect(html).toContain("Not a common comparison period");
    expect(html).toContain("2011-03-12T00:00:00.000001Z");
    expect(html).toContain("excluded-end");
  });
  it("provides labeled native dialog/table semantics and a visible native Close control", () => {
    const html = render();
    expect(html).toMatch(/<dialog[^>]*aria-labelledby="[^"]+"[^>]*aria-describedby="[^"]+"/);
    expect(html).toContain('type="button">Close</button>');
    expect(html).toContain('role="region" aria-label="Exact observation rows — horizontally scrollable" tabindex="0"');
    expect(html).toContain("<caption>");
    expect(html).toContain('<th scope="col">Observation ID</th>');
    expect(html).toContain('type="number"');
  });
  it("shows empty selected windows without fabricating measurement rows", () => {
    const html = render({ records: { ...records, rows: [], support: [{ ...support, accepted_sample_n: 0, valid_sample_n: 0, product_valid_n: { raw_value: 0, residual_value: 0, fitted_value: 0 } }] } });
    expect(html).toContain("No source observation rows in this reviewed window");
    expect(html).not.toContain('<th scope="row">');
  });
  it("bounds the rendered DOM for 109422 rows and offers direct page entry", () => {
    const many = Array.from({ length: 109422 }, (_, i) => ({ ...rows[0], observation_id: `large-${i}` }));
    const html = render({ records: { ...records, rows: many } });
    expect(html.match(/<th scope="row">large-/g)).toHaveLength(50);
    expect(html).not.toContain("large-50</th>");
    expect(html).toContain('max="2189"');
  });
  it("pairs Previous and Next ahead of the page field, so phones show them on one row in focus order", () => {
    const html = render({ records: { ...records, rows: Array.from({ length: 120 }, (_, i) => ({ ...rows[0], observation_id: `p-${i}` })) } });
    const paging = html.slice(html.indexOf('class="evidence__paging"'));
    expect(paging.indexOf(">Previous<")).toBeLessThan(paging.indexOf(">Next<"));
    expect(paging.indexOf(">Next<")).toBeLessThan(paging.indexOf("Page <input"));
    expect(paging).toContain('class="evidence__step"');
  });
  it("keeps reviewed span classifications/endpoints inspectable and bounds their table too", () => {
    const span = { station_id: "test", window_id: "common_day", start_utc: "2011-03-11T00:01:00Z", end_utc_exclusive: "2011-03-11T00:02:00Z", status: "source_blank", absent_n: 0, source_blank_n: 1, affected_position_n: 1, classification: "publisher_blank", classification_semantics: "test classification semantics", endpoint_semantics: "test endpoint semantics", left_observed_utc: "unknown", right_observed_utc: "2011-03-11T00:02:30.123456Z", within_block_valid_raw_n: 0 };
    const html = render({ records: { ...records, coverage_spans: [span], gap_blocks: Array.from({ length: 101 }, () => span) } });
    expect(html).toContain("Coverage spans (1)");
    expect(html).toContain("Gap blocks (101)");
    expect(html).toContain("publisher_blank");
    expect(html).toContain("test classification semantics");
    expect(html).toContain("test endpoint semantics");
    expect(html.match(/<td>publisher_blank<\/td>/g)).toHaveLength(51);
  });
  it("shows a visible horizontal-scroll cue before each rendered evidence table", () => {
    const span = { station_id: "test", window_id: "common_day", start_utc: "2011-03-11T00:01:00Z", end_utc_exclusive: "2011-03-11T00:02:00Z", status: "source_blank", absent_n: 0, source_blank_n: 1, affected_position_n: 1, classification: "publisher_blank", classification_semantics: "test classification semantics", endpoint_semantics: "test endpoint semantics", left_observed_utc: "unknown", right_observed_utc: "2011-03-11T00:02:30.123456Z", within_block_valid_raw_n: 0 };
    const html = render({ records: { ...records, coverage_spans: [span], gap_blocks: [span] } });
    expect(html.split("Scroll sideways to inspect all columns.")).toHaveLength(4);
  });
});

describe("evidence paging bounds and selection identity", () => {
  it("clamps first/last/invalid page entry and keeps the last partial page reachable", () => {
    const values = Array.from({ length: 109422 }, (_, i) => i);
    expect(evidencePage(values, 2189, "same", "same").rows).toEqual([109400,109401,109402,109403,109404,109405,109406,109407,109408,109409,109410,109411,109412,109413,109414,109415,109416,109417,109418,109419,109420,109421]);
    expect(evidencePage(values, 99999, "same", "same").page).toBe(2189);
    for (const page of [-1, 0, NaN, Infinity]) expect(evidencePage(values, page, "same", "same").page).toBe(1);
    expect(evidencePage([], 10, "same", "same")).toEqual({ page: 1, pageCount: 1, start: 0, end: 0, rows: [] });
  });
  it.each(["station-b|common_day|raw_value", "station-a|source_full|raw_value", "station-a|common_day|residual_value"])("resets to first page when station/window/product changes: %s", identity => {
    expect(evidencePage(Array.from({ length: 101 }, (_, i) => i), 3, "station-a|common_day|raw_value", identity).rows[0]).toBe(0);
  });
});
