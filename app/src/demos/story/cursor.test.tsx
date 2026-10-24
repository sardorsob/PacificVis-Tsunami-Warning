import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RecordChart } from "../RecordChart";
import { SupportView } from "../SupportView";
import type { Observation, StationMetadata, StationRecords } from "../types";

// Typed test-only inputs. Never imported by a runtime renderer or scientific bundle.
const station: StationMetadata = {
  station_id: "test", source_id: "test-only", station_type: "dart", name: "Test station", units: "m", vertical_reference: "unknown",
  horizontal_datum: "unknown", coordinate_order: "longitude,latitude", time_basis: "UTC", latitude: 0, longitude: 0, observation_count: 3,
  products: [
    { key: "raw_value", label: "Test raw measurement", units: "m", available: true },
    { key: "residual_value", label: "Test residual", units: "m", available: false },
    { key: "fitted_value", label: "Test fitted", units: "m", available: false },
  ],
  source: { source_id: "test-only", title: "Test-only source", publisher: "Test publisher", accessed_on: "unknown", version_or_date: "unknown", license_or_terms: "unknown", processing_level: "test-only", sha256: "0".repeat(64), url: null },
};
const row = (at: string, raw: number): Observation => ({ observation_id: at, source_id: "test-only", station_id: "test", source_time: at, observed_at_utc: at,
  raw_value: raw, fitted_value: null, residual_value: null, units: "m", vertical_reference: "unknown", raw_status: "observed",
  residual_status: "source_blank", grid_status: "not_applicable", qc_flags: {}, source_qc_status: "not_reported" });
const records: StationRecords = { schema_version: "1", station_id: "test",
  rows: [row("2011-03-11T02:00:00Z", 1), row("2011-03-11T10:00:00Z", 0), row("2011-03-11T20:00:00Z", 2)],
  support: [{ station_id: "test", window_id: "common_day", start_utc: "2011-03-11T00:00:00Z", end_utc_exclusive: "2011-03-12T00:00:00Z", accepted_sample_n: 3, valid_sample_n: 3,
    source_blank_n: 0, product_valid_n: { raw_value: 3, residual_value: 0, fitted_value: 0 }, support_kind: "dart_actual_timestamps", strict_numerator_n: null, strict_denominator_n: null,
    strict_percent: null, cadence_seconds_counts: [{ seconds: 28800, count: 1 }, { seconds: 36000, count: 1 }] }],
  coverage_spans: [], gap_blocks: [] };
const props = { station, records, windowId: "common_day", productKey: "raw_value" as const };
const dots = (html: string) => (html.match(/h0\.01/g) ?? []).length;

describe("story clock on records", () => {
  it("marks the clock without hiding, moving or adding a point", () => {
    const plain = renderToStaticMarkup(<RecordChart {...props} role="selected" />);
    const timed = renderToStaticMarkup(<RecordChart {...props} role="selected" cursorMs={Date.parse("2011-03-11T12:00:00Z")} />);
    expect(plain).not.toContain("clock-cursor");
    expect(timed).toContain("clock-cursor");
    expect(timed).toContain("record-points--after");
    expect(dots(timed)).toBe(dots(plain));
    expect(dots(plain)).toBe(3);
  });
  it("drops the cursor outside the window instead of clamping it", () => {
    expect(renderToStaticMarkup(<RecordChart {...props} role="selected" cursorMs={Date.parse("2011-03-12T03:00:00Z")} />)).not.toContain("clock-cursor");
  });
  it("gives compact support the same cursor and keeps zero distinct from a gap", () => {
    const html = renderToStaticMarkup(<SupportView {...props} compact cursorMs={Date.parse("2011-03-11T12:00:00Z")} />);
    expect(html).toContain("clock-cursor");
    expect(html).toContain("not zeros");
    expect(html).not.toContain("<details");
  });
});
