import { array, count, fetchHashed, finite, hash, keys, object, oneOf, requireValue, text, utcMicros } from "../loader";
import type { EventEntry } from "../types";
import { T_MAX } from "./clock";
import { toSvg, type Pt } from "./layers";

/** docs/data/story-arrivals.md, "Release": the display permission, compared field by field (arrays in this order). */
export const RELEASE = {
  allowed_uses: ["display_source_reported_times", "display_published_estimates", "display_plain_differences"],
  arrival_comparison_allowed: false, estimate_difference_display_allowed: true, physical_arrival_records_released: 0,
  prohibited_uses: ["physical_arrival_validation", "modeled_minus_observed_residual", "model_output_display", "actionable_warning_time", "operational_warning",
    "public_release_before_release_gate", "selection_or_reserved_event_display", "fitted_or_predicted_value_display", "paper_figure_or_model_code_use",
    "cross_source_difference"],
  release_id: "story-reported-times-v1", reported_arrival_display_allowed: true,
} as const;
const CRS = "+proj=eqearth +lon_0=-160 +datum=WGS84 +units=m +no_defs +type=crs";
const RULER = { speed_km_per_h: 713, statement: "Constant long-wave speed over a 4 km deep ocean. A ruler, not a prediction." } as const;
const INPUTS = [...["manifest.json","source_records.csv.gz","observations.csv.gz","forecast_instances.csv.gz","pair_members.csv.gz","sites.csv.gz","site_links.csv.gz"]
  .map(f=>`data/processed/arrival-evidence/foundation-v1/${f}`),"artifacts/releases/story-reported-times-v1.json"];
const TOP = ["schema_version","exporter_version","evidence_state","event_id","origin_time_utc","release","display_crs","coordinate_order","ruler","places","reports","accounting","input_fingerprints","config_sha256"];
const PLACE = ["site_id","label","position_status","latitude","longitude","x","y","distance_km","ruler_minutes","record"];
const REPORT = ["report_id","source","site_id","place_text","gauge_kind","reported_minutes","reported_origin","reported_utc","reported_text","origin_offset_seconds","estimate_minutes","estimate_utc","estimate_text","reported_minus_estimate_minutes","reported_minus_ruler_minutes","source_flags","source_id","source_sha256"];
const NUMBERS = ["reported_minutes","origin_offset_seconds","estimate_minutes","reported_minus_estimate_minutes","reported_minus_ruler_minutes"];
const ACCOUNTING = ["ntwc_table_rows","ntwc_rows_with_reported_time","ntwc_rows_with_estimate","ntwc_rows_with_both_times","ntwc_pairs_with_position","ntwc_reported_with_position","ncei_records","ncei_reported_durations","ncei_durations_with_position","reports","places"] as const;

export type Place = { site_id: string; label: string; position_status: "reviewed" | "source_position"; latitude: number; longitude: number; x: number; y: number;
  distance_km: number; ruler_minutes: number; record: { station_id: string; link: "same_provider_id" | "within_1km" } | null };
export type Report = {
  report_id: string; source: "ntwc" | "ncei"; site_id: string | null; place_text: string; gauge_kind: "unknown" | "tide_gauge" | "deep_ocean_gauge";
  reported_minutes: number | null; reported_origin: "usgs_reviewed" | "ncei_native" | null; reported_utc: string | null; reported_text: string | null;
  origin_offset_seconds: number | null; estimate_minutes: number | null; estimate_utc: string | null; estimate_text: string | null;
  reported_minus_estimate_minutes: number | null; reported_minus_ruler_minutes: number | null; source_flags: string[]; source_id: string; source_sha256: string;
};
export type Accounting = Record<(typeof ACCOUNTING)[number], number>;
export type StoryArrivals = {
  schema_version: "1"; exporter_version: "1"; evidence_state: "internal_descriptive_only"; event_id: string; origin_time_utc: string; release: typeof RELEASE;
  display_crs: string; coordinate_order: "x,y"; ruler: typeof RULER; places: Place[]; reports: Report[]; accounting: Accounting;
  input_fingerprints: { path: string; sha256: string }[]; config_sha256: string;
};

/** Strictly before in code-point order (the exporter's sort); JS `<` compares UTF-16 units, which differs above U+FFFF. */
function before(a: string, b: string): boolean {
  const x=[...a],y=[...b];for(let i=0;i<x.length&&i<y.length;i++)if(x[i]!==y[i])return x[i].codePointAt(0)!<y[i].codePointAt(0)!;return x.length<y.length;
}
/** A reported-times file is checked against its index entry and every rule of the contract its own value can show; the index pins its bytes. */
export function validateArrivals(input: unknown, entry: EventEntry): StoryArrivals {
  const x=object(input);keys(x,TOP);
  requireValue(x.schema_version==="1"&&x.exporter_version==="1"&&x.evidence_state==="internal_descriptive_only"&&x.coordinate_order==="x,y"&&x.display_crs===CRS,"unsupported reported-times schema or projection");
  requireValue(x.event_id===entry.event_id&&x.origin_time_utc===entry.origin_time_utc,"reported-times event identity mismatch");
  const release=object(x.release);keys(release,Object.keys(RELEASE));
  requireValue(Object.entries(RELEASE).every(([k,v])=>JSON.stringify(release[k])===JSON.stringify(v)),"reported-times release mismatch");
  const ruler=object(x.ruler);keys(ruler,Object.keys(RULER));requireValue(ruler.speed_km_per_h===RULER.speed_km_per_h&&ruler.statement===RULER.statement,"reported-times ruler mismatch");
  hash(x.config_sha256);
  // Only the allowlisted inputs, sorted by path; the records manifest may sit under another bundles root, so only its tail is fixed.
  const records=entry.records?`/${entry.records.bundle_id}/manifest.json`:null;
  array(x.input_fingerprints).forEach((v,i,all)=>{const f=object(v);keys(f,["path","sha256"]);text(f.path);hash(f.sha256);
    requireValue(INPUTS.includes(f.path)||!!records&&f.path.endsWith(records)&&!f.path.startsWith("/")&&!f.path.split("/").includes(".."),"unlisted reported-times input");
    requireValue(i===0||before(String(object(all[i-1]).path),f.path),"input fingerprints out of order");});
  const places=array(x.places).map((v,i,all)=>{const p=object(v);keys(p,PLACE);text(p.site_id);text(p.label);oneOf(p.position_status,["reviewed","source_position"]);
    requireValue(i===0||before(String(object(all[i-1]).site_id),p.site_id),"places out of order or duplicate");
    finite(p.latitude);finite(p.longitude);requireValue(Math.abs(p.latitude)<=90&&Math.abs(p.longitude)<=180,"invalid coordinates");
    finite(p.x);finite(p.y);requireValue(Number.isInteger(p.x)&&Number.isInteger(p.y),"coordinate must be whole metres");
    finite(p.distance_km);finite(p.ruler_minutes);requireValue(p.distance_km>=0&&p.ruler_minutes>=0,"invalid place distance");
    if(p.record!==null){const r=object(p.record);keys(r,["station_id","link"]);text(r.station_id);oneOf(r.link,["same_provider_id","within_1km"]);requireValue(entry.records!==null,"place record link without a records bundle");}
    return p as Place;});
  const sites=new Set(places.map(p=>p.site_id)),ids=new Set<string>();let ncei=false;
  const reports=array(x.reports).map(v=>{const r=object(v);keys(r,REPORT);text(r.report_id);requireValue(!ids.has(r.report_id),"duplicate report");ids.add(r.report_id);
    oneOf(r.source,["ntwc","ncei"]);requireValue(r.site_id===null||typeof r.site_id==="string"&&sites.has(r.site_id),"report names an unlisted place");
    text(r.place_text);text(r.source_id);hash(r.source_sha256);const flags=array(r.source_flags);flags.forEach(text);
    for(const k of NUMBERS)if(r[k]!==null)finite(r[k]);for(const k of ["reported_utc","estimate_utc"])if(r[k]!==null){text(r[k]);utcMicros(r[k] as string);}
    for(const k of ["reported_text","estimate_text"])if(r[k]!==null)text(r[k]);
    const rep=r.reported_minutes as number|null,est=r.estimate_minutes as number|null;
    requireValue((r.reported_origin===null)===(rep===null),"reported origin null rule mismatch");
    requireValue((r.reported_minus_ruler_minutes===null)===(r.site_id===null||rep===null||rep<0),"reported-minus-ruler null rule mismatch");
    requireValue(r.reported_minus_estimate_minutes===null||!(rep!==null&&rep<0||est!==null&&est<0),"difference for a time before the origin");
    // NTWC rows first (each with an exact reported time or estimate), then NCEI records (each with a positive duration); never an NCEI estimate or difference.
    if(r.source==="ntwc"){requireValue(!ncei,"NTWC reports must precede NCEI reports");
      requireValue(r.gauge_kind==="unknown"&&(rep===null||r.reported_origin==="usgs_reviewed")&&(r.reported_utc===null)===(rep===null)&&r.origin_offset_seconds===null
        &&(r.estimate_utc===null)===(est===null)&&(rep!==null||est!==null)&&flags.length===0,"NTWC report field rules mismatch");}
    else{ncei=true;requireValue((r.gauge_kind==="tide_gauge"||r.gauge_kind==="deep_ocean_gauge")&&rep!==null&&rep>0&&r.reported_origin==="ncei_native"&&r.reported_utc===null
        &&r.reported_text===null&&est===null&&r.estimate_utc===null&&r.estimate_text===null&&r.reported_minus_estimate_minutes===null
        &&(flags.length===0||flags.length===1&&flags[0]==="doubtful"),"NCEI report field rules mismatch");}
    return r as Report;});
  // Every place is used; its label is its first report's place text; a place any NTWC report uses is reviewed.
  for(const p of places){const at=reports.filter(r=>r.site_id===p.site_id);
    requireValue(at.length>0&&p.label===at[0].place_text&&p.position_status===(at.some(r=>r.source==="ntwc")?"reviewed":"source_position"),"place does not match its reports");}
  const acc=object(x.accounting);keys(acc,ACCOUNTING);Object.values(acc).forEach(count);const a=acc as Accounting;
  const n=(f:(r:Report)=>boolean)=>reports.filter(f).length,ntwc=(r:Report)=>r.source==="ntwc",nc=n(r=>!ntwc(r)),paired=(r:Report)=>r.reported_minus_estimate_minutes!==null;
  // Counts the lists show exactly; the rest (rows not listed, pairs) only bound what is listed.
  requireValue(a.reports===reports.length&&a.places===places.length&&a.ntwc_rows_with_reported_time===n(r=>ntwc(r)&&r.reported_minutes!==null)
    &&a.ntwc_rows_with_estimate===n(r=>ntwc(r)&&r.estimate_minutes!==null)&&a.ntwc_reported_with_position===n(r=>ntwc(r)&&r.reported_minutes!==null&&r.site_id!==null)
    &&a.ncei_reported_durations===nc&&a.ncei_durations_with_position===n(r=>!ntwc(r)&&r.site_id!==null)&&a.ntwc_table_rows>=n(ntwc)&&a.ncei_records>=nc
    &&a.ntwc_rows_with_both_times>=n(paired)&&a.ntwc_pairs_with_position<=a.ntwc_rows_with_both_times&&a.ntwc_pairs_with_position>=n(r=>paired(r)&&r.site_id!==null),
  "reported-times accounting mismatch");
  return x as StoryArrivals;
}
/** The entry's reported-times file, verified against the index pin before parsing; an event without one fetches nothing. */
export async function loadArrivals(entry: EventEntry, signal?: AbortSignal, request: typeof fetch = fetch): Promise<StoryArrivals | null> {
  const a=entry.arrivals;return a?validateArrivals(await fetchHashed(`/data/${a.path}`,a.bytes,a.sha256,signal,request),entry):null;
}

export type MarkKind = "estimate" | "ntwc" | "tide" | "deep";
/** One drawn mark: its place (SVG space), the minutes that light it, and its report's slot among the reports drawn at that place. */
export type ArrivalMark = { key: string; kind: MarkKind; xy: Pt; minutes: number; slot: number; of: number };
/** What the map and the column show: the drawn marks, the accounting, and listed reports not drawn (no place, before the origin, after 30 h). */
export type ArrivalDisplay = { marks: ArrivalMark[]; accounting: Accounting; unplaced: number; beforeOrigin: number; afterClock: number };
const CLOCK_END = T_MAX * 60;
/** "Listed but not drawn": only a listed place and 0 ≤ minutes < 30 h, and only under both display permissions. */
export function arrivalDisplay(a: StoryArrivals): ArrivalDisplay {
  const allowed=a.release.reported_arrival_display_allowed===true&&a.release.estimate_difference_display_allowed===true;
  const xy=new Map(a.places.map(p=>[p.site_id,toSvg([p.x,p.y])])),at=new Map<string,Omit<ArrivalMark,"slot"|"of">[][]>();let unplaced=0,beforeOrigin=0,afterClock=0;
  for(const r of a.reports){
    if(r.site_id===null){unplaced++;continue;}
    const times=[r.estimate_minutes,r.reported_minutes].filter(m=>m!==null);if(times.some(m=>m<0))beforeOrigin++;if(times.some(m=>m>=CLOCK_END))afterClock++;
    const dot:MarkKind=r.source==="ntwc"?"ntwc":r.gauge_kind==="deep_ocean_gauge"?"deep":"tide",site=r.site_id;
    const own=([["estimate",r.estimate_minutes],[dot,r.reported_minutes]] as [MarkKind,number|null][]).filter(([,m])=>m!==null&&m>=0&&m<CLOCK_END)
      .map(([kind,m])=>({key:`${r.report_id}:${kind}`,kind,xy:xy.get(site)!,minutes:m!}));
    if(allowed&&own.length)at.set(site,[...(at.get(site)??[]),own]);
  }
  const marks=[...at.values()].flatMap(group=>group.flatMap((own,slot)=>own.map(m=>({...m,slot,of:group.length}))));
  return {marks,accounting:a.accounting,unplaced,beforeOrigin,afterClock};
}
