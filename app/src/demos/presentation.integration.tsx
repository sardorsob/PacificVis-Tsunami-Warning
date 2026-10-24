import { expect,it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { validateManifest,validateGeometry,decodeStation } from "./loader";
import { StationMap } from "./StationMap";
import { PairedDemo } from "./PairedDemo";
import { RecordChart } from "./RecordChart";
import type { RadialProps } from "./types";
import { readDemoJson as json } from "./integration-data";

const manifest=validateManifest(json("manifest.json"));
const geometry=validateGeometry(json("geometry.json"),manifest);
const props:RadialProps={manifest,geometry,geometryError:null,state:{view:"paired",...manifest.default_state},selected:{station:manifest.stations[0],status:"ready",error:null,records:decodeStation(json("stations/1617760.json"),manifest.stations[0],manifest)},pinned:null,onSelectStation:()=>{},onOpenEvidence:()=>{},onRetryStation:()=>{},onRetryGeometry:()=>{}};
it("keeps every real station keyboard reachable and roles redundantly named",()=>{
  const html=renderToStaticMarkup(<StationMap geometry={geometry} stations={manifest.stations} selectedStationId="1617760" pinnedStationId="saip" onSelectStation={()=>{}}/>);
  expect(html.match(/type="button"/g)).toHaveLength(10);
  expect(html).toContain("Selected: Hilo");expect(html).toContain("Pinned reference: Saipan");expect(html).toContain("Equal Earth");
});
it("shows real source next to selected data, retains explicit clear-pin state and scoped error identity",()=>{
  const html=renderToStaticMarkup(<PairedDemo {...props}/>);
  expect(html).toContain("Hilo");expect(html).toContain("Selected");expect(html).toContain("No reference pinned");expect(html).toContain("NOAA Center");expect(html).not.toContain("Fictional");
  const failed=renderToStaticMarkup(<PairedDemo {...props} selected={{station:manifest.stations[1],status:"error",error:"hash mismatch",records:null}}/>);
  expect(failed).toContain(manifest.stations[1].name);expect(failed).toContain("hash mismatch");expect(failed).toContain("Retry");expect(failed).not.toContain("record-points");
});
it("labels multi-day full-source ticks with dates and never substitutes unavailable product",()=>{
  const station=manifest.stations.find(s=>s.station_id==="21418")!;
  const records=decodeStation(json("stations/21418.json"),station,manifest);
  const html=renderToStaticMarkup(<RecordChart station={station} records={records} windowId="source_full" productKey="raw_value" role="selected"/>);
  expect(html).toContain("03-01");expect(html).toContain("Station-specific full source");expect(html).toContain("m water column");
  expect(renderToStaticMarkup(<RecordChart station={props.selected.station} records={props.selected.records!} windowId="common_day" productKey="residual_value" role="selected"/>)).toContain("No other product substituted");
});
