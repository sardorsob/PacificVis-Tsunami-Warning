import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Gallery } from "./Gallery";
import { resolveSample, sampleDefinitions } from "./registry";
import { stationFixtures } from "./fixtures";
import { CoverageChart, StationMap, TraceChart } from "./primitives";

describe("sample gallery", () => {
  it("resolves URL selections and safely falls back for unknown or absent samples", () => {
    expect(resolveSample("?sample=paired-atlas").id).toBe("paired-atlas");
    expect(resolveSample("?sample=not-a-sample").id).toBe("paired-atlas");
    expect(resolveSample("").id).toBe("paired-atlas");
    expect(sampleDefinitions.map((sample) => sample.id)).toEqual(["paired-atlas", "radial-record", "radial-comparison"]);
  });

  it("renders the selected sample with visible illustrative disclosure and accessible navigation", () => {
    const html = renderToStaticMarkup(<Gallery search="?sample=paired-atlas" />);
    expect(html).toContain("Paired atlas");
    expect(html).toContain("Invented examples");
    expect(html).toContain("not scientific results");
    expect(html).toContain('href="?sample=paired-atlas"');
    expect(html).toContain("Station A");
    expect(html).toContain("Station B");
  });

  it("can render the default sample without a browser environment", () => {
    expect(renderToStaticMarkup(<Gallery />)).toContain("Paired atlas");
  });

  it.each(["radial-record", "radial-comparison"])("resolves and renders %s as a disclosed chart-bearing station lens", (id) => {
    const sample = resolveSample(`?sample=${id}`);
    expect(sample.id).toBe(id);
    const html = renderToStaticMarkup(<sample.Component />);
    expect(html).toContain(`class="${id}"`);
    expect(html).toContain("Invented examples");
    expect(html).toContain("not scientific results");
    expect(html).toContain("Fictional");
    expect(html).toContain("Station A");
    expect(html).toContain("Station B");
    expect(html).toContain("Schematic Pacific");
    expect(html.match(/<svg /g)?.length).toBeGreaterThanOrEqual(4);
    expect(html).toContain("Water-level trace");
    expect(html).toContain("Observation coverage");
    expect(html).toContain("Unavailable");
  });

  it("keeps the radial record arms semantically separate and the comparison owners explicit", () => {
    const record = resolveSample("?sample=radial-record");
    const recordHtml = renderToStaticMarkup(<record.Component />);
    expect(recordHtml).toContain('aria-label="Station A water-level trace"');
    expect(recordHtml).toContain('aria-label="Station A observation coverage"');
    expect(recordHtml).toContain('aria-label="Station B comparison trace"');
    const comparison = resolveSample("?sample=radial-comparison");
    const comparisonHtml = renderToStaticMarkup(<comparison.Component />);
    expect(comparisonHtml).toContain("Pinned A");
    expect(comparisonHtml).toContain("Selected B");
    expect(comparisonHtml).toContain('aria-label="Pinned Station A record"');
    expect(comparisonHtml).toContain('aria-label="Selected Station B record"');
    expect(comparisonHtml).toContain("Static selection");
  });

  it("renders labeled SVG charts without connecting across missing observations", () => {
    const trace = renderToStaticMarkup(<TraceChart station={stationFixtures[0]} />);
    expect(trace).toContain("Invented examples");
    expect(trace).toContain("minutes");
    expect(trace).toContain("cm");
    expect(trace.match(/data-trace-segment=/g)).toHaveLength(2);
    const coverage = renderToStaticMarkup(<CoverageChart station={stationFixtures[0]} />);
    expect(coverage).toContain("Unavailable");
    expect(coverage).toContain("Invented examples");
    const map = renderToStaticMarkup(<StationMap stations={stationFixtures} />);
    expect(map).toContain("Schematic Pacific");
    expect(map).toContain("not to scale");
    expect(map).toContain("Station A");
    expect(map).toContain("Invented examples");
  });

  it("renders station-owned SVG titles without React title-children warnings", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const trace = renderToStaticMarkup(<TraceChart station={stationFixtures[0]} />);
      const coverage = renderToStaticMarkup(<CoverageChart station={stationFixtures[1]} />);
      expect(trace).toMatch(/<title[^>]*>Station A: invented water-level trace in cm/);
      expect(coverage).toMatch(/<title[^>]*>Station B: illustrative observation coverage/);
      expect(errors).not.toHaveBeenCalled();
    } finally {
      errors.mockRestore();
    }
  });
});
