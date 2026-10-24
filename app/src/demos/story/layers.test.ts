import { describe, expect, it } from "vitest";
import { hourPaths, labelAnchors, nearestHours, pointBetween, validateCoastline, validateContours, validateLayersManifest } from "./layers";

// Deliberate unit-test geometry; never a fallback for the real layers bundle.
const manifestInput = () => ({
  schema_version: "1", exporter_version: "1", bundle_id: "tohoku-story-layers-v1", evidence_state: "internal_descriptive_only",
  display_crs: "+proj=eqearth +lon_0=-160 +datum=WGS84 +units=m +no_defs +type=crs", central_meridian: -160, coordinate_order: "x,y",
  units: "metres (rounded to whole metres)", statement: "test statement", contour_source_id: "ncei-ttt-tohoku-layer17-geojson",
  coastline_source_id: "natural-earth-50m-coastline", origin_time_utc: "2011-03-11T05:46:24.120Z", hours_semantics: "test semantics",
  assets: [{ path: "coastline.json", sha256: "b".repeat(64), bytes: 1 }, { path: "contours.json", sha256: "a".repeat(64), bytes: 1 }],
  input_fingerprints: [], config_sha256: "c".repeat(64),
  accounting: { contour_features: 2, contour_parts: 2, contour_vertices: 4, hours: [1, 2], coastline_parts: 1 },
});
const manifest = validateLayersManifest(manifestInput());
const contours = validateContours({ schema_version: "1", source_id: "ncei-ttt-tohoku-layer17-geojson", features: [
  { hours: 1, index: false, parts: [[[0, 0], [1000, 0]]] },
  { hours: 2, index: false, parts: [[[0, 2000], [1000, 2000]]] },
] }, manifest);

describe("story map layers", () => {
  it("accepts only the reviewed layers bundle identity", () => {
    expect(() => validateLayersManifest({ ...manifestInput(), bundle_id: "other" })).toThrow(/identity/);
    expect(() => validateLayersManifest({ ...manifestInput(), display_crs: "+proj=merc" })).toThrow(/projection/);
  });
  it("rejects a contour cohort that disagrees with the manifest", () => {
    expect(() => validateContours({ schema_version: "1", source_id: "ncei-ttt-tohoku-layer17-geojson", features: [] }, manifest)).toThrow(/cohort/);
    expect(() => validateContours({ schema_version: "1", source_id: "ncei-ttt-tohoku-layer17-geojson", features: [
      { hours: 1, index: false, parts: [[[0.5, 0], [1000, 0]]] }, { hours: 2, index: false, parts: [[[0, 2000], [1000, 2000]]] },
    ] }, manifest)).toThrow(/coordinate/);
  });
  it("flips y once so paths and lookups share SVG space", () => {
    expect(hourPaths(contours).get(2)).toBe("M0 -2000L1000 -2000");
    const coast = validateCoastline({ schema_version: "1", source_id: "natural-earth-50m-coastline", parts: [[[0, 10], [5, 10], [0, 10]]], closed: [true] }, manifest);
    expect(coast.parts[0][0]).toEqual([0, -10]);
  });
  it("anchors index labels south-east of the epicentre and aims between two hours", () => {
    const indexed = contours.map(f => ({ ...f, index: true }));
    expect(labelAnchors(indexed, [-5000, -5000], 1e9).get(1)).toEqual([1000, -0]);
    expect(pointBetween(contours, [0, 0], 2)).toEqual([0, -1000]);
  });
  it("names the two nearest published hours, never an interpolated time", () => {
    expect(nearestHours(contours, 500, 900, 5000)).toEqual({ a: 1, b: 2 });
    expect(nearestHours(contours, 500, 90000, 5000)).toBeNull();
  });
});
