import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { readDemoJson } from "../integration-data";
import { decodeStation, validateGeometry, validateManifest } from "../loader";
import { RecordChart } from "../RecordChart";
import { SupportView } from "../SupportView";
import { PairedDemo } from "../PairedDemo";
import { StationMap } from "../StationMap";
import type { RadialProps, StationSelection } from "../types";
import { RadialDemo } from "./RadialDemo";

// Explicit opt-in actual-bundle tests. No generated scientific payload is committed.
const manifest = validateManifest(readDemoJson("manifest.json"));
const geometry = validateGeometry(readDemoJson("geometry.json"), manifest);
function selection(id: string): StationSelection {
  const station = manifest.stations.find(station => station.station_id === id)!;
  return {station, status: "ready", error: null, records: decodeStation(readDemoJson(`stations/${id}.json`), station, manifest)};
}
function input(): RadialProps {
  return {manifest, geometry, geometryError: null, state: {view: "radial", ...manifest.default_state}, selected: selection(manifest.default_state.selectedStationId), pinned: selection(manifest.default_state.pinnedStationId!), onSelectStation: vi.fn(), onOpenEvidence: vi.fn(), onRetryStation: vi.fn(), onRetryGeometry: vi.fn()};
}
type NodeProps = {children?: ReactNode; onClick?: () => void; "aria-label"?: string};
function nodes(node: ReactNode): ReactElement<NodeProps>[] {
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (!isValidElement<NodeProps>(node)) return [];
  return [node, ...nodes(node.props.children)];
}

it("matches paired actual measurement and support markup without rebinding or reprocessing", () => {
  const props = input();
  const radial = renderToStaticMarkup(<RadialDemo {...props}/>);
  const paired = renderToStaticMarkup(<PairedDemo {...props}/>);
  for (const [stationSelection, role] of [[props.selected, "selected"], [props.pinned!, "pinned"]] as const) {
    const chartProps = {station: stationSelection.station, records: stationSelection.records!, windowId: props.state.windowId, productKey: props.state.productKey};
    const chart = renderToStaticMarkup(<RecordChart {...chartProps} role={role}/>);
    const support = renderToStaticMarkup(<SupportView {...chartProps}/>);
    expect(radial).toContain(chart);
    expect(paired).toContain(chart);
    expect(radial).toContain(support);
    expect(paired).toContain(support);
  }
  expect(radial).toContain("98.0556");
  expect(radial).toContain("44.7222");
  expect(radial).toContain("53.0556");
  expect(radial).not.toContain("Fictional");
});

it("keeps ten actual station targets and forwards geographic selection without moving pin", () => {
  const props = input();
  const tree = nodes(RadialDemo(props));
  const map = tree.find(node => node.type === StationMap)!;
  expect(map.props).toMatchObject({stations: manifest.stations, selectedStationId: "1617760", pinnedStationId: "saip", onSelectStation: props.onSelectStation});
  const renderedMap = renderToStaticMarkup(<StationMap stations={manifest.stations} geometry={geometry} selectedStationId="1617760" pinnedStationId="saip" onSelectStation={props.onSelectStation}/>);
  expect(renderedMap.match(/type="button"/g)).toHaveLength(10);
  // StationMap has useMemo, so actual event dispatch belongs to browser QA;
  // the renderer boundary must retain the original callback identity.
  expect(manifest.stations.map(station => station.station_id)).toEqual(["1617760", "1770000", "21413", "21418", "32401", "46411", "9419750", "9461380", "saip", "valp"]);
  expect(renderToStaticMarkup(<RadialDemo {...props}/>)).toContain("Equal Earth");
});

it("retains station-specific full-source UTC intervals and DART non-applicable grid support", () => {
  const props = input();
  props.state = {...props.state, selectedStationId: "21418", windowId: "source_full"};
  props.selected = selection("21418");
  const html = renderToStaticMarkup(<RadialDemo {...props}/>);
  expect(html).toContain("Full source record — station-specific bounds");
  expect(html).toContain("not a common comparison period");
  expect(html).toContain("Strict coastal-grid coverage");
  expect(html).toContain("Not applicable");
  expect(html).toContain("m water column");
  for (const stationSelection of [props.selected, props.pinned!]) {
    const chart = renderToStaticMarkup(<RecordChart station={stationSelection.station} records={stationSelection.records!} windowId="source_full" productKey="raw_value" role={stationSelection === props.selected ? "selected" : "pinned"}/>);
    expect(html).toContain(chart);
  }
  expect(manifest.release).toMatchObject({arrival_comparison_allowed: false, physical_arrival_records_released: 0, continuous_nctr_field: "blocked_no_proxy"});
});
