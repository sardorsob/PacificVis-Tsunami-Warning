import type { Observation, ProductKey, StationRecords } from "./types";
import { utcMicros } from "./loader";

export function selectWindow(records: StationRecords, windowId: string) {
  const support=records.support.find(s=>s.window_id===windowId);
  if(!support)throw new Error(`Reviewed window ${windowId} is unavailable for ${records.station_id}.`);
  const start=utcMicros(support.start_utc),end=utcMicros(support.end_utc_exclusive);
  return {support,rows:windowId==="source_full"?records.rows:records.rows.filter(r=>{const t=utcMicros(r.observed_at_utc);return t>=start&&t<end;}),coverageSpans:records.coverage_spans.filter(s=>s.window_id===windowId),gapBlocks:records.gap_blocks.filter(s=>s.window_id===windowId)};
}
type Values=readonly Partial<Pick<Observation,ProductKey>>[];
export function localYDomain(rows: Values,productKey: ProductKey): [number,number] | null {
  let min=Infinity,max=-Infinity;
  for(const row of rows){const v=row[productKey];if(typeof v==="number"&&Number.isFinite(v)){min=Math.min(min,v);max=Math.max(max,v);}}
  if(!Number.isFinite(min))return null;
  const pad=max>min?(max-min)*0.05:Math.max(Math.abs(min)*0.00001,0.001);
  return [min-pad,max+pad];
}
export function pointPath(rows: readonly (Partial<Pick<Observation,ProductKey>> & Pick<Observation,"observed_at_utc">)[],productKey:ProductKey,x:(time:number)=>number,y:(value:number)=>number): string {
  let path="";for(const row of rows){const v=row[productKey];if(typeof v==="number"&&Number.isFinite(v))path+=`M${+x(Date.parse(row.observed_at_utc)).toFixed(2)},${+y(v).toFixed(2)}h0.01`;}
  return path;
}
export function formatValue(value:number): string {return new Intl.NumberFormat("en-US",{maximumFractionDigits:5}).format(value);}
export function formatUtc(value:string): string {return value.replace("T"," ").replace(/(?:\.0+)?Z$/," UTC");}
