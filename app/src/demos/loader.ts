import type { Asset, DemoGeometry, DemoManifest, Observation, StationMetadata, StationRecords } from "./types";

export const MANIFEST_URL = "/data/tohoku-descriptive-demo-v2/manifest.json";
export const STATION_IDS = ["1617760","1770000","21413","21418","32401","46411","9419750","9461380","saip","valp"] as const;
export const PRODUCT_KEYS = ["raw_value","residual_value","fitted_value"] as const;
export const COLUMNS = ["observation_id","source_id","station_id","source_time","observed_at_utc","raw_value","fitted_value","residual_value","units","vertical_reference","raw_status","residual_status","grid_status","qc_flags","source_qc_status"] as const;
const WINDOW_IDS = ["common_day","event_minus4_to_0h","event_0_to_6h","event_6_to_12h","event_12_to_18h","source_full"];
type Obj = Record<string,unknown>;
function requireValue(valid: unknown, message: string): asserts valid { if (!valid) throw new Error(`Demo data rejected: ${message}`); }
function object(value: unknown): Obj { requireValue(value !== null && typeof value === "object" && !Array.isArray(value),"expected object"); return value as Obj; }
function keys(value: Obj, allowed: readonly string[]) { requireValue(Object.keys(value).every(k=>allowed.includes(k)) && allowed.every(k=>k in value),"unexpected or missing fields"); }
function text(value: unknown): asserts value is string { requireValue(typeof value === "string" && value.length>0,"expected nonempty text"); }
function finite(value: unknown): asserts value is number { requireValue(typeof value === "number" && Number.isFinite(value),"expected finite number"); }
function count(value: unknown): asserts value is number { finite(value); requireValue(Number.isInteger(value)&&value>=0,"expected nonnegative count"); }
function hash(value: unknown) { requireValue(typeof value === "string" && /^[a-f0-9]{64}$/.test(value),"invalid SHA256"); }
function array(value: unknown): unknown[] { requireValue(Array.isArray(value),"expected array"); return value; }
function strings(value: unknown) { array(value).forEach(text); }
function oneOf(value: unknown, values: readonly unknown[]) { requireValue(values.includes(value),"unsupported value"); }
export function utcMicros(value: string): bigint {
  const match=/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?Z$/.exec(value);
  requireValue(match,"invalid UTC timestamp"); const ms=Date.parse(`${match[1]}Z`);
  requireValue(Number.isFinite(ms) && new Date(ms).toISOString().slice(0,19)===match[1],"invalid UTC date");
  return BigInt(ms)*1000n + BigInt((match[2]??"").padEnd(6,"0"));
}
function time(value: unknown) { text(value); utcMicros(value); }
function interval(value: Obj) { time(value.start_utc); time(value.end_utc_exclusive); requireValue(utcMicros(value.start_utc as string)<utcMicros(value.end_utc_exclusive as string),"invalid half-open interval"); }
export function safeSourceUrl(value: string | null): string | null {
  if(value===null) return null;
  try { const u=new URL(value); return u.protocol==="https:"&&!u.username&&!u.password&&!u.search&&!u.hash&&!/\s/.test(value) ? value : null; } catch { return null; }
}
function asset(value: unknown): Asset {
  const a=object(value); keys(a,["path","sha256","bytes"]); text(a.path); hash(a.sha256); count(a.bytes);
  requireValue(a.bytes>0 && /^(geometry\.json|stations\/[a-zA-Z0-9_-]+\.json)$/.test(a.path),"unsafe asset path"); return a as Asset;
}
export function validateManifest(input: unknown): DemoManifest {
  const m=object(input); keys(m,["schema_version","exporter_version","bundle_id","evidence_state","event","release","windows","default_state","stations","assets","geometry_path","input_fingerprints","config_sha256","accounting"]);
  requireValue(m.schema_version==="1"&&m.exporter_version==="1"&&m.bundle_id==="tohoku-descriptive-demo-v2"&&m.evidence_state==="internal_descriptive_only","unsupported schema or evidence release");
  const event=object(m.event); keys(event,["event_id","origin_time_utc","latitude","longitude"]);
  requireValue(event.event_id==="official20110311054624120_30"&&event.origin_time_utc==="2011-03-11T05:46:24.120Z"&&event.latitude===38.297&&event.longitude===142.373,"event identity mismatch");
  const release=object(m.release); keys(release,["release_id","arrival_comparison_allowed","physical_arrival_records_released","continuous_nctr_field","allowed_uses","prohibited_uses"]);
  requireValue(release.release_id==="tohoku-descriptive-v1"&&release.arrival_comparison_allowed===false&&release.physical_arrival_records_released===0&&release.continuous_nctr_field==="blocked_no_proxy","release restriction mismatch");
  strings(release.allowed_uses); strings(release.prohibited_uses);
  requireValue(JSON.stringify(release.allowed_uses)===JSON.stringify(["descriptive_data_quality","preliminary_story_diagnostics"])&&JSON.stringify(release.prohibited_uses)===JSON.stringify(["physical_arrival_comparison","modeled_minus_observed_residual","community_timing_selection","actionable_warning_time","operational_warning","public_story_scene_promotion"]),"release uses mismatch");
  const windows=array(m.windows); requireValue(windows.length===6,"window cohort mismatch");
  const expectedBounds=[["2011-03-11T00:00:00Z","2011-03-12T00:00:00Z"],["2011-03-11T01:46:24.120Z","2011-03-11T05:46:24.120Z"],["2011-03-11T05:46:24.120Z","2011-03-11T11:46:24.120Z"],["2011-03-11T11:46:24.120Z","2011-03-11T17:46:24.120Z"],["2011-03-11T17:46:24.120Z","2011-03-11T23:46:24.120Z"]];
  windows.forEach((v,i)=>{const w=object(v); keys(w,i===5?["id","label"]:["id","label","start_utc","end_utc_exclusive"]); requireValue(w.id===WINDOW_IDS[i],"window identity mismatch");text(w.label); if(i<5){interval(w); requireValue(w.start_utc===expectedBounds[i][0]&&w.end_utc_exclusive===expectedBounds[i][1],"window bounds mismatch");}});
  const stations=array(m.stations); requireValue(stations.length===10,"station cohort mismatch");
  stations.forEach((v,i)=>{
    const s=object(v); keys(s,["station_id","source_id","station_type","name","units","vertical_reference","horizontal_datum","coordinate_order","time_basis","latitude","longitude","observation_count","source","products"]);
    requireValue(s.station_id===STATION_IDS[i],"station identity mismatch");oneOf(s.station_type,["coastal","dart"]);
    requireValue(s.station_type===(["21413","21418","32401","46411"].includes(s.station_id as string)?"dart":"coastal"),"station type mismatch");
    for(const key of ["source_id","name","units","vertical_reference","horizontal_datum","coordinate_order","time_basis"])text(s[key]);
    finite(s.latitude);finite(s.longitude);requireValue(Math.abs(s.latitude)<=90&&Math.abs(s.longitude)<=180,"invalid coordinates");count(s.observation_count);
    const source=object(s.source); keys(source,["source_id","title","publisher","accessed_on","version_or_date","license_or_terms","processing_level","sha256","url"]);
    for(const key of ["source_id","title","publisher","accessed_on","version_or_date","license_or_terms","processing_level"])text(source[key]);hash(source.sha256);
    requireValue(source.source_id===s.source_id,"source identity mismatch");
    requireValue(source.url===null || typeof source.url==="string"&&safeSourceUrl(source.url)!==null,"unsafe source URL");
    const products=array(s.products);requireValue(products.length===3,"product cohort mismatch");products.forEach((v,j)=>{const p=object(v);keys(p,["key","label","units","available"]);requireValue(p.key===PRODUCT_KEYS[j],"product identity mismatch");text(p.label);text(p.units);requireValue(typeof p.available==="boolean","product availability missing");});
  });
  const defaults=object(m.default_state);keys(defaults,["selectedStationId","pinnedStationId","windowId","productKey"]);
  requireValue(defaults.selectedStationId==="1617760"&&defaults.pinnedStationId==="saip"&&defaults.windowId==="common_day"&&defaults.productKey==="raw_value","default state mismatch");
  const assets=array(m.assets).map(asset);requireValue(assets.length===11&&new Set(assets.map(a=>a.path)).size===11&&assets.some(a=>a.path==="geometry.json")&&STATION_IDS.every(id=>assets.some(a=>a.path===`stations/${id}.json`)),"asset cohort mismatch");
  requireValue(m.geometry_path==="geometry.json","geometry path mismatch");hash(m.config_sha256);
  array(m.input_fingerprints).forEach(v=>{const f=object(v);keys(f,["path","sha256"]);text(f.path);requireValue(!f.path.startsWith("/")&&!f.path.split("/").includes(".."),"unsafe fingerprint path");hash(f.sha256);});
  const accounting=object(m.accounting);keys(accounting,["source_observation_count","exported_observation_count","station_count","rejected_observation_count"]);Object.values(accounting).forEach(count);
  requireValue(accounting.source_observation_count===143655&&accounting.exported_observation_count===143655&&accounting.station_count===10&&accounting.rejected_observation_count===0&&stations.reduce<number>((sum,s)=>sum+Number(object(s).observation_count),0)===143655,"accounting mismatch");
  return m as DemoManifest;
}

export async function fetchVerifiedAsset(manifest: DemoManifest,path: string,signal?: AbortSignal,request: typeof fetch=fetch): Promise<unknown> {
  const descriptor=manifest.assets.find(a=>a.path===path);requireValue(descriptor,"asset not in manifest");asset(descriptor);
  const response=await request(`/data/${manifest.bundle_id}/${path}`,{signal,credentials:"omit",redirect:"error"});requireValue(response.ok,`asset HTTP ${response.status}`);
  const bytes=await response.arrayBuffer();signal?.throwIfAborted();requireValue(bytes.byteLength===descriptor.bytes,"asset byte count mismatch");
  const digest=await crypto.subtle.digest("SHA-256",bytes); const actual=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,"0")).join("");
  signal?.throwIfAborted();requireValue(actual===descriptor.sha256,"asset hash mismatch");
  return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)) as unknown;
}
export async function loadManifest(signal?: AbortSignal): Promise<DemoManifest> {
  const response=await fetch(MANIFEST_URL,{signal,credentials:"omit",redirect:"error"});requireValue(response.ok,`manifest HTTP ${response.status}`);return validateManifest(await response.json());
}
export function validateGeometry(input: unknown,manifest: DemoManifest): DemoGeometry {
  const g=object(input);keys(g,["schema_version","source_crs","display_crs","coordinate_order","central_meridian","coastline","points","bounds"]);
  requireValue(g.schema_version==="1"&&g.source_crs==="EPSG:4326"&&g.coordinate_order==="x,y"&&g.central_meridian===-160,"geometry schema/projection mismatch");text(g.display_crs);requireValue(g.display_crs.includes("+proj=eqearth")&&g.display_crs.includes("+lon_0=-160"),"unreviewed projection");
  const bounds=array(g.bounds);requireValue(bounds.length===4,"bounds mismatch");bounds.forEach(finite); requireValue(Number(bounds[2])>Number(bounds[0])&&Number(bounds[3])>Number(bounds[1]),"invalid bounds");
  array(g.coastline).forEach(line=>{const points=array(line);requireValue(points.length>=2,"invalid coastline");points.forEach(point=>{const p=array(point);requireValue(p.length===2,"coordinate dimension");p.forEach(finite);});});
  const ids=[manifest.event.event_id,...STATION_IDS];const points=array(g.points);requireValue(points.length===11,"geometry point cohort mismatch");
  const seen=new Set<string>();points.forEach(v=>{const p=object(v);keys(p,["id","x","y"]);text(p.id);oneOf(p.id,ids);requireValue(!seen.has(p.id),"duplicate geometry point");seen.add(p.id);finite(p.x);finite(p.y);});
  return g as DemoGeometry;
}

const BASE_SUPPORT=["station_id","window_id","start_utc","end_utc_exclusive","accepted_sample_n","valid_sample_n","source_blank_n","product_valid_n","strict_numerator_n","strict_denominator_n","strict_percent","support_kind"];
const COASTAL_COUNTS=["expected_n","cadence_seconds","absent_n","off_grid_n","off_grid_valid_n","exact_valid_n","sample_density_numerator_n","sample_density_denominator_n"];
const COASTAL_TIMES=["source_grid_anchor_utc","supported_start_utc","supported_end_utc_exclusive","first_grid_utc","last_grid_utc","first_valid_raw_utc","last_valid_raw_utc"];
const SPAN_TEXT=["station_id","window_id","start_utc","end_utc_exclusive","status","classification","classification_semantics","endpoint_semantics","left_observed_utc","right_observed_utc"];
const SPAN_COUNTS=["absent_n","source_blank_n","affected_position_n","within_block_valid_raw_n"];
export function decodeStation(input: unknown,station: StationMetadata,manifest: DemoManifest): StationRecords {
  const s=object(input);keys(s,["schema_version","station_id","columns","rows","support","coverage_spans","gap_blocks"]);
  requireValue(s.schema_version==="1"&&s.station_id===station.station_id,"station chunk identity/schema mismatch");requireValue(JSON.stringify(s.columns)===JSON.stringify(COLUMNS),"record columns mismatch");
  const seen=new Set<string>();let previous=-1n;
  const rows=array(s.rows).map(value=>{
    const row=array(value);requireValue(row.length===15,"record width mismatch");for(const i of [0,1,2,3,4,8,9,10,11,12,14])text(row[i]);for(const i of [5,6,7])if(row[i]!==null)finite(row[i]);
    requireValue(row[1]===station.source_id&&row[2]===station.station_id&&row[8]===station.units&&row[9]===station.vertical_reference,"record metadata mismatch");
    const stamp=utcMicros(row[4] as string);const id=row[0] as string;requireValue(stamp>previous,"record order or duplicate timestamp");requireValue(!seen.has(id),"duplicate observation id");seen.add(id);previous=stamp;
    oneOf(row[10],["observed","source_blank"]);requireValue((row[5]===null)===(row[10]==="source_blank"),"raw status mismatch");
    oneOf(row[11],["available","source_blank","structurally_not_applicable"]);requireValue(station.station_type==="dart"?row[11]===(row[7]===null?"source_blank":"available"):row[11]==="structurally_not_applicable","residual status mismatch");
    oneOf(row[12],station.station_type==="dart"?["not_applicable"]:["on_grid","off_grid"]);oneOf(row[14],["flagged","not_flagged","not_reported"]);
    const qc=object(row[13]);for(const [key,value] of Object.entries(qc)){oneOf(key,["completeness","distinctness","exceeded_neighbours","flat_line","missing","out_of_range","shift","spikes_via_median"]);requireValue(value===null||typeof value==="string"||typeof value==="boolean"||typeof value==="number"&&Number.isFinite(value),"invalid QC encoding");}
    return Object.fromEntries(COLUMNS.map((key,i)=>[key,row[i]])) as Observation;
  });
  requireValue(rows.length===station.observation_count,"station observation count mismatch");
  for(const product of station.products)requireValue(product.available===rows.some(r=>r[product.key]!==null),"product availability mismatch");
  const support=array(s.support);requireValue(support.length===6,"support window cohort mismatch");const supportWindows=new Set<string>();
  support.forEach(value=>{
    const p=object(value);const coastal=station.station_type==="coastal";keys(p,[...BASE_SUPPORT,...(coastal?[...COASTAL_COUNTS,...COASTAL_TIMES,"sample_density_percent"]:["cadence_seconds_counts"])]);
    requireValue(p.station_id===station.station_id,"support station mismatch");oneOf(p.window_id,WINDOW_IDS);text(p.window_id);requireValue(!supportWindows.has(p.window_id),"duplicate support window");supportWindows.add(p.window_id);interval(p);
    requireValue(p.support_kind===(coastal?"coastal_exact_grid":"dart_actual_timestamps"),"support kind mismatch");
    for(const key of ["accepted_sample_n","valid_sample_n","source_blank_n"])count(p[key]);const products=object(p.product_valid_n);keys(products,PRODUCT_KEYS);Object.values(products).forEach(count);
    for(const key of ["strict_numerator_n","strict_denominator_n"])if(p[key]!==null)count(p[key]);if(p.strict_percent!==null){finite(p.strict_percent);requireValue(p.strict_percent>=0&&p.strict_percent<=100,"invalid strict percentage");}
    if(coastal){for(const key of COASTAL_COUNTS)if(p[key]!==null)count(p[key]);for(const key of COASTAL_TIMES){text(p[key]);if(p[key]!=="unknown")time(p[key]);}if(p.sample_density_percent!==null){finite(p.sample_density_percent);requireValue(p.sample_density_percent>=0&&p.sample_density_percent<=100,"invalid density percentage");}}
    else{requireValue(p.strict_percent===null&&p.strict_numerator_n===null&&p.strict_denominator_n===null,"DART cannot have coastal completeness");array(p.cadence_seconds_counts).forEach(v=>{const c=object(v);keys(c,["seconds","count"]);finite(c.seconds);requireValue(c.seconds>0,"invalid actual cadence");count(c.count);});}
    const window=manifest.windows.find(w=>w.id===p.window_id)!;
    if(window.id!=="source_full") requireValue(utcMicros(p.start_utc as string)===utcMicros(window.start_utc!)&&utcMicros(p.end_utc_exclusive as string)===utcMicros(window.end_utc_exclusive!),"support interval mismatch");
    const start=utcMicros(p.start_utc as string),end=utcMicros(p.end_utc_exclusive as string);
    const intervalRows=rows.filter(r=>{const t=utcMicros(r.observed_at_utc);return t>=start&&t<end;});
    requireValue(intervalRows.length===p.accepted_sample_n&&intervalRows.filter(r=>r.raw_value!==null).length===p.valid_sample_n&&intervalRows.filter(r=>r.raw_value===null).length===p.source_blank_n,"support row accounting mismatch");
    for(const key of PRODUCT_KEYS)requireValue(intervalRows.filter(r=>r[key]!==null).length===products[key],"support product accounting mismatch");
    if(window.id==="source_full")requireValue(intervalRows.length===rows.length,"source_full does not contain all rows");
  });
  for(const field of ["coverage_spans","gap_blocks"]){const spans=array(s[field]);if(station.station_type==="dart")requireValue(spans.length===0,"DART cannot have coastal grid spans");spans.forEach(value=>{const p=object(value);keys(p,[...SPAN_TEXT,...SPAN_COUNTS]);SPAN_TEXT.forEach(k=>text(p[k]));SPAN_COUNTS.forEach(k=>count(p[k]));requireValue(p.station_id===station.station_id,"span station mismatch");oneOf(p.window_id,WINDOW_IDS);oneOf(p.status,["observed","source_blank","absent_timestamp"]);interval(p);});}
  return {schema_version:"1",station_id:station.station_id,rows,support:support as StationRecords["support"],coverage_spans:s.coverage_spans as StationRecords["coverage_spans"],gap_blocks:s.gap_blocks as StationRecords["gap_blocks"]};
}

export class LatestRequest<T> {
  private version=0;
  private controller: AbortController | null=null;
  cancel() { this.version++;this.controller?.abort(); }
  async run(task: (signal: AbortSignal)=>Promise<T>): Promise<T | undefined> {
    this.cancel();const version=this.version;const controller=new AbortController();this.controller=controller;
    try{const result=await task(controller.signal);return version===this.version&&!controller.signal.aborted?result:undefined;}
    catch(error){if(version!==this.version||controller.signal.aborted)return undefined;throw error;}
  }
}
