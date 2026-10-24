import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { validateManifest, decodeStation, validateGeometry, fetchVerifiedAsset } from "./loader";
import { selectWindow, localYDomain } from "./chart";
import { RecordChart } from "./RecordChart";
import { SupportView } from "./SupportView";
import { readDemoJson as json, readDemoBytes } from "./integration-data";

const manifest = () => validateManifest(json("manifest.json"));

describe("verified descriptive boundary", () => {
  it("accepts the exact ten station identities, and rejects schema/release/cohort drift", () => {
    const m = manifest();
    expect(m.stations.map(s => s.station_id)).toEqual(["1617760","1770000","21413","21418","32401","46411","9419750","9461380","saip","valp"]);
    const raw = json("manifest.json") as Record<string, unknown>;
    expect(() => validateManifest({...raw, schema_version:"2"})).toThrow();
    expect(() => validateManifest({...raw, stations:m.stations.slice(1)})).toThrow();
    expect(() => validateManifest({...raw, release:{...m.release,arrival_comparison_allowed:true}})).toThrow();
    expect(() => validateManifest({...raw, event:{...m.event,event_id:"other"}})).toThrow();
  });
  it("rejects unsafe asset paths and credential-bearing source links", () => {
    const m = manifest();
    expect(() => validateManifest({...m,assets:[...m.assets,{path:"../secret",bytes:1,sha256:"a".repeat(64)}]})).toThrow();
    expect(() => validateManifest({...m,stations:m.stations.map((s,i)=>i ? s : {...s,source:{...s.source,url:"https://user:pass@example.org/x"}})})).toThrow();
    expect(() => validateManifest({...m,stations:m.stations.map((s,i)=>i ? s : {...s,source_extra:{private:"secret"}})})).toThrow();
  });
  it("verifies actual UTF8 bytes including Valparaíso; rejects bytes/hash/network failures", async () => {
    const m = manifest(); const asset = m.assets.find(a=>a.path==="stations/valp.json")!;
    const bytes = readDemoBytes(asset.path);
    const request = async () => new Response(new Uint8Array(bytes));
    expect(await fetchVerifiedAsset(m, asset.path, undefined, request)).toHaveProperty("station_id","valp");
    await expect(fetchVerifiedAsset({...m,assets:[{...asset,bytes:1}]},asset.path,undefined,request)).rejects.toThrow(/byte/i);
    await expect(fetchVerifiedAsset({...m,assets:[{...asset,sha256:"0".repeat(64)}]},asset.path,undefined,request)).rejects.toThrow(/hash/i);
    await expect(fetchVerifiedAsset(m,asset.path,undefined,async()=>new Response("",{status:404}))).rejects.toThrow();
  });
  it("validates geometry identity, projection and finite coordinates", () => {
    const m=manifest(); const raw=json("geometry.json") as Record<string,unknown>;
    expect(validateGeometry(raw,m).points).toHaveLength(11);
    expect(()=>validateGeometry({...raw,central_meridian:0},m)).toThrow();
    expect(()=>validateGeometry({...raw,points:[]},m)).toThrow();
  });
});

describe("actual rows and chart math",()=>{
  it("rejects product-availability drift",()=>{
    const m=manifest();const station=m.stations.find(s=>s.station_id==="saip")!;
    expect(()=>decodeStation(json("stations/saip.json"),{...station,products:station.products.map(p=>({...p,available:true}))},m)).toThrow();
  });
  it("rejects repeated observation timestamps",()=>{
    const m=manifest();const station=m.stations.find(s=>s.station_id==="saip")!;
    const repeated=json("stations/saip.json") as {rows:unknown[][]};repeated.rows[1][4]=repeated.rows[0][4];
    expect(()=>decodeStation(repeated,station,m)).toThrow();
  });
  it("rejects unsupported reviewed span categories",()=>{
    const m=manifest();const station=m.stations.find(s=>s.station_id==="saip")!;
    const badSpan=json("stations/saip.json") as {coverage_spans:Record<string,unknown>[]};badSpan.coverage_spans[0].status="invented";
    expect(()=>decodeStation(badSpan,station,m)).toThrow();
  });
  it("decodes and reconciles all ten actual station chunks with no invented or rejected rows",()=>{
    const m=manifest();let total=0;
    for(const station of m.stations){const records=decodeStation(json(`stations/${station.station_id}.json`),station,m);total+=records.rows.length;expect(selectWindow(records,"source_full").rows).toHaveLength(station.observation_count);}
    expect(total).toBe(143655);
  });
  it("decodes zero, blanks, QC, off-grid and products without substitution",()=>{
    const m=manifest();
    const saip=decodeStation(json("stations/saip.json"),m.stations.find(s=>s.station_id==="saip")!,m);
    expect(saip.rows.some(r=>r.grid_status==="off_grid")).toBe(true);
    expect(saip.rows[0].residual_value).toBe(null);
    const hilo=decodeStation(json("stations/1617760.json"),m.stations[0],m);
    expect(hilo.rows.some(r=>r.raw_value===null&&r.raw_status==="source_blank")).toBe(true);
    const valp=decodeStation(json("stations/valp.json"),m.stations.find(s=>s.station_id==="valp")!,m);
    expect(valp.rows.some(r=>r.raw_value===0&&r.source_qc_status==="flagged")).toBe(true);
    const s=selectWindow(saip,"common_day");
    expect(s.rows).toHaveLength(764);
    expect(s.support.product_valid_n.residual_value).toBe(0);
    expect(localYDomain(s.rows,"residual_value")).toBe(null);
    const bad=json("stations/saip.json") as {rows:unknown[][]}; bad.rows[0][5]="zero";
    expect(()=>decodeStation(bad,m.stations.find(s=>s.station_id==="saip")!,m)).toThrow();
  });
  it("retains final DART source_full row at last+1 microsecond; common intervals stay half open",()=>{
    const m=manifest(); const station=m.stations.find(s=>s.station_id==="21418")!;
    const records=decodeStation(json("stations/21418.json"),station,m);
    expect(selectWindow(records,"source_full").rows.at(-1)).toBe(records.rows.at(-1));
    expect(selectWindow(records,"source_full").rows).toHaveLength(station.observation_count);
    const common=selectWindow(records,"common_day");
    expect(common.rows).toHaveLength(1222);
    expect(common.rows.every(r=>r.observed_at_utc<"2011-03-12T00:00:00Z")).toBe(true);
  });
  it("renders actual source/product/datum and distinguishes coastal coverage from DART timestamps",()=>{
    const m=manifest(); const hilo=m.stations[0]; const records=decodeStation(json("stations/1617760.json"),hilo,m);
    const html=renderToStaticMarkup(<RecordChart station={hilo} records={records} windowId="common_day" productKey="raw_value" role="selected"/>);
    expect(html).toContain("STND"); expect(html).toContain("Raw coastal water level"); expect(html).not.toContain("NaN");
    expect(renderToStaticMarkup(<SupportView station={hilo} records={records} windowId="common_day" productKey="raw_value"/>)).toContain("98.0556");
    const dart=m.stations.find(s=>s.station_id==="21418")!;
    const d=decodeStation(json("stations/21418.json"),dart,m);
    const support=renderToStaticMarkup(<SupportView station={dart} records={d} windowId="common_day" productKey="raw_value"/>);
    expect(support).toContain("Not applicable"); expect(support).toContain("1222"); expect(support).toContain("900");
  });
});
