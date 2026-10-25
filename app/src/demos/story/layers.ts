import { array, count, fetchHashed, finite, hash, keys, object, requireValue, text } from "../loader";

const LAYERS_BUNDLE_ID = "tohoku-story-layers-v1";
const LAYERS_MANIFEST_URL = `/data/${LAYERS_BUNDLE_ID}/manifest.json`;
/** Display CRS (y up) to SVG space (y down). */
export const toSvg = ([x, y]: readonly number[]): Pt => [x, -y];
export type Pt = [number, number];
type LayersAsset = { path: "contours.json" | "coastline.json"; bytes: number; sha256: string };
type LayersManifest = {
  schema_version: "1"; exporter_version: "1"; bundle_id: typeof LAYERS_BUNDLE_ID; evidence_state: "internal_descriptive_only";
  display_crs: string; central_meridian: -160; coordinate_order: "x,y"; units: string; statement: string;
  contour_source_id: string; coastline_source_id: string; origin_time_utc: string; hours_semantics: string;
  assets: LayersAsset[]; input_fingerprints: { path: string; sha256: string }[]; config_sha256: string;
  accounting: { contour_features: number; contour_parts: number; contour_vertices: number; hours: number[]; coastline_parts: number };
};
export type ContourFeature = { hours: number; index: boolean; parts: Pt[][] };
export type Coastline = { parts: Pt[][]; closed: boolean[] };
export type StoryLayers = { manifest: LayersManifest; contours: ContourFeature[]; coastline: Coastline };

const MANIFEST_KEYS = ["schema_version","exporter_version","bundle_id","evidence_state","display_crs","central_meridian","coordinate_order","units","statement","contour_source_id","coastline_source_id","origin_time_utc","hours_semantics","assets","input_fingerprints","config_sha256","accounting"];
export function validateLayersManifest(input: unknown): LayersManifest {
  const m=object(input);keys(m,MANIFEST_KEYS);
  requireValue(m.schema_version==="1"&&m.exporter_version==="1"&&m.bundle_id===LAYERS_BUNDLE_ID&&m.evidence_state==="internal_descriptive_only","layers bundle identity mismatch");
  text(m.display_crs);requireValue(m.display_crs.includes("+proj=eqearth")&&m.display_crs.includes("+lon_0=-160")&&m.central_meridian===-160&&m.coordinate_order==="x,y","unreviewed layers projection");
  for(const key of ["units","statement","hours_semantics"])text(m[key]);
  requireValue(m.contour_source_id==="ncei-ttt-tohoku-layer17-geojson"&&m.coastline_source_id==="natural-earth-50m-coastline"&&m.origin_time_utc==="2011-03-11T05:46:24.120Z","layers source identity mismatch");
  const assets=array(m.assets);requireValue(assets.length===2,"layers asset cohort mismatch");
  const paths=assets.map(v=>{const a=object(v);keys(a,["path","sha256","bytes"]);text(a.path);hash(a.sha256);count(a.bytes);requireValue(a.bytes>0,"empty layer asset");return a.path;});
  requireValue(JSON.stringify([...paths].sort())===JSON.stringify(["coastline.json","contours.json"]),"layers asset cohort mismatch");
  array(m.input_fingerprints).forEach(v=>{const f=object(v);keys(f,["path","sha256"]);text(f.path);hash(f.sha256);});hash(m.config_sha256);
  const acc=object(m.accounting);keys(acc,["contour_features","contour_parts","contour_vertices","hours","coastline_parts"]);
  for(const key of ["contour_features","contour_parts","contour_vertices","coastline_parts"])count(acc[key]);
  const hours=array(acc.hours);hours.forEach(count);requireValue(hours.every((h,i)=>i===0||Number(h)>Number(hours[i-1])),"layers hours not strictly increasing");
  return m as LayersManifest;
}
function points(value: unknown, partsSeen: { parts: number; vertices: number }): Pt[][] {
  return array(value).map(part=>{const pts=array(part);requireValue(pts.length>=2,"layer line needs two points");partsSeen.parts++;partsSeen.vertices+=pts.length;
    return pts.map(point=>{const p=array(point);requireValue(p.length===2,"coordinate dimension");p.forEach(finite);requireValue(Number.isInteger(p[0])&&Number.isInteger(p[1]),"coordinate must be whole metres");
      return [p[0] as number,-(p[1] as number)] as Pt;});});
}
export function validateContours(input: unknown, manifest: LayersManifest): ContourFeature[] {
  const c=object(input);keys(c,["schema_version","source_id","features"]);requireValue(c.schema_version==="1"&&c.source_id===manifest.contour_source_id,"contour identity mismatch");
  const seen={parts:0,vertices:0};
  const features=array(c.features).map(v=>{const f=object(v);keys(f,["hours","index","parts"]);count(f.hours);requireValue(f.hours>=1&&typeof f.index==="boolean","contour hour or index invalid");
    return {hours:f.hours,index:f.index as boolean,parts:points(f.parts,seen)};});
  const acc=manifest.accounting;
  requireValue(features.length===acc.contour_features&&JSON.stringify([...new Set(features.map(f=>f.hours))])===JSON.stringify(acc.hours),"contour cohort mismatch");
  requireValue(seen.parts===acc.contour_parts&&seen.vertices===acc.contour_vertices,"contour cohort mismatch");
  return features;
}
export function validateCoastline(input: unknown, manifest: LayersManifest): Coastline {
  const c=object(input);keys(c,["schema_version","source_id","parts","closed"]);requireValue(c.schema_version==="1"&&c.source_id===manifest.coastline_source_id,"coastline identity mismatch");
  const parts=points(c.parts,{parts:0,vertices:0});const closed=array(c.closed);
  requireValue(parts.length===manifest.accounting.coastline_parts&&closed.length===parts.length&&closed.every(v=>typeof v==="boolean"),"coastline cohort mismatch");
  return {parts,closed:closed as boolean[]};
}
export async function loadLayers(signal?: AbortSignal): Promise<StoryLayers> {
  const response=await fetch(LAYERS_MANIFEST_URL,{signal,credentials:"omit",redirect:"error"});requireValue(response.ok,`layers manifest HTTP ${response.status}`);
  const manifest=validateLayersManifest(await response.json());
  const get=(path:LayersAsset["path"])=>{const a=manifest.assets.find(x=>x.path===path)!;return fetchHashed(`/data/${LAYERS_BUNDLE_ID}/${path}`,a.bytes,a.sha256,signal);};
  const [contours,coastline]=await Promise.all([get("contours.json"),get("coastline.json")]);
  return {manifest,contours:validateContours(contours,manifest),coastline:validateCoastline(coastline,manifest)};
}
export const linePath=(parts: Pt[][], close=false)=>parts.map(part=>`M${part.map(p=>`${p[0]} ${p[1]}`).join("L")}${close?"Z":""}`).join("");
export function hourPaths(contours: ContourFeature[]): Map<number,string> {
  const out=new Map<number,string>();for(const f of contours)out.set(f.hours,(out.get(f.hours)??"")+linePath(f.parts));return out;
}
/** Label anchors for index hours: the vertex nearest a south-east ray from the epicentre (SVG space). */
export function labelAnchors(contours: ContourFeature[], epicentre: Pt, maxOffset = 400_000): Map<number,Pt> {
  const n=Math.hypot(1,0.62),dir:Pt=[1/n,0.62/n],out=new Map<number,Pt>(),best=new Map<number,number>();
  for(const f of contours){if(!f.index)continue;for(const part of f.parts)for(const p of part){const dx=p[0]-epicentre[0],dy=p[1]-epicentre[1];if(dx*dir[0]+dy*dir[1]<=0)continue;
    const off=Math.abs(dx*dir[1]-dy*dir[0]);if(off<(best.get(f.hours)??maxOffset)){best.set(f.hours,off);out.set(f.hours,p);}}}
  return out;
}
/** A point midway between two published hours near the given anchor: used only to aim the lens, never as a value. */
export function pointBetween(contours: ContourFeature[], anchor: Pt, laterHour: number): Pt | null {
  let best:Pt|null=null,d=Infinity;
  for(const f of contours)if(f.hours===laterHour)for(const part of f.parts)for(const p of part){const q=(p[0]-anchor[0])**2+(p[1]-anchor[1])**2;if(q<d){d=q;best=p;}}
  return best?[(anchor[0]+best[0])/2,(anchor[1]+best[1])/2]:null;
}
/** The nearest published hour and its nearer neighbour at an SVG-space point; null beyond maxDistance. Never interpolates a time. */
// ponytail: brute force over every vertex (63k, well under a frame); a spatial index if the layers grow.
export function nearestHours(contours: ContourFeature[], x: number, y: number, maxDistance: number): { a: number; b: number } | null {
  const best=new Map<number,number>();
  for(const f of contours){let d=best.get(f.hours)??Infinity;for(const part of f.parts)for(const p of part){const q=(p[0]-x)**2+(p[1]-y)**2;if(q<d)d=q;}best.set(f.hours,d);}
  let hour=-1,min=Infinity;for(const [h,d] of best)if(d<min){min=d;hour=h;}
  if(hour<0||Math.sqrt(min)>maxDistance)return null;
  const neighbours=[hour-1,hour+1].filter(h=>best.has(h)).sort((p,q)=>best.get(p)!-best.get(q)!);
  const other=neighbours[0]??hour;return {a:Math.min(hour,other),b:Math.max(hour,other)};
}
