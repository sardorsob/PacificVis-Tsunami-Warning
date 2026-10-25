import { describe,expect,it } from "vitest";
import { localYDomain,pointPath,selectWindow } from "./chart";
import { LatestRequest,STATION_IDS,utcMicros } from "./loader";
import { parseState,serializeState } from "./state";
import { parseStoryParams,type StoryParams } from "./story/url";
import type { DemoManifest,Observation,StationRecords } from "./types";
import { isShortLandscape,plotDateContext } from "./layout";

// Deliberate unit-test input, not an observation fixture or application fallback.
const manifest:DemoManifest={
  schema_version:"1",exporter_version:"1",bundle_id:"test-selection-only",evidence_state:"internal_descriptive_only",
  event:{event_id:"test",origin_time_utc:"2011-03-11T05:46:24.120Z",latitude:0,longitude:0},
  release:{release_id:"test",arrival_comparison_allowed:false,physical_arrival_records_released:0,continuous_nctr_field:"blocked_no_proxy",allowed_uses:[],prohibited_uses:[]},
  default_state:{selectedStationId:"1617760",pinnedStationId:"saip",windowId:"common_day",productKey:"raw_value"},
  windows:[{id:"common_day",label:"Common day",start_utc:"2011-03-11T00:00:00Z",end_utc_exclusive:"2011-03-12T00:00:00Z"},{id:"source_full",label:"Full source"}],
  stations:STATION_IDS.map(station_id=>({station_id,source_id:"test",station_type:"coastal",name:station_id,units:"m",vertical_reference:"unknown",horizontal_datum:"unknown",coordinate_order:"test",time_basis:"UTC",latitude:0,longitude:0,observation_count:0,products:[],source:{source_id:"test",title:"test",publisher:"test",accessed_on:"unknown",version_or_date:"unknown",license_or_terms:"unknown",processing_level:"test",sha256:"0".repeat(64),url:null}})),
  assets:[],geometry_path:"geometry.json",input_fingerprints:[],config_sha256:"0".repeat(64),accounting:{source_observation_count:0,exported_observation_count:0,station_count:10,rejected_observation_count:0},
};
const row=(observed_at_utc:string,raw_value:number|null):Observation=>({observation_id:observed_at_utc,source_id:"test",station_id:"test",source_time:observed_at_utc,observed_at_utc,raw_value,fitted_value:null,residual_value:null,units:"m",vertical_reference:"unknown",raw_status:raw_value===null?"source_blank":"observed",residual_status:"source_blank",grid_status:"not_applicable",qc_flags:{},source_qc_status:"not_reported"});

describe("asset-independent chart and exact-time invariants",()=>{
  it("uses compact locator defaults only in short wide viewports",()=>{
    expect(isShortLandscape(844,390)).toBe(true);
    expect(isShortLandscape(390,844)).toBe(false);
    expect(isShortLandscape(1440,1000)).toBe(false);
  });
  it("keeps UTC date context adjacent to a plot even when the interval line is below screen",()=>{
    expect(plotDateContext("2011-03-11T00:00:00Z","2011-03-12T00:00:00Z")).toBe("2011-03-11 → 2011-03-12 UTC");
    expect(plotDateContext("2011-03-11T05:46:24.120Z","2011-03-11T11:46:24.120Z")).toBe("2011-03-11 UTC");
  });
  it("uses local finite y-domains including real zero and water-column offsets",()=>{
    expect(localYDomain([{raw_value:0},{raw_value:10},{raw_value:null}],"raw_value")).toEqual([-0.5,10.5]);
    expect(localYDomain([{raw_value:5000},{raw_value:5001}],"raw_value")).toEqual([4999.95,5001.05]);
    expect(localYDomain([{raw_value:null}],"raw_value")).toBe(null);
  });
  it("makes independent point marks rather than connecting across a blank",()=>{
    expect(pointPath([row("2011-03-11T00:00:00Z",0),row("2011-03-11T00:02:00Z",null)],"raw_value",()=>10,()=>20)).toBe("M10,20h0.01");
  });
  it("preserves last+1 microsecond and rejects invalid UTC values",()=>{
    expect(utcMicros("2011-03-20T00:00:00.000001Z")-utcMicros("2011-03-20T00:00:00Z")).toBe(1n);
    expect(()=>utcMicros("2011-02-30T00:00:00Z")).toThrow();
    expect(()=>utcMicros("2011-03-20T00:00:00+01:00")).toThrow();
  });
  it("uses a half-open common interval and retains every full-source row",()=>{
    const rows=[row("2011-03-11T00:00:00Z",0),row("2011-03-12T00:00:00Z",1)];
    const base={station_id:"test",accepted_sample_n:2,valid_sample_n:2,source_blank_n:0,product_valid_n:{raw_value:2,fitted_value:0,residual_value:0},support_kind:"dart_actual_timestamps" as const,strict_numerator_n:null,strict_denominator_n:null,strict_percent:null,cadence_seconds_counts:[]};
    const records:StationRecords={schema_version:"1",station_id:"test",rows,coverage_spans:[],gap_blocks:[],support:[{...base,window_id:"common_day",start_utc:"2011-03-11T00:00:00Z",end_utc_exclusive:"2011-03-12T00:00:00Z"},{...base,window_id:"source_full",start_utc:"2011-03-11T00:00:00Z",end_utc_exclusive:"2011-03-12T00:00:00.000001Z"}]};
    expect(selectWindow(records,"common_day").rows).toEqual([rows[0]]);
    expect(selectWindow(records,"source_full").rows).toEqual(rows);
    expect(()=>selectWindow(records,"not-reviewed")).toThrow(/unavailable/);
  });
});
describe("asset-independent shared URL and request ownership",()=>{
  it("round trips selected/pinned/view/window/product including deliberately cleared pin",()=>{
    const parsed=parseState("?view=radial&selected=21418&pinned=&window=source_full&product=residual_value",manifest);
    expect(parsed.issues).toEqual([]);expect(parsed.state.pinnedStationId).toBe(null);
    // Every view carries the shared clock and lens fields, so switching views keeps the moment.
    const story:StoryParams={t:4.5,compare:false,step:"explore",at:[1,2],z:2,from:4};
    const url=serializeState(parsed.state,story);
    expect(url).toBe("?view=radial&selected=21418&pinned=&window=source_full&product=residual_value&t=4.5&cmp=0&step=explore&at=1,2&z=2&from=4");
    expect(parseState(url,manifest)).toEqual({state:parsed.state,issues:[]});
    expect(parseStoryParams(url)).toEqual({params:story,issues:[]});
    expect(parseState("",manifest).state.pinnedStationId).toBe("saip");
    expect(parseState("",manifest).state.view).toBe("story"); // a plain link opens the story
  });
  it("repairs each invalid URL value visibly and reports repeated/unknown fields",()=>{
    const invalid=parseState("?selected=evil&window=missing&product=no&view=other&pinned=missing",manifest);
    expect(invalid.issues).toHaveLength(5);expect(invalid.state.selectedStationId).toBe("1617760");
    expect(parseState("?selected=21418&selected=1617760&extra=x",manifest).issues).toHaveLength(2);
  });
  it("never returns stale data and aborts superseded/cancelled requests",async()=>{
    const requests=new LatestRequest<string>();let resolveOld:(value:string)=>void=()=>{};
    const old=requests.run(async signal=>{expect(signal.aborted).toBe(false);return new Promise<string>(resolve=>{resolveOld=resolve;});});
    expect(await requests.run(async()=>"new")).toBe("new");resolveOld("old");expect(await old).toBe(undefined);
    let signal:AbortSignal|undefined;
    const pending=requests.run(async s=>{signal=s;return new Promise<string>(resolve=>{resolveOld=resolve;});});
    requests.cancel();expect(signal?.aborted).toBe(true);resolveOld("cancelled");expect(await pending).toBe(undefined);
  });
  it("ignores stale failures but surfaces active failures for visible retry",async()=>{
    const requests=new LatestRequest<string>();let rejectOld:(reason:Error)=>void=()=>{};
    const old=requests.run(async()=>new Promise<string>((_,reject)=>{rejectOld=reject;}));
    expect(await requests.run(async()=>"current")).toBe("current");rejectOld(new Error("late old failure"));expect(await old).toBe(undefined);
    await expect(requests.run(async()=>{throw new Error("current failure");})).rejects.toThrow("current failure");
  });
});
