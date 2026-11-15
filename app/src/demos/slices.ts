import { array, count, fetchHashed, fetchHashedBytes, finite, hash, keys, object, oneOf, requireValue, safeSourceUrl, text, utcMicros, validateRelease } from "./loader";
import { validateCoastline, type Coastline } from "./story/layers";
import type { Asset, DemoManifest, EventEntry, EventsIndex } from "./types";

// Records schema 2 (docs/data/demo-bundle.md, "Records schema 2 (display slices)"): one display window, one raw product per station,
// each station a gzip CSV. Tōhoku stays on schema 1 (loader.ts).
export const SLICE_PRODUCTS = ["one_minute_water_level","water_level","archive_window"] as const;
export const SLICE_COLUMNS = ["event_id","source_id","station_key","sensor","timestamp_utc","numeric_value","value_state","timestamp_state","duplicate_timestamp","units","vertical_datum","qc_state","qc_json"] as const;
const TIMESTAMP_STATES = ["reported_utc","epoch_calendar_agree","epoch_calendar_minute_agree","header_day_end_boundary"] as const;
const SAFE_ID = /^[a-zA-Z0-9_-]+$/;
/** A plain decimal with an optional exponent: no blank, "+", bare ".", NaN or Infinity text. */
const DECIMAL = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const HOUR = 3_600_000_000n; // microseconds, as utcMicros returns

export type SliceStation = {
  station_id: string; display_station_key: string; name: string; product: (typeof SLICE_PRODUCTS)[number]; latitude: number; longitude: number;
  units: "m"; vertical_datum: "STND" | "MLLW" | "unknown"; source: { source_id: string; sha256: string; url: string | null };
  coverage_fraction: number; longest_supported_minutes: number; coverage_rule_id: string; rows: number;
};
export type SliceManifest = Pick<DemoManifest,"bundle_id" | "event" | "release" | "input_fingerprints" | "config_sha256"> & {
  schema_version: "2"; exporter_version: "1"; evidence_state: "internal_descriptive_only";
  window: { id: "display"; label: string; start_utc: string; end_utc_exclusive: string }; default_station_id: string; stations: SliceStation[];
  assets: (Asset & { content_encoding: "identity" | "gzip" })[]; geometry_path: "geometry.json"; accounting: { station_count: number; rows: number };
};
/** One CSV row as published: numeric_value is null only for a blank row; qc_json is the parsed object. */
export type SliceRow = {
  event_id: string; source_id: string; station_key: string; sensor: string; timestamp_utc: string; numeric_value: number | null;
  value_state: "finite_numeric" | "blank"; timestamp_state: (typeof TIMESTAMP_STATES)[number]; duplicate_timestamp: boolean; units: string;
  vertical_datum: string; qc_state: "provided" | "not_provided"; qc_json: Record<string,unknown>;
};
/** t: UTC milliseconds; v: the raw value in the station's units and datum. */
export type SlicePoint = { t: number; v: number };
export type SliceRecords = {
  station_id: string; rows: SliceRow[]; segments: SlicePoint[][];
  counts: { rows: number; blank: number; duplicates_dropped: number; outside_window: number; backward_steps: number };
};

/** A schema-2 records manifest, checked against its index entry; the index pins its exact bytes. */
export function validateSliceManifest(input: unknown, entry: EventEntry): SliceManifest {
  requireValue(entry.records,"event has no records bundle");
  const m=object(input); keys(m,["schema_version","exporter_version","bundle_id","evidence_state","event","release","window","default_station_id","stations","assets","geometry_path","input_fingerprints","config_sha256","accounting"]);
  requireValue(m.schema_version==="2"&&m.exporter_version==="1"&&m.evidence_state==="internal_descriptive_only","unsupported schema or evidence release");
  requireValue(m.bundle_id===entry.records.bundle_id,"bundle identity mismatch");
  const event=object(m.event); keys(event,["event_id","origin_time_utc","latitude","longitude"]);
  requireValue(event.event_id===entry.event_id&&event.origin_time_utc===entry.origin_time_utc&&event.latitude===entry.latitude&&event.longitude===entry.longitude,"event identity mismatch");
  requireValue(validateRelease(m.release).release_id==="multi-event-descriptive-v1","release identity mismatch");
  const w=object(m.window); keys(w,["id","label","start_utc","end_utc_exclusive"]); text(w.start_utc); text(w.end_utc_exclusive);
  const origin=utcMicros(entry.origin_time_utc);
  requireValue(w.id==="display"&&w.label==="6 hours before to 30 hours after the origin"&&utcMicros(w.start_utc)===origin-6n*HOUR&&utcMicros(w.end_utc_exclusive)===origin+30n*HOUR,"display window mismatch");
  const stations=array(m.stations).map(object); requireValue(stations.length>0,"station cohort mismatch");
  stations.forEach((s,i)=>{
    keys(s,["station_id","display_station_key","name","product","latitude","longitude","units","vertical_datum","source","coverage_fraction","longest_supported_minutes","coverage_rule_id","rows"]);
    // Strictly ascending (unique) ASCII ids, so string order is code-point order.
    text(s.station_id); requireValue(SAFE_ID.test(s.station_id)&&(i===0||String(stations[i-1].station_id)<s.station_id),"station order or duplicate station");
    requireValue(s.display_station_key===`coops:${s.station_id}`,"display station key mismatch");
    text(s.name); oneOf(s.product,SLICE_PRODUCTS); finite(s.latitude); finite(s.longitude); requireValue(Math.abs(s.latitude)<=90&&Math.abs(s.longitude)<=180,"invalid coordinates");
    requireValue(s.units==="m","station units mismatch"); oneOf(s.vertical_datum,["STND","MLLW","unknown"]);
    const source=object(s.source); keys(source,["source_id","sha256","url"]); text(source.source_id); hash(source.sha256);
    requireValue(source.url===null||typeof source.url==="string"&&safeSourceUrl(source.url)!==null,"unsafe source URL");
    finite(s.coverage_fraction); finite(s.longest_supported_minutes); text(s.coverage_rule_id); count(s.rows);
    requireValue(s.coverage_fraction>=0&&s.coverage_fraction<=1&&s.longest_supported_minutes>=0,"invalid coverage");
  });
  const ids=stations.map(s=>s.station_id as string); requireValue(ids.includes(m.default_station_id as string),"default station not listed");
  // geometry.json, then one station file per station in path order (not id order: "-" sorts before ".").
  const paths=["geometry.json",...ids.map(id=>`stations/${id}.csv.gz`).sort()];
  const assets=array(m.assets).map(v=>{const a=object(v); keys(a,["path","sha256","bytes","content_encoding"]); text(a.path); hash(a.sha256); count(a.bytes); requireValue(a.bytes>0,"empty asset"); return a;});
  requireValue(assets.length===paths.length&&assets.every((a,i)=>a.path===paths[i]&&a.content_encoding===(i?"gzip":"identity")),"asset cohort mismatch");
  requireValue(m.geometry_path==="geometry.json","geometry path mismatch"); hash(m.config_sha256);
  array(m.input_fingerprints).forEach(v=>{const f=object(v);keys(f,["path","sha256"]);text(f.path);requireValue(!f.path.startsWith("/")&&!f.path.split("/").includes(".."),"unsafe fingerprint path");hash(f.sha256);});
  const accounting=object(m.accounting); keys(accounting,["station_count","rows"]); count(accounting.station_count); count(accounting.rows);
  requireValue(accounting.station_count===ids.length&&accounting.rows===stations.reduce((n,s)=>n+(s.rows as number),0),"accounting mismatch");
  return m as SliceManifest;
}

// One field and its delimiter: a quoted field ("" is one quote) or a bare one, then a comma, LF, CRLF or the end of the text.
const CSV_FIELD = /("(?:[^"]|"")*"|[^",\r\n]*)(,|\r?\n|$)/y;
/** RFC 4180 records (the final line break is optional); a stray quote or bare CR is refused. */
export function parseCsv(source: string): string[][] {
  const rows: string[][] = [], field = new RegExp(CSV_FIELD); let row: string[] = [];
  while (field.lastIndex<source.length) {
    const at=field.lastIndex, m=field.exec(source); requireValue(m,`malformed CSV at character ${at}`);
    row.push(m[1].startsWith('"')?m[1].slice(1,-1).replaceAll('""','"'):m[1]);
    if (m[2]!==",") { rows.push(row); row=[]; }
    else if (field.lastIndex===source.length) { row.push(""); rows.push(row); row=[]; }
  }
  return rows;
}

/** A station file's verified bytes: gzip, then UTF-8 CSV, every row checked, then drawn in file order. */
export async function decodeSliceStation(bytes: ArrayBuffer, station: SliceStation, manifest: SliceManifest): Promise<SliceRecords> {
  const magic=new Uint8Array(bytes,0,Math.min(2,bytes.byteLength)); requireValue(magic[0]===0x1f&&magic[1]===0x8b,"station file is not gzip");
  const plain=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
  const [header,...lines]=parseCsv(new TextDecoder("utf-8",{fatal:true}).decode(plain));
  requireValue(JSON.stringify(header)===JSON.stringify(SLICE_COLUMNS),"station file columns mismatch");
  requireValue(lines.length===station.rows,"station row count mismatch");
  const coops=station.product!=="archive_window", datums=station.vertical_datum==="unknown"?["unknown","Unknown"]:[station.vertical_datum];
  const start=utcMicros(manifest.window.start_utc), end=utcMicros(manifest.window.end_utc_exclusive);
  const counts={rows:lines.length,blank:0,duplicates_dropped:0,outside_window:0,backward_steps:0}, segments: SlicePoint[][]=[], seen=new Set<bigint>();
  let segment: SlicePoint[] | null=null, previous: bigint | null=null;
  const rows=lines.map(cells=>{
    requireValue(cells.length===SLICE_COLUMNS.length,"station row width mismatch");
    const [event_id,source_id,station_key,sensor,timestamp_utc,value,value_state,timestamp_state,duplicate,units,vertical_datum,qc_state,qc_text]=cells;
    requireValue(event_id===manifest.event.event_id,"row event identity mismatch");
    requireValue(source_id===station.source.source_id,"row source identity mismatch");
    // CO-OPS files name the station; archived NTWC day files carry the NTWC code instead.
    requireValue(coops?station_key===`coops-${station.station_id}`:/^ntwc-[a-z0-9]+$/.test(station_key),"row station key mismatch");
    requireValue(units===station.units&&datums.includes(vertical_datum),"row units or datum mismatch");
    text(sensor); const stamp=utcMicros(timestamp_utc);
    oneOf(value_state,["finite_numeric","blank"]); oneOf(timestamp_state,TIMESTAMP_STATES); oneOf(duplicate,["True","False"]); oneOf(qc_state,["provided","not_provided"]);
    const blank=value_state==="blank", numeric_value=blank?null:Number(value);
    requireValue(blank?value==="unknown":DECIMAL.test(value)&&Number.isFinite(numeric_value),"numeric value does not match its value state");
    let qc: unknown=null; try { qc=JSON.parse(qc_text) as unknown; } catch { /* refused by object() below */ }
    const qc_json=object(qc);
    // Drawing: a blank ends the line; a repeated timestamp flagged True is drawn only the first time; outside the window is not drawn;
    // a backward step starts a new line. Never sorted, interpolated or filled; QC never filters.
    const repeat=duplicate==="True"&&seen.has(stamp); seen.add(stamp);
    if (blank) { counts.blank++; segment=null; }
    else if (repeat) counts.duplicates_dropped++;
    else if (stamp<start||stamp>=end) counts.outside_window++;
    else {
      if (previous!==null&&stamp<previous) { counts.backward_steps++; segment=null; }
      if (!segment) segments.push(segment=[]);
      segment.push({t:Number(stamp)/1000,v:numeric_value!}); previous=stamp;
    }
    return {event_id,source_id,station_key,sensor,timestamp_utc,numeric_value,value_state,timestamp_state,duplicate_timestamp:duplicate==="True",units,vertical_datum,qc_state,qc_json} as SliceRow;
  });
  return {station_id:station.station_id,rows,segments,counts};
}

/** The entry's schema-2 records manifest, verified against the index pin before parsing. */
export async function loadSliceManifest(entry: EventEntry, signal?: AbortSignal, request: typeof fetch = fetch): Promise<SliceManifest> {
  if(!entry.records)throw new Error("No station records are published for this event.");
  const ref=entry.records;return validateSliceManifest(await fetchHashed(`/data/${ref.bundle_id}/manifest.json`,ref.manifest_bytes,ref.manifest_sha256,signal,request),entry);
}
/** One station file, pinned by its manifest asset (the stored gzip bytes), then decoded. */
export async function loadSliceStation(manifest: SliceManifest, stationId: string, signal?: AbortSignal, request: typeof fetch = fetch): Promise<SliceRecords> {
  const path=`stations/${stationId}.csv.gz`, station=manifest.stations.find(s=>s.station_id===stationId), asset=manifest.assets.find(a=>a.path===path);
  requireValue(station&&asset,"station not in manifest");
  return decodeSliceStation(await fetchHashedBytes(`/data/${manifest.bundle_id}/${path}`,asset.bytes,asset.sha256,signal,request),station,manifest);
}
/** The index's shared basemap (index schema 2), in the layers coastline format with the Natural Earth 1:110m source id. */
export async function loadBasemap(index: EventsIndex, signal?: AbortSignal, request: typeof fetch = fetch): Promise<Coastline> {
  const ref=index.basemap; requireValue(ref,"events index has no basemap");
  const c=object(await fetchHashed(`/data/${ref.path}`,ref.bytes,ref.sha256,signal,request));
  // No manifest counts the basemap's parts, so its own count is the cohort; closed[] must still match it.
  return validateCoastline(c,{coastline_source_id:"natural-earth-110m-coastline",accounting:{coastline_parts:array(c.parts).length}});
}
