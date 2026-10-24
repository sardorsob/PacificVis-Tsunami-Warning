import { useMemo } from "react";
import type { DemoGeometry,StationMetadata } from "./types";

export type StationMapProps={geometry:DemoGeometry;stations:StationMetadata[];selectedStationId:string;pinnedStationId:string|null;onSelectStation:(stationId:string)=>void};
export function StationMap({geometry,stations,selectedStationId,pinnedStationId,onSelectStation}:StationMapProps) {
  const [xmin,ymin,xmax,ymax]=geometry.bounds;
  const x=(value:number)=>(value-xmin)/(xmax-xmin)*100;
  const y=(value:number)=>100-(value-ymin)/(ymax-ymin)*100;
  const coastline=useMemo(()=>geometry.coastline.map(line=>line.map(([px,py],i)=>`${i?"L":"M"}${x(px).toFixed(3)},${y(py).toFixed(3)}`).join("")).join(""),[geometry]);
  return <figure className="station-map">
    <div className="station-map__surface" style={{width:`calc(var(--locator-height, 130px) * ${(xmax-xmin)/(ymax-ymin)})`,height:"auto",maxWidth:"100%",aspectRatio:`${xmax-xmin} / ${ymax-ymin}`}}>
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d={coastline} fill="none" stroke="#769092" strokeWidth="0.6" vectorEffect="non-scaling-stroke"/></svg>
      {stations.map(station=>{const point=geometry.points.find(p=>p.id===station.station_id)!;const selected=station.station_id===selectedStationId,pinned=station.station_id===pinnedStationId;
        return <button key={station.station_id} type="button" className={`map-station${selected?" map-station--selected":""}${pinned?" map-station--pinned":""}`} style={{left:`${x(point.x)}%`,top:`${y(point.y)}%`}} onClick={()=>onSelectStation(station.station_id)} aria-label={`${selected?"Selected: ":pinned?"Pinned reference: ":"Select "}${station.name} (${station.station_id})${selected&&pinned?", also pinned reference":""}`} aria-pressed={selected}>
          <span className="map-station__mark" aria-hidden="true"/>{(selected||pinned)&&<span className="map-station__label">{selected?"○":"◇"} {station.name}</span>}
        </button>;
      })}
    </div>
    <figcaption>Pacific locator · Equal Earth −160° · Natural Earth 1:110m v4.1.0. ○ selected · ◇ pinned. Crowded marks: use station selector. No arrival surface.</figcaption>
  </figure>;
}
