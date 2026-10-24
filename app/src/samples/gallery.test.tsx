import { describe, expect, it } from "vitest";
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
    expect(sampleDefinitions.map((sample) => sample.id)).toEqual(["paired-atlas"]);
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
});
