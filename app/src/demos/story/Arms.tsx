import type { CSSProperties, ReactNode } from "react";
import { RecordChart } from "../RecordChart";
import { SupportView } from "../SupportView";
import type { ProductKey, StationSelection } from "../types";
import { utcAt } from "./clock";

export const CAVEAT = "Contours are NOAA/NCEI published travel-time estimates: hours after the earthquake, computed from a point at the epicentre (not the full rupture), first arrival only, no wave height. Not a station's arrival, and not warning time.";
export type Reading = { a: number; b: number } | null;
type ArmsProps = {
  ocean: boolean; atOrigin: boolean; nearestName: string; reading: Reading; t: number; originUtc: string;
  a: StationSelection; b: StationSelection | null; windowId: string; productKey: ProductKey;
  onRetry: () => void; styles: { record: CSSProperties; support: CSSProperties; read: CSSProperties };
};
const typeLabel = (s: StationSelection) => s.station.station_type === "dart" ? "Deep-ocean DART buoy" : "Coastal tide gauge";

function hereText(reading: Reading, t: number): ReactNode {
  if (!reading) return "No published contour runs near this point.";
  const span = `${reading.a} h and ${reading.b} h`;
  if (t < reading.a) return <>NOAA/NCEI's published estimate reaches this area between <b>{span}</b>. The clock is at {t.toFixed(1)} h.</>;
  if (t < reading.b + 1) return <>The clock is inside this area's published <b>{span}</b> band.</>;
  return <>The published estimate passed this area between <b>{span}</b>.</>;
}
function windowEnd(s: StationSelection, windowId: string): number | null {
  const w = s.records?.support.find(x => x.window_id === windowId);
  return w ? Date.parse(w.end_utc_exclusive) : null;
}
function Record({ s, tag, cursorMs, windowId, productKey, onRetry }: { s: StationSelection; tag?: "A" | "B"; cursorMs: number; windowId: string; productKey: ProductKey; onRetry: () => void }) {
  const head = <p className="story-arm__who">{tag && <span className={`story-tag story-tag--${tag.toLowerCase()}`}>{tag}</span>}<b>{s.station.name}</b> <span>{typeLabel(s)}</span></p>;
  if (s.status === "error") return <div role="alert">{head}<p>{s.error}</p><button type="button" onClick={onRetry}>Retry record</button></div>;
  if (s.status !== "ready" || !s.records) return <div role="status">{head}<p>Loading {s.station.name}'s record…</p></div>;
  const end = windowEnd(s, windowId);
  return <div>{head}<RecordChart station={s.station} records={s.records} windowId={windowId} productKey={productKey} role={tag === "B" ? "pinned" : "selected"} cursorMs={cursorMs} height={tag ? 128 : 160} compact/>
    {end !== null && cursorMs >= end && <p className="story-arm__note">No record loaded for this time; the loaded record ends {new Date(end).toISOString().slice(11, 16)} UTC.</p>}</div>;
}
function Support({ s, tag, cursorMs, windowId, productKey }: { s: StationSelection; tag?: "A" | "B"; cursorMs: number; windowId: string; productKey: ProductKey }) {
  if (s.status !== "ready" || !s.records) return null;
  return <div>{tag && <p className="story-arm__who"><span className={`story-tag story-tag--${tag.toLowerCase()}`}>{tag}</span><b>{s.station.name}</b></p>}
    <SupportView station={s.station} records={s.records} windowId={windowId} productKey={productKey} cursorMs={cursorMs} compact/></div>;
}

/** Record (upper left), what supports it (upper right), how to read it (below). */
export function Arms({ ocean, atOrigin, nearestName, reading, t, originUtc, a, b, windowId, productKey, onRetry, styles }: ArmsProps) {
  const cursorMs = Date.parse(originUtc) + t * 3_600_000, both = !!b;
  return <>
    <section className="story-arm" style={styles.record} aria-label="Record at the story clock">
      <h2 className="story-arm__h">{both ? "Records at the same clock" : "Record at the same clock"}</h2>
      {ocean ? <><p className="story-arm__big">No station record here</p><p>No instrument measured this water. Nearest record: <b>{nearestName}</b>.</p></>
        : <Record s={a} tag={both ? "A" : undefined} cursorMs={cursorMs} windowId={windowId} productKey={productKey} onRetry={onRetry}/>}
      {b && <Record s={b} tag="B" cursorMs={cursorMs} windowId={windowId} productKey={productKey} onRetry={onRetry}/>}
      {both && <p className="story-arm__note">Shared UTC axis and clock; heights stay station-local and are not compared.</p>}
    </section>
    <section className="story-arm" style={styles.support} aria-label={ocean ? "Published clock at this point" : "What supports the record"}>
      {ocean ? <><h2 className="story-arm__h">Published clock here</h2>{atOrigin ? <p>The published clock starts here, at the epicentre, at <b>0 h</b> ({utcAt(originUtc, 0)}). NOAA/NCEI's first contour is the 1 h line around it.</p>
        : <p>{reading ? <>Nearest published contours: <b>{reading.a} h</b> and <b>{reading.b} h</b>.</> : null} {hereText(reading, t)}</p>}</>
        : <><h2 className="story-arm__h">What supports it</h2><Support s={a} tag={both ? "A" : undefined} cursorMs={cursorMs} windowId={windowId} productKey={productKey}/></>}
      {b && <Support s={b} tag="B" cursorMs={cursorMs} windowId={windowId} productKey={productKey}/>}
    </section>
    <section className="story-arm story-arm--read" style={styles.read} aria-label="How to read this">
      <h2 className="story-arm__h">Read this as</h2>
      <p>{ocean ? CAVEAT : <>The white line is the clock ({utcAt(originUtc, t)}), not an arrival pick. The published contours near {a.station.name} are model estimates, not its arrival. Source: {a.station.source.publisher}.</>}</p>
    </section>
  </>;
}
