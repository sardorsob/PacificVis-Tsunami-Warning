import { createHash } from "node:crypto";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { readDemoJson, readLayersBytes, readLayersJson } from "../integration-data";
import { decodeStation, validateManifest } from "../loader";
import { RecordChart } from "../RecordChart";
import { nearestHours, validateCoastline, validateContours, validateLayersManifest } from "./layers";
import { validateSteps } from "./steps";
import { StoryView } from "./StoryView";
import type { DemoGeometry } from "../types";

const manifest = validateManifest(readDemoJson("manifest.json"));
const layers = validateLayersManifest(readLayersJson("manifest.json"));

describe("story view against the accepted local bundles", () => {
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
        selected={{ station, status: "loading", records: null, error: null }} pinned={null} onSelectStation={noop} onOpenEvidence={noop}
        onRetryStation={noop} onRetryGeometry={noop} params={{ t: 0, compare: false, step: 1, at: null, z: 1, from: null }}
        onNav={noop} restoreKey={0} evidenceOpen={false} issues={[]} onDismissIssues={noop} onState={noop} initialSize={initialSize}/>);
      expect(html, `${initialSize.w}×${initialSize.h}`).toContain('story-lens-title__name">Tōhoku epicentre<');
    }
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
});
