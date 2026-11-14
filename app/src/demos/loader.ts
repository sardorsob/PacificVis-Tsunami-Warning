import type { Asset, BundleRef, DemoGeometry, DemoManifest, EventEntry, EventsIndex, Observation, StationMetadata, StationRecords } from "./types";

export const INDEX_URL = "/data/events.json";
export const PRODUCT_KEYS = ["raw_value","residual_value","fitted_value"] as const;
export const COLUMNS = ["observation_id","source_id","station_id","source_time","observed_at_utc","raw_value","fitted_value","residual_value","units","vertical_reference","raw_status","residual_status","grid_status","qc_flags","source_qc_status"] as const;
const SAFE_ID = /^[a-zA-Z0-9_-]+$/;
export type Obj = Record<string,unknown>;
export function requireValue(valid: unknown, message: string): asserts valid { if (!valid) throw new Error(`Demo data rejected: ${message}`); }
export function object(value: unknown): Obj { requireValue(value !== null && typeof value === "object" && !Array.isArray(value),"expected object"); return value as Obj; }
export function keys(value: Obj, allowed: readonly string[]) { requireValue(Object.keys(value).every(k=>allowed.includes(k)) && allowed.every(k=>k in value),"unexpected or missing fields"); }
export function text(value: unknown): asserts value is string { requireValue(typeof value === "string" && value.length>0,"expected nonempty text"); }
export function finite(value: unknown): asserts value is number { requireValue(typeof value === "number" && Number.isFinite(value),"expected finite number"); }
export function count(value: unknown): asserts value is number { finite(value); requireValue(Number.isInteger(value)&&value>=0,"expected nonnegative count"); }
export function hash(value: unknown) { requireValue(typeof value === "string" && /^[a-f0-9]{64}$/.test(value),"invalid SHA256"); }
export function array(value: unknown): unknown[] { requireValue(Array.isArray(value),"expected array"); return value; }
function strings(value: unknown) { array(value).forEach(text); }
export function oneOf(value: unknown, values: readonly unknown[]) { requireValue(values.includes(value),"unsupported value"); }
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
function bundleRef(value: unknown): BundleRef | null {
  if(value===null) return null; const b=object(value); keys(b,["bundle_id","manifest_sha256","manifest_bytes"]); text(b.bundle_id); hash(b.manifest_sha256); count(b.manifest_bytes);
  requireValue(SAFE_ID.test(b.bundle_id)&&b.manifest_bytes>0,"unsafe bundle reference"); return b as BundleRef;
}
const COUNTS=["ntwc_pairs","ntwc_pairs_with_position","ntwc_reported","ncei_reported","stations"];
/** events.json, schema 1 or 2: the browser's upstream anchor (itself not hash-checked); it pins every bundle manifest it lists.
 * Schema 2 ("Index schema 2") adds the shared basemap and, per event, the projected epicentre and display counts; schema 1 refuses them. */
export function validateIndex(input: unknown): EventsIndex {
  const x=object(input),two=x.schema_version==="2"; keys(x,["schema_version","evidence_state","default_event_id","events",...(two?["basemap"]:[])]);
  requireValue((x.schema_version==="1"||two)&&x.evidence_state==="internal_descriptive_only","unsupported events index");
  if(two){const b=object(x.basemap); keys(b,["path","sha256","bytes"]); text(b.path); hash(b.sha256); count(b.bytes);
    requireValue(b.bytes>0&&b.bytes<=2_097_152&&/^[a-zA-Z0-9_-]+\/coastline\.json$/.test(b.path),"unsafe basemap reference");}
  const events=array(x.events).map(object); requireValue(events.length>0,"empty events index"); const bundles=new Set<string>();
  events.forEach((e,i)=>{
    keys(e,["event_id","label","origin_time_utc","latitude","longitude","magnitude","magnitude_type","records","layers","arrivals",...(two?["x","y","counts"]:[])]);
    if(two){finite(e.x); finite(e.y); requireValue(Number.isInteger(e.x)&&Number.isInteger(e.y),"epicentre must be whole metres");
      const c=object(e.counts); keys(c,[...COUNTS,"reported_per_hour"]); COUNTS.forEach(k=>count(c[k])); const h=object(c.reported_per_hour); keys(h,["ntwc","ncei"]);
      for(const k of ["ntwc","ncei"]){const hours=array(h[k]); requireValue(hours.length===30,"reported_per_hour needs 30 hours"); hours.forEach(count);}}
    text(e.event_id); requireValue(SAFE_ID.test(e.event_id),"unsafe event id"); text(e.label); time(e.origin_time_utc); finite(e.magnitude); text(e.magnitude_type);
    finite(e.latitude); finite(e.longitude); requireValue(Math.abs(e.latitude)<=90&&Math.abs(e.longitude)<=180,"invalid coordinates");
    for(const ref of [bundleRef(e.records),bundleRef(e.layers)]) if(ref){requireValue(!bundles.has(ref.bundle_id),"bundle listed twice"); bundles.add(ref.bundle_id);}
    if(e.arrivals!==null){const a=object(e.arrivals); keys(a,["path","sha256","bytes"]); text(a.path); hash(a.sha256); count(a.bytes);
      requireValue(a.bytes>0&&a.bytes<=2_097_152&&/^[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+\.json$/.test(a.path)&&a.path.endsWith(`/${e.event_id}.json`),"unsafe arrivals reference");}
    requireValue(!events.slice(0,i).some(p=>p.event_id===e.event_id),"duplicate event id");
    // By origin instant (".5Z" is after "Z", though it sorts before it as text), then event id in code-point order (ids are ASCII).
    if(i){const p=events[i-1],a=utcMicros(p.origin_time_utc as string),b=utcMicros(e.origin_time_utc as string); requireValue(a<b||a===b&&(p.event_id as string)<e.event_id,"events out of order");}
  });
  requireValue(events.some(e=>e.event_id===x.default_event_id),"default event not listed");
  return x as EventsIndex;
}
/** A records manifest is checked against its index entry and its own structure; the index pins its exact bytes, so no fixed event values. */
export function validateManifest(input: unknown, entry: EventEntry): DemoManifest {
  requireValue(entry.records,"event has no records bundle");
  const m=object(input); keys(m,["schema_version","exporter_version","bundle_id","evidence_state","event","release","windows","default_state","stations","assets","geometry_path","input_fingerprints","config_sha256","accounting"]);
  requireValue(m.schema_version==="1"&&m.exporter_version==="1"&&m.evidence_state==="internal_descriptive_only","unsupported schema or evidence release");
  requireValue(m.bundle_id===entry.records.bundle_id,"bundle identity mismatch");
  const event=object(m.event); keys(event,["event_id","origin_time_utc","latitude","longitude"]);
  requireValue(event.event_id===entry.event_id&&event.origin_time_utc===entry.origin_time_utc&&event.latitude===entry.latitude&&event.longitude===entry.longitude,"event identity mismatch");
  const release=object(m.release); keys(release,["release_id","arrival_comparison_allowed","physical_arrival_records_released","continuous_nctr_field","allowed_uses","prohibited_uses"]);
  text(release.release_id); requireValue(release.arrival_comparison_allowed===false&&release.physical_arrival_records_released===0&&release.continuous_nctr_field==="blocked_no_proxy","release restriction mismatch");
  strings(release.allowed_uses); strings(release.prohibited_uses);
  requireValue(JSON.stringify(release.allowed_uses)===JSON.stringify(["descriptive_data_quality","preliminary_story_diagnostics"])&&JSON.stringify(release.prohibited_uses)===JSON.stringify(["physical_arrival_comparison","modeled_minus_observed_residual","community_timing_selection","actionable_warning_time","operational_warning","public_story_scene_promotion"]),"release uses mismatch");
  // Comparison windows are half-open intervals; an optional final source_full has station-specific bounds, so only id and label.
  const windows=array(m.windows).map(object); requireValue(windows.length>0,"window cohort mismatch");
  windows.forEach((w,i)=>{const full=w.id==="source_full"; requireValue(!full||i===windows.length-1,"window identity mismatch"); keys(w,full?["id","label"]:["id","label","start_utc","end_utc_exclusive"]); text(w.id); text(w.label); if(!full) interval(w);});
  requireValue(new Set(windows.map(w=>w.id)).size===windows.length,"duplicate window");
  const stations=array(m.stations); requireValue(stations.length>0,"station cohort mismatch");
  stations.forEach((v,i)=>{
    const s=object(v); keys(s,["station_id","source_id","station_type","name","units","vertical_reference","horizontal_datum","coordinate_order","time_basis","latitude","longitude","observation_count","source","products"]);
    // Strictly ascending station ids (unique); the chunk paths below keep them ASCII, so string order is code-point order.
    text(s.station_id); requireValue(i===0||String(object(stations[i-1]).station_id)<s.station_id,"station order or duplicate station"); oneOf(s.station_type,["coastal","dart"]);
    for(const key of ["source_id","name","units","vertical_reference","horizontal_datum","coordinate_order","time_basis"])text(s[key]);
    finite(s.latitude);finite(s.longitude);requireValue(Math.abs(s.latitude)<=90&&Math.abs(s.longitude)<=180,"invalid coordinates");count(s.observation_count);
    const source=object(s.source); keys(source,["source_id","title","publisher","accessed_on","version_or_date","license_or_terms","processing_level","sha256","url"]);
    for(const key of ["source_id","title","publisher","accessed_on","version_or_date","license_or_terms","processing_level"])text(source[key]);hash(source.sha256);
    requireValue(source.source_id===s.source_id,"source identity mismatch");
    requireValue(source.url===null || typeof source.url==="string"&&safeSourceUrl(source.url)!==null,"unsafe source URL");
    const products=array(s.products);requireValue(products.length===3,"product cohort mismatch");products.forEach((v,j)=>{const p=object(v);keys(p,["key","label","units","available"]);requireValue(p.key===PRODUCT_KEYS[j],"product identity mismatch");text(p.label);text(p.units);requireValue(typeof p.available==="boolean","product availability missing");});
  });
  const ids=stations.map(s=>object(s).station_id);const defaults=object(m.default_state);keys(defaults,["selectedStationId","pinnedStationId","windowId","productKey"]);
  // B is never A (the parseState rule); a null pin is allowed (one-station events).
  requireValue(ids.includes(defaults.selectedStationId)&&(defaults.pinnedStationId===null||ids.includes(defaults.pinnedStationId)&&defaults.pinnedStationId!==defaults.selectedStationId)&&windows.some(w=>w.id===defaults.windowId)&&(PRODUCT_KEYS as readonly unknown[]).includes(defaults.productKey),"default state mismatch");
  const assets=array(m.assets).map(asset);const paths=new Set(assets.map(a=>a.path));
  requireValue(assets.length===ids.length+1&&paths.size===assets.length&&paths.has("geometry.json")&&ids.every(id=>paths.has(`stations/${id}.json`)),"asset cohort mismatch");
  requireValue(m.geometry_path==="geometry.json","geometry path mismatch");hash(m.config_sha256);
  array(m.input_fingerprints).forEach(v=>{const f=object(v);keys(f,["path","sha256"]);text(f.path);requireValue(!f.path.startsWith("/")&&!f.path.split("/").includes(".."),"unsafe fingerprint path");hash(f.sha256);});
  const accounting=object(m.accounting);keys(accounting,["source_observation_count","exported_observation_count","station_count","rejected_observation_count"]);Object.values(accounting).forEach(count);
  const total=stations.reduce<number>((sum,s)=>sum+Number(object(s).observation_count),0);
  requireValue(accounting.station_count===ids.length&&accounting.exported_observation_count===total&&accounting.source_observation_count===accounting.exported_observation_count&&accounting.rejected_observation_count===0,"accounting mismatch");
  return m as DemoManifest;
}

export async function fetchHashed(url: string,byteCount: number,sha256: string,signal?: AbortSignal,request: typeof fetch=fetch): Promise<unknown> {
  const response=await request(url,{signal,credentials:"omit",redirect:"error"});requireValue(response.ok,`asset HTTP ${response.status}`);
  const bytes=await response.arrayBuffer();signal?.throwIfAborted();requireValue(bytes.byteLength===byteCount,"asset byte count mismatch");
  const digest=await crypto.subtle.digest("SHA-256",bytes); const actual=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,"0")).join("");
  signal?.throwIfAborted();requireValue(actual===sha256,"asset hash mismatch");
  return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)) as unknown;
}
export async function fetchVerifiedAsset(manifest: DemoManifest,path: string,signal?: AbortSignal,request: typeof fetch=fetch): Promise<unknown> {
  const descriptor=manifest.assets.find(a=>a.path===path);requireValue(descriptor,"asset not in manifest");asset(descriptor);
  return fetchHashed(`/data/${manifest.bundle_id}/${path}`,descriptor.bytes,descriptor.sha256,signal,request);
}
export async function loadIndex(signal?: AbortSignal,request: typeof fetch=fetch): Promise<EventsIndex> {
  const response=await request(INDEX_URL,{signal,credentials:"omit",redirect:"error"});requireValue(response.ok,`events index HTTP ${response.status}`);return validateIndex(await response.json());
}
/** The records manifest pinned by the index entry: byte count and SHA-256 are verified before it is parsed. */
export async function loadManifest(entry: EventEntry,signal?: AbortSignal,request: typeof fetch=fetch): Promise<DemoManifest> {
  // ponytail: a records-free event (allowed by the index) shows the load alert; its own screen is a later task.
  if(!entry.records)throw new Error("No station records are published for this event.");
  const ref=entry.records;return validateManifest(await fetchHashed(`/data/${ref.bundle_id}/manifest.json`,ref.manifest_bytes,ref.manifest_sha256,signal,request),entry);
}
export function validateGeometry(input: unknown,manifest: DemoManifest): DemoGeometry {
  const g=object(input);keys(g,["schema_version","source_crs","display_crs","coordinate_order","central_meridian","coastline","points","bounds"]);
  requireValue(g.schema_version==="1"&&g.source_crs==="EPSG:4326"&&g.coordinate_order==="x,y"&&g.central_meridian===-160,"geometry schema/projection mismatch");text(g.display_crs);requireValue(g.display_crs.includes("+proj=eqearth")&&g.display_crs.includes("+lon_0=-160"),"unreviewed projection");
  const bounds=array(g.bounds);requireValue(bounds.length===4,"bounds mismatch");bounds.forEach(finite); requireValue(Number(bounds[2])>Number(bounds[0])&&Number(bounds[3])>Number(bounds[1]),"invalid bounds");
  array(g.coastline).forEach(line=>{const points=array(line);requireValue(points.length>=2,"invalid coastline");points.forEach(point=>{const p=array(point);requireValue(p.length===2,"coordinate dimension");p.forEach(finite);});});
  const ids=[manifest.event.event_id,...manifest.stations.map(s=>s.station_id)];const points=array(g.points);requireValue(points.length===ids.length,"geometry point cohort mismatch");
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
  const windowIds=manifest.windows.map(w=>w.id);const support=array(s.support);requireValue(support.length===windowIds.length,"support window cohort mismatch");const supportWindows=new Set<string>();
  support.forEach(value=>{
    const p=object(value);const coastal=station.station_type==="coastal";keys(p,[...BASE_SUPPORT,...(coastal?[...COASTAL_COUNTS,...COASTAL_TIMES,"sample_density_percent"]:["cadence_seconds_counts"])]);
    requireValue(p.station_id===station.station_id,"support station mismatch");oneOf(p.window_id,windowIds);text(p.window_id);requireValue(!supportWindows.has(p.window_id),"duplicate support window");supportWindows.add(p.window_id);interval(p);
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
  for(const field of ["coverage_spans","gap_blocks"]){const spans=array(s[field]);if(station.station_type==="dart")requireValue(spans.length===0,"DART cannot have coastal grid spans");spans.forEach(value=>{const p=object(value);keys(p,[...SPAN_TEXT,...SPAN_COUNTS]);SPAN_TEXT.forEach(k=>text(p[k]));SPAN_COUNTS.forEach(k=>count(p[k]));requireValue(p.station_id===station.station_id,"span station mismatch");oneOf(p.window_id,windowIds);oneOf(p.status,["observed","source_blank","absent_timestamp"]);interval(p);});}
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
