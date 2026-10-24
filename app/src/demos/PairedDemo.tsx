import { RecordChart } from "./RecordChart";
import { StationMap } from "./StationMap";
import { SupportView } from "./SupportView";
import { safeSourceUrl } from "./loader";
import { useEffect,useState } from "react";
import { isShortLandscape } from "./layout";
import type { ProductKey,RadialProps,StationSelection } from "./types";

export type StationCardProps={selection:StationSelection;role:"selected"|"pinned";windowId:string;productKey:ProductKey;onOpenEvidence:(stationId:string)=>void;onRetryStation:(stationId:string)=>void};
export function StationCard({selection,role,windowId,productKey,onOpenEvidence,onRetryStation}:StationCardProps) {
  const {station,records,status,error}=selection;const url=safeSourceUrl(station.source.url);
  return <article className={`station-card station-card--${role}`} aria-label={`${role==="selected"?"Selected":"Pinned reference"}: ${station.name}`}>
    <header><span className="role-badge">{role==="selected"?"○ Selected":"◇ Pinned reference"}</span><h2>{station.name} <span>{station.station_id}</span></h2><p>{station.station_type==="dart"?"DART water column":"Coastal water level"}</p></header>
    {status==="ready"&&records?<><RecordChart station={station} records={records} windowId={windowId} productKey={productKey} role={role}/><SupportView station={station} records={records} windowId={windowId} productKey={productKey}/></>:status==="error"?<div className="data-error" role="alert"><p>{station.name}: {error}</p><button type="button" onClick={()=>onRetryStation(station.station_id)}>Retry {station.name}</button></div>:<p className="loading-record" role="status">Loading and verifying {station.name} records…</p>}
    <footer className="source-strip"><p>Source: {station.source.publisher} · {station.source.title}</p><p>Source time basis: {station.time_basis}; verified observations plotted in UTC. Vertical datum: {station.vertical_reference}; horizontal datum: {station.horizontal_datum}. Source QC retained; empty flags do not certify QC pass.</p><div>{url?<a href={url} target="_blank" rel="noopener noreferrer">Publisher record ↗</a>:<span>Source link unavailable; provenance retained.</span>}<button type="button" disabled={status!=="ready"} onClick={()=>onOpenEvidence(station.station_id)}>Rows &amp; sources</button></div></footer>
  </article>;
}
export function PairedDemo(props:RadialProps) {
  const [locatorOpen,setLocatorOpen]=useState(()=>typeof window==="undefined"||!isShortLandscape(window.innerWidth,window.innerHeight));
  useEffect(()=>{const resetForViewport=()=>setLocatorOpen(!isShortLandscape(window.innerWidth,window.innerHeight));window.addEventListener("resize",resetForViewport);return()=>window.removeEventListener("resize",resetForViewport);},[]);
  return <>
    <section className="paired-locator" aria-label="Station geography"><details open={locatorOpen} onToggle={event=>setLocatorOpen(event.currentTarget.open)}><summary>Pacific locator</summary>{props.geometry?<StationMap geometry={props.geometry} stations={props.manifest.stations} selectedStationId={props.state.selectedStationId} pinnedStationId={props.state.pinnedStationId} onSelectStation={props.onSelectStation}/>:props.geometryError?<div className="data-error" role="alert">Locator unavailable: {props.geometryError} <button type="button" onClick={props.onRetryGeometry}>Retry locator</button><p>The station selector remains available.</p></div>:<p role="status">Loading reviewed Pacific locator…</p>}</details></section>
    <section className="paired-records" aria-label="Separate station-local records">
      <StationCard selection={props.selected} role="selected" windowId={props.state.windowId} productKey={props.state.productKey} onOpenEvidence={props.onOpenEvidence} onRetryStation={props.onRetryStation}/>
      {props.pinned?<StationCard selection={props.pinned} role="pinned" windowId={props.state.windowId} productKey={props.state.productKey} onOpenEvidence={props.onOpenEvidence} onRetryStation={props.onRetryStation}/>:<article className="station-card station-card--empty"><h2>No reference pinned</h2><p>Use “Pin selected as reference” in More controls to retain a separate station identity.</p></article>}
    </section>
  </>;
}
