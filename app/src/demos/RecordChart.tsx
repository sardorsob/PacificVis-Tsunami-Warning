import { useEffect, useMemo, useRef, useState } from "react";
import { formatUtc, formatValue, localYDomain, pointPath, selectWindow } from "./chart";
import type { ProductKey, StationMetadata, StationRecords } from "./types";
import { plotDateContext } from "./layout";

export type RecordChartProps={station:StationMetadata;records:StationRecords;windowId:string;productKey:ProductKey;role:"selected"|"pinned";cursorMs?:number;height?:number;compact?:boolean};
/** cursorMs marks the story clock: a time on the record, never an arrival. Points after it are dimmed, never removed. */
export function RecordChart({station,records,windowId,productKey,role,cursorMs,height=210,compact=false}:RecordChartProps) {
  const container=useRef<HTMLDivElement>(null);const [width,setWidth]=useState(360);
  useEffect(()=>{const element=container.current;if(!element)return;const observer=new ResizeObserver(entries=>{const w=entries[0]?.contentRect.width;if(w)setWidth(Math.max(240,Math.round(w)));});observer.observe(element);return()=>observer.disconnect();},[]);
  const selected=useMemo(()=>selectWindow(records,windowId),[records,windowId]);
  const domain=useMemo(()=>localYDomain(selected.rows,productKey),[selected,productKey]);
  const product=station.products.find(p=>p.key===productKey)!;
  const left=64,right=20,top=14,bottom=40;
  const start=Date.parse(selected.support.start_utc),end=Date.parse(selected.support.end_utc_exclusive);
  const x=(t:number)=>left+(t-start)/Math.max(1,end-start)*(width-left-right);
  const y=(v:number)=>domain?height-bottom-(v-domain[0])/(domain[1]-domain[0])*(height-top-bottom):0;
  const cursor=cursorMs!==undefined&&cursorMs>=start&&cursorMs<end?cursorMs:null;
  const [path,after]=useMemo(()=>{if(cursor===null)return [pointPath(selected.rows,productKey,x,y),""];const at=(r:{observed_at_utc:string})=>Date.parse(r.observed_at_utc)<=cursor;
    return [pointPath(selected.rows.filter(at),productKey,x,y),pointPath(selected.rows.filter(r=>!at(r)),productKey,x,y)];},[selected,productKey,width,domain,height,cursor]);
  const valid=selected.rows.filter(r=>r[productKey]!==null);const first=valid[0],last=valid.at(-1);
  const xTicks=width<480?[0,0.5,1]:[0,0.25,0.5,0.75,1];
  return <div className="record-chart" ref={container}>
    <h3>{product.label} <span>({product.units})</span></h3>
    <p className="chart-context">Datum: {station.vertical_reference} · UTC · station-local y-scale<span className="chart-date"> · {plotDateContext(selected.support.start_utc,selected.support.end_utc_exclusive)}</span></p>
    {domain&&product.available?<svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${station.name}: ${valid.length} actual ${product.label} measurements; independent station-local vertical scale. Points only; no interpolation.`}>
      {[0,0.5,1].map(f=>{const v=domain[0]+f*(domain[1]-domain[0]);return <g key={f}><line className="chart-grid" x1={left} x2={width-right} y1={y(v)} y2={y(v)}/><text x={left-8} y={y(v)+4} textAnchor="end">{formatValue(v)}</text></g>;})}
      {xTicks.map(f=>{const t=start+f*(end-start);const iso=new Date(t).toISOString();return <text key={f} x={x(t)} y={height-16} textAnchor={f===0?"start":f===1?"end":"middle"}>{end-start>86400000?iso.slice(5,10):iso.slice(11,16)}</text>;})}
      <path d={path} className={`record-points record-points--${role}`} fill="none" strokeWidth="2.6" strokeLinecap="round"/>
      {cursor!==null&&<><path d={after} className={`record-points record-points--${role} record-points--after`} fill="none" strokeWidth="2.6" strokeLinecap="round"/><line className="clock-cursor" x1={x(cursor)} x2={x(cursor)} y1={top} y2={height-bottom}/></>}
    </svg>:<div className="chart-empty" role="status">{!product.available?`${product.label} is not available in this station’s source.`:`No non-null ${product.label} values in this reviewed window.`} No other product substituted.</div>}
    {!compact&&<><p className="window-bounds">{windowId==="source_full"?"Station-specific full source · ":"Shared window · "}[{formatUtc(selected.support.start_utc)}, {formatUtc(selected.support.end_utc_exclusive)})</p>
    {first&&last&&<p className="value-context">First {formatValue(first[productKey]!)} at {formatUtc(first.observed_at_utc)}<br/>Last {formatValue(last[productKey]!)} at {formatUtc(last.observed_at_utc)} · {valid.length.toLocaleString("en-US")} values</p>}</>}
  </div>;
}
