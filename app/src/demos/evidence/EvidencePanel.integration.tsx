import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { decodeStation, validateManifest } from "../loader";
import { selectWindow } from "../chart";
import { readDemoJson } from "../integration-data";
import { EvidencePanel } from "./EvidencePanel";
import { evidencePage } from "./paging";

// Opt-in accepted local bundle only; never imported by *.test.ts(x).
const manifest = validateManifest(readDemoJson("manifest.json"));
function actual(stationId: string) {
  const station = manifest.stations.find(item => item.station_id === stationId)!;
  const records = decodeStation(readDemoJson(`stations/${stationId}.json`), station, manifest);
  return { manifest, station, records, onClose: () => {} };
}

it("renders Hilo exact raw/source-time cells and its reviewed original denominator", () => {
  const html = renderToStaticMarkup(<EvidencePanel {...actual("1617760")} windowId="common_day" productKey="raw_value" />);
  expect(html).toContain('1617760-2011-03-11T00:00:00Z</th><td>1.309</td>');
  expect(html).toContain('<td>2011-03-11 00:00</td>');
  expect(html).toContain("98.0556% (1412/1440)");
  expect(html).toContain("STND");
});

it("keeps all Saipan off-grid rows in selection and the separate strict/density denominators", () => {
  const props = actual("saip");
  const selection = selectWindow(props.records, "common_day");
  expect(selection.rows).toHaveLength(764);
  expect(selection.rows.filter(row => row.grid_status === "off_grid")).toHaveLength(120);
  const html = renderToStaticMarkup(<EvidencePanel {...props} windowId="common_day" productKey="raw_value" />);
  expect(html).toContain('saip-2011-03-11T00:00:00Z</th><td>2.239</td>');
  expect(html).toContain("44.7222% (644/1440)");
  expect(html).toContain("53.0556% (764/1440)");
});

it("puts the independently named Valparaíso flagged zero on direct page31 of source_full", () => {
  const props = actual("valp");
  const selection = selectWindow(props.records, "source_full");
  const page = evidencePage(selection.rows, 31, "valp|source_full|raw_value", "valp|source_full|raw_value");
  const target = page.rows.find(row => row.observation_id === "valp-2011-03-12T01:30:00Z");
  expect(target).toMatchObject({ source_time: "2011-03-12 01:30:00", observed_at_utc: "2011-03-12T01:30:00Z", raw_value: 0, raw_status: "observed", grid_status: "on_grid", source_qc_status: "flagged", qc_flags: { out_of_range: "T" } });
  const html = renderToStaticMarkup(<EvidencePanel {...props} windowId="source_full" productKey="raw_value" />);
  expect(html).toContain('valp-2011-03-11T00:01:00Z</th><td>4.462</td>');
  expect(html).toContain("unknown");
});

it("bounds the largest actual DART DOM and preserves exact selected residual without coastal percentages", () => {
  const props = actual("46411");
  const selection = selectWindow(props.records, "source_full");
  expect(selection.rows).toHaveLength(109422);
  const lastPage = evidencePage(selection.rows, 2189, "same", "same");
  expect(lastPage.rows).toHaveLength(22);
  expect(lastPage.rows.at(-1)).toBe(selection.rows.at(-1));
  const html = renderToStaticMarkup(<EvidencePanel {...props} windowId="source_full" productKey="residual_value" />);
  expect(html.match(/<th scope="row">46411-/g)).toHaveLength(50);
  expect(html).toContain('46411-2011-03-01T00:00:00Z</th><td>-0.00749</td>');
  expect(html).toContain('max="2189"');
  expect(html).toContain("Strict coastal-grid coverage: Not applicable");
  for (const item of manifest.input_fingerprints) expect(html).not.toContain(item.path);
});
