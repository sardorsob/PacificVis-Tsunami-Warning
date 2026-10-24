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
    expect(sampleDefinitions.map((sample) => sample.id)).toEqual(["paired-atlas", "radial-record", "radial-comparison", "timeline-map", "editorial-story", "mobile-inspector", "map-overlay-lens", "evidence-ledger"]);
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

  it.each([
    ["timeline-map", "Two records. One shared timeline."],
    ["editorial-story", "What a record leaves unsaid."],
  ])("resolves and renders %s with distinct narrative hierarchy and disclosed evidence", (id, title) => {
    const sample = resolveSample(`?sample=${id}`);
    expect(sample.id).toBe(id);
    const html = renderToStaticMarkup(<sample.Component />);
    expect(html).toContain(`class="${id}"`);
    expect(html).toContain(title);
    expect(html).toContain("Invented examples");
    expect(html).toContain("not scientific results");
    expect(html).toContain("Fictional");
    expect(html).toContain("Station A");
    expect(html).toContain("Station B");
    expect(html).toContain("Schematic Pacific");
    expect(html.match(/<svg /g)?.length).toBeGreaterThanOrEqual(5);
    expect(html.match(/data-trace-segment=/g)).toHaveLength(4);
    expect(html).toContain("Water-level trace");
    expect(html).toContain("Observation coverage");
    expect(html).toContain("Unavailable");
  });

  it("leads the timeline with a shared linear rail and embeds editorial evidence in reading order", () => {
    const timeline = resolveSample("?sample=timeline-map");
    const timelineHtml = renderToStaticMarkup(<timeline.Component />);
    expect(timelineHtml).toContain('aria-label="Shared elapsed example time"');
    expect(timelineHtml).toContain("0–60 minutes");
    expect(timelineHtml.indexOf('aria-label="Shared elapsed example time"')).toBeLessThan(timelineHtml.indexOf('aria-label="Station A evidence"'));
    const story = resolveSample("?sample=editorial-story");
    const storyHtml = renderToStaticMarkup(<story.Component />);
    expect(storyHtml).toContain('<article class="editorial-story__essay"');
    expect(storyHtml.indexOf("First, a place to look.")).toBeLessThan(storyHtml.indexOf('aria-label="Station A evidence"'));
    expect(storyHtml.indexOf('aria-label="Station A evidence"')).toBeLessThan(storyHtml.indexOf('aria-label="Station B evidence"'));
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

  it("opens the mobile inspector with Station A owning the map highlight and both upright charts", () => {
    const sample = resolveSample("?sample=mobile-inspector");
    expect(sample.id).toBe("mobile-inspector");
    const html = renderToStaticMarkup(<sample.Component />);
    expect(html).toContain('class="mobile-inspector"');
    expect(html).toContain("Invented examples");
    expect(html).toContain("not scientific results");
    expect(html).toContain("Fictional");
    expect(html).toContain("Schematic Pacific");
    expect(html).toContain('<label for="mobile-inspector-station">Inspect station</label>');
    expect(html).toContain('<option value="station-a" selected="">Station A</option>');
    expect(html).toContain('<option value="station-b">Station B</option>');
    expect(html).toContain('aria-label="Station A inspector"');
    expect(html).toContain("Open-ocean example");
    expect(html).toContain('aria-label="Station A water-level trace"');
    expect(html).toContain('aria-label="Station A observation coverage"');
    expect(html).toContain('Station A: invented water-level trace');
    expect(html).toContain('Station A: illustrative observation coverage');
    expect(html).toContain('transform="translate(243.2 167.2)"><circle r="17" fill="none" stroke="#a94625"');
    expect(html).toContain('transform="translate(435.20000000000005 235.6)"><circle r="17" fill="none" stroke="#32696e"');
    expect(html.match(/data-trace-segment=/g)).toHaveLength(2);
    expect(html).toContain("Unavailable");
    expect(html.indexOf("Schematic Pacific")).toBeLessThan(html.indexOf('aria-label="Station A inspector"'));
  });

  it.each(["map-overlay-lens", "evidence-ledger"])("resolves and renders %s with disclosed real chart content", (id) => {
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
    expect(html.match(/data-trace-segment=/g)).toHaveLength(4);
    expect(html).toContain("minutes");
    expect(html).toContain("cm");
    expect(html).toContain("Unavailable");
  });

  it("labels the map-overlay lens as stationary and gives its chart panels explicit station ownership", () => {
    const sample = resolveSample("?sample=map-overlay-lens");
    const html = renderToStaticMarkup(<sample.Component />);
    expect(html).toContain("Static appearance study · not draggable");
    expect(html).toContain('aria-label="Station A water-level trace"');
    expect(html).toContain('aria-label="Station A observation coverage"');
    expect(html).toContain('aria-label="Station B reference trace"');
    expect(html).toContain("Below the map on small screens");
    expect(html.match(/<svg /g)).toHaveLength(4);
  });

  it("renders all 13 paired fixture values in a native table with units and explicit missingness", () => {
    const sample = resolveSample("?sample=evidence-ledger");
    const html = renderToStaticMarkup(<sample.Component />);
    const table = html.match(/<table[\s\S]*?<\/table>/)?.[0] ?? "";
    expect(table).toContain("<caption>");
    expect(table).toContain("Invented examples");
    expect(table).toContain("not scientific results");
    expect(table).toContain('<th scope="col">Elapsed example time (minutes)</th>');
    expect(table).toContain('<th scope="col">Station A (cm)</th>');
    expect(table).toContain('<th scope="col">Station B (cm)</th>');
    const rows = table.match(/<tr><th scope="row">[\s\S]*?<\/tr>/g) ?? [];
    expect(rows).toHaveLength(13);
    expect(rows[0]).toBe('<tr><th scope="row">0</th><td>0</td><td>0</td></tr>');
    expect(rows[2]).toBe('<tr><th scope="row">10</th><td>-1</td><td>Unavailable</td></tr>');
    expect(rows[5]).toBe('<tr><th scope="row">25</th><td>Unavailable</td><td>5</td></tr>');
    expect(rows[12]).toBe('<tr><th scope="row">60</th><td>1</td><td>0</td></tr>');
    for (const [index, point] of stationFixtures[0].points.entries()) {
      const second = stationFixtures[1].points[index];
      expect(rows[index]).toBe(`<tr><th scope="row">${point.minute}</th><td>${point.value ?? "Unavailable"}</td><td>${second.value ?? "Unavailable"}</td></tr>`);
    }
    expect(table.match(/<td>Unavailable<\/td>/g)).toHaveLength(4);
    expect(html.indexOf('aria-label="Aligned station traces"')).toBeLessThan(html.indexOf("<table"));
  });

  it("keeps a literal space between inspector headline sentences when the responsive break is hidden", () => {
    const sample = resolveSample("?sample=mobile-inspector");
    const html = renderToStaticMarkup(<sample.Component />);
    const heading = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1] ?? "";
    expect(heading.replace(/<br\s*\/?\s*>/g, "")).toBe("A place above. A record below.");
  });
});
