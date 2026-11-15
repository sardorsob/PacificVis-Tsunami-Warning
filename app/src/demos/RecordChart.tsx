import { useEffect, useMemo, useRef, useState } from "react";
import { formatUtc, formatValue, localYDomain, pointPath, selectWindow } from "./chart";
import type { ProductKey, StationMetadata, StationRecords } from "./types";
import { plotDateContext } from "./layout";
import { SLICE_PRODUCT_LABEL, type SlicePoint, type SliceRecords, type SliceStation } from "./slices";

/** The chart's width, kept in step with its container. */
function useWidth() {
  const container=useRef<HTMLDivElement>(null);const [width,setWidth]=useState(360);
  useEffect(()=>{const element=container.current;if(!element)return;const observer=new ResizeObserver(entries=>{const w=entries[0]?.contentRect.width;if(w)setWidth(Math.max(240,Math.round(w)));});observer.observe(element);return()=>observer.disconnect();},[]);
  return [container,width] as const;
}

export type RecordChartProps={station:StationMetadata;records:StationRecords;windowId:string;productKey:ProductKey;role:"selected"|"pinned";cursorMs?:number;height?:number;compact?:boolean};
/** cursorMs marks the story clock: a time on the record, never an arrival. Points after it are dimmed, never removed. */
export function RecordChart({station,records,windowId,productKey,role,cursorMs,height=210,compact=false}:RecordChartProps) {
  const [container,width]=useWidth();
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

export type SliceChartProps={station:SliceStation;records:SliceRecords;role:"selected"|"pinned";cursorMs?:number;height?:number;compact?:boolean};
/** A records-schema-2 record on its display window: each segment one line, in file order. Lines never join across a segment boundary (a blank
 * row or a backward time step, slices.ts); nothing is sorted, filled or interpolated. cursorMs is the story clock: the line after it is dimmed. */
export function SliceChart({station,records,role,cursorMs,height=210,compact=false}:SliceChartProps) {
  const [container,width]=useWidth();const {segments,window:w}=records,label=SLICE_PRODUCT_LABEL[station.product];
  const domain=useMemo(()=>localYDomain(segments.flat().map(p=>({raw_value:p.v})),"raw_value"),[segments]);
  const left=64,right=20,top=14,bottom=40,start=Date.parse(w.start_utc),end=Date.parse(w.end_utc_exclusive);
  const x=(t:number)=>left+(t-start)/Math.max(1,end-start)*(width-left-right);
  const y=(v:number)=>domain?height-bottom-(v-domain[0])/(domain[1]-domain[0])*(height-top-bottom):0;
  const cursor=cursorMs!==undefined&&cursorMs>=start&&cursorMs<end?cursorMs:null;
  const [path,after]=useMemo(()=>{
    const line=(s:SlicePoint[])=>s.map((p,i)=>`${i?"L":"M"}${+x(p.t).toFixed(2)},${+y(p.v).toFixed(2)}`).join("")+(s.length===1?"h0.01":"");
    if(cursor===null)return [segments.map(line).join(""),""];
    // Inside a segment time never steps back (a backward step starts the next one), so the part up to the clock is a prefix; the dimmed
    // part starts at its last point, so the line stays whole.
    const parts=segments.map(s=>{const i=s.findIndex(p=>p.t>cursor);return i<0?[s,[]]:[s.slice(0,i),s.slice(Math.max(0,i-1))];});
    return [parts.map(([a])=>line(a)).join(""),parts.map(([,b])=>line(b)).join("")];},[segments,width,domain,height,cursor]);
  const n=segments.reduce((sum,s)=>sum+s.length,0);
  return <div className="record-chart" ref={container}>
    <h3>{label} <span>({station.units})</span></h3>
    <p className="chart-context">Datum: {station.vertical_datum} · UTC · station-local y-scale<span className="chart-date"> · {plotDateContext(w.start_utc,w.end_utc_exclusive)}</span></p>
    {records.rows.length===0?<div className="chart-empty" role="status">This record has no rows in the display window.</div>
      :domain?<svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${station.name}: ${n} ${label} values in ${segments.length} line${segments.length===1?"":"s"}; a line breaks at every blank row and backward time step; independent station-local vertical scale. No interpolation.`}>
        {[0,0.5,1].map(f=>{const v=domain[0]+f*(domain[1]-domain[0]);return <g key={f}><line className="chart-grid" x1={left} x2={width-right} y1={y(v)} y2={y(v)}/><text x={left-8} y={y(v)+4} textAnchor="end">{formatValue(v)}</text></g>;})}
        {(width<480?[0,0.5,1]:[0,0.25,0.5,0.75,1]).map(f=>{const t=start+f*(end-start);return <text key={f} x={x(t)} y={height-16} textAnchor={f===0?"start":f===1?"end":"middle"}>{new Date(t).toISOString().slice(11,16)}</text>;})}
        <path d={path} className={`record-points record-points--${role}`} fill="none" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
        {cursor!==null&&<><path d={after} className={`record-points record-points--${role} record-points--after`} fill="none" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/><line className="clock-cursor" x1={x(cursor)} x2={x(cursor)} y1={top} y2={height-bottom}/></>}
      </svg>:<div className="chart-empty" role="status">No row of this record has a value in the display window; blank rows are gaps.</div>}
    {!compact&&<p className="window-bounds">{w.label} · [{formatUtc(w.start_utc)}, {formatUtc(w.end_utc_exclusive)})</p>}
  </div>;
}
