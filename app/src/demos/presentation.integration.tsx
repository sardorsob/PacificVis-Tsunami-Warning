import { expect,it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { validateManifest,validateGeometry,decodeStation } from "./loader";
import { RecordChart } from "./RecordChart";
import { PairedView } from "./story/PairedView";
import type { StoryViewProps } from "./story/StoryView";
import type { StationSelection } from "./types";
import { readDemoJson as json } from "./integration-data";

const manifest=validateManifest(json("manifest.json"));
const geometry=validateGeometry(json("geometry.json"),manifest);
const pick=(id:string):StationSelection=>{const station=manifest.stations.find(s=>s.station_id===id)!;return {station,status:"ready",error:null,records:decodeStation(json(`stations/${id}.json`),station,manifest)};};
const noop=()=>undefined;
const props:StoryViewProps={manifest,geometry,geometryError:null,layers:null,layersError:null,layersPending:null,onRetryLayers:noop,
  state:{view:"paired",...manifest.default_state,pinnedStationId:null},selected:pick("1617760"),pinned:null,onOpenEvidence:noop,onRetryStation:noop,
  onRetryGeometry:noop,params:{t:7.5,compare:false,step:1,at:null,z:1,from:null},onNav:noop,restoreKey:0,evidenceOpen:false,issues:[],onDismissIssues:noop,
  onState:noop,initialSize:{w:1440,h:900}};
it("keeps every real station reachable on the map band and names A and B by role",()=>{
  const html=renderToStaticMarkup(<PairedView {...props} state={{...props.state,pinnedStationId:"saip"}} pinned={pick("saip")}/>);
  expect(html.match(/class="paired-station[^"]*"/g)).toHaveLength(10);
  expect(html).toContain("Selected A: Hilo");expect(html).toContain("Pinned reference B: Saipan");expect(html).toContain("Equal Earth");
});
it("shows real source next to selected data, retains explicit clear-pin state and scoped error identity",()=>{
  const html=renderToStaticMarkup(<PairedView {...props}/>);
  expect(html).toContain("Hilo");expect(html).toContain("Selected");expect(html).toContain("No reference pinned");expect(html).toContain("NOAA Center");expect(html).not.toContain("Fictional");
  const failed=renderToStaticMarkup(<PairedView {...props} selected={{station:manifest.stations[1],status:"error",error:"hash mismatch",records:null}}/>);
  expect(failed).toContain(manifest.stations[1].name);expect(failed).toContain("hash mismatch");expect(failed).toContain("Retry");expect(failed).not.toContain("record-points");
});
it("labels multi-day full-source ticks with dates and never substitutes unavailable product",()=>{
  const station=manifest.stations.find(s=>s.station_id==="21418")!;
  const records=decodeStation(json("stations/21418.json"),station,manifest);
  const html=renderToStaticMarkup(<RecordChart station={station} records={records} windowId="source_full" productKey="raw_value" role="selected"/>);
  expect(html).toContain("03-01");expect(html).toContain("Station-specific full source");expect(html).toContain("m water column");
  expect(renderToStaticMarkup(<RecordChart station={props.selected.station} records={props.selected.records!} windowId="common_day" productKey="residual_value" role="selected"/>)).toContain("No other product substituted");
});
