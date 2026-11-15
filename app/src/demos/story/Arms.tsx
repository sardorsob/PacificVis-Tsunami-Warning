import type { CSSProperties, ReactNode } from "react";
import { RecordChart, SliceChart } from "../RecordChart";
import { isSlice, isSliceStation, SLICE_PRODUCT_LABEL } from "../slices";
import { SliceSupport, SupportView } from "../SupportView";
import type { AnySelection, AnyStation, ProductKey } from "../types";
import type { StoryArrivals } from "./arrivals";
import { utcAt } from "./clock";
import { ThreeClocks } from "./ThreeClocks";

export const CAVEAT = "Contours are NOAA/NCEI published travel-time estimates: hours after the earthquake, computed from a point at the epicentre (not the full rupture), for the first wave only, with no wave height. A contour is not a time reported at any station, and not when a warning was issued.";
type Reading = { a: number; b: number } | null;
type ArmsProps = {
  /** The event lists published contours. */
  listed: boolean;
  /** nearestName and a are null only for an event without a records bundle (no stations: the lens is always over open water). */
  ocean: boolean; atOrigin: boolean; nearestName: string | null; reading: Reading; t: number; originUtc: string;
  a: AnySelection | null; b: AnySelection | null; windowId: string; productKey: ProductKey;
  onRetry: (stationId: string) => void; onOpenEvidence: (stationId: string) => void;
  /** The reported-times file to show (shownArrivals), or null: then the record arm has no three-clocks strip. */
  arrivals: StoryArrivals | null;
  styles: { record: CSSProperties; support: CSSProperties; read: CSSProperties };
};
export const typeLabel = (type: string) => type === "dart" ? "Deep-ocean DART buoy" : "Coastal tide gauge";
/** What a station's record is: its type (records schema 1), or its one product (schema 2 gives no station type). */
export const kindLabel = (s: AnyStation) => isSliceStation(s) ? SLICE_PRODUCT_LABEL[s.product] : typeLabel(s.station_type);

function hereText(reading: Reading, t: number): ReactNode {
  if (!reading) return "No published contour runs near this point.";
  const span = `${reading.a} h and ${reading.b} h`;
  if (t < reading.a) return <>NOAA/NCEI's published estimate reaches this area between <b>{span}</b>. The clock is at {t.toFixed(1)} h.</>;
  if (t < reading.b + 1) return <>The clock is inside this area's published <b>{span}</b> band.</>;
  return <>The published estimate passed this area between <b>{span}</b>.</>;
}
function windowSpan(s: AnySelection, windowId: string): [number, number] | null {
  if (isSlice(s)) return null; // a schema-2 record spans origin − 6 h to + 30 h: every clock time is inside it
  const w = s.records?.support.find(x => x.window_id === windowId);
  return w ? [Date.parse(w.start_utc), Date.parse(w.end_utc_exclusive)] : null;
}
const hhmm = (ms: number) => new Date(ms).toISOString().slice(11, 16);
/** When the clock is outside the loaded record: a time with no data, never a gap in the record. */
export function ClockNote({ s, windowId, cursorMs }: { s: AnySelection; windowId: string; cursorMs: number }) {
  const span = windowSpan(s, windowId);
  if (span && cursorMs >= span[1]) return <p className="story-arm__note">No record loaded for this time; the loaded record ends {hhmm(span[1])} UTC.</p>;
  if (span && cursorMs < span[0]) return <p className="story-arm__note">No record loaded for this time; the loaded record starts {hhmm(span[0])} UTC.</p>;
  return null;
}
type RecordProps = { s: AnySelection; tag?: "A" | "B"; cursorMs: number; windowId: string; productKey: ProductKey };
const Tag = ({ tag }: { tag: "A" | "B" }) => <span className={`story-tag story-tag--${tag.toLowerCase()}`}>{tag}</span>;
function Record({ s, tag, cursorMs, windowId, productKey, onRetry, clocks }: RecordProps & { onRetry: (stationId: string) => void; clocks?: ReactNode }) {
  const head = <><p className="story-arm__who">{tag && <Tag tag={tag}/>}<b>{s.station.name}</b> <span>{kindLabel(s.station)}</span></p>{clocks}</>;
  if (s.status === "error") return <div role="alert">{head}<p>{s.error}</p>
    <button type="button" onClick={() => onRetry(s.station.station_id)}>Retry record</button></div>;
  if (s.status !== "ready" || !s.records) return <div role="status">{head}<p>Loading {s.station.name}'s record…</p></div>;
  const role = tag === "B" ? "pinned" : "selected", height = tag ? 128 : 160;
  return <div>{head}
    {isSlice(s) ? <SliceChart station={s.station} records={s.records!} role={role} cursorMs={cursorMs} height={height} compact/>
      : <RecordChart station={s.station} records={s.records!} windowId={windowId} productKey={productKey} role={role} cursorMs={cursorMs} height={height} compact/>}
    <ClockNote s={s} windowId={windowId} cursorMs={cursorMs}/></div>;
}
function Support({ s, tag, cursorMs, windowId, productKey }: RecordProps) {
  if (s.status !== "ready" || !s.records) return null;
  return <div>{tag && <p className="story-arm__who"><Tag tag={tag}/><b>{s.station.name}</b></p>}
    {isSlice(s) ? <SliceSupport station={s.station} records={s.records!} compact/>
      : <SupportView station={s.station} records={s.records!} windowId={windowId} productKey={productKey} cursorMs={cursorMs} compact/>}</div>;
}

/** Record (upper left), what supports it (upper right), how to read it (below). The record arm opens on the three-clocks strip: above A's
 * record, or in Compare A's and B's stacked on one axis above both records. */
export function Arms(props: ArmsProps) {
  const { listed, ocean, atOrigin, nearestName, reading, t, originUtc, a, b, windowId, productKey, onRetry, onOpenEvidence, arrivals, styles } = props;
  const cursorMs = Date.parse(originUtc) + t * 3_600_000, both = !!b, here = ocean ? null : a;
  const clocks = (list: { s: AnySelection; tag?: "A" | "B" }[]) => arrivals && list.length > 0 && <ThreeClocks arrivals={arrivals} t={t}
    stations={list.map(({ s, tag }) => ({ id: s.station.station_id, name: s.station.name, tag }))}/>;
  return <>
    <section className="story-arm story-arm--side" style={styles.record} aria-label="Record at the story clock">
      <h2 className="story-arm__h">{both ? "Records at the same clock" : "Record at the same clock"}</h2>
      {b && clocks([...(here ? [{ s: here, tag: "A" as const }] : []), { s: b, tag: "B" }])}
      {nearestName === null ? <p className="story-arm__big">No station records are published for this event.</p>
        : !here ? <><p className="story-arm__big">{both ? "A: no station record here" : "No station record here"}</p>
        <p>No instrument measured this water. Nearest record: <b>{nearestName}</b>.</p></>
        : <Record s={here} tag={both ? "A" : undefined} cursorMs={cursorMs} windowId={windowId} productKey={productKey} onRetry={onRetry}
          clocks={both ? null : clocks([{ s: here }])}/>}
      {b && <Record s={b} tag="B" cursorMs={cursorMs} windowId={windowId} productKey={productKey} onRetry={onRetry}/>}
      {both && <p className="story-arm__note">Shared UTC axis and clock; heights stay station-local and are not compared.</p>}
    </section>
    <section className="story-arm story-arm--side" style={styles.support} aria-label={here ? "What supports the record" : listed ? "Published clock at this point" : "The clock at this point"}>
      {!here && !listed ? <><h2 className="story-arm__h">The clock here</h2>
        <p>{atOrigin ? <>The clock starts here, at the epicentre, at <b>0 h</b> ({utcAt(originUtc, 0)}).</> : "No published travel-time contours are listed for this event."}</p></>
        : !here ? <><h2 className="story-arm__h">Published clock here</h2>
        {atOrigin ? <p>The published clock starts here, at the epicentre, at <b>0 h</b> ({utcAt(originUtc, 0)}).
          NOAA/NCEI's first contour is the 1 h line around it.</p>
          : <p>{reading ? <>Nearest published contours: <b>{reading.a} h</b> and <b>{reading.b} h</b>.</> : null} {hereText(reading, t)}</p>}</>
        : <><h2 className="story-arm__h">What supports it</h2>
          <Support s={here} tag={both ? "A" : undefined} cursorMs={cursorMs} windowId={windowId} productKey={productKey}/></>}
      {b && <Support s={b} tag="B" cursorMs={cursorMs} windowId={windowId} productKey={productKey}/>}
    </section>
    <section className="story-arm story-arm--read" style={styles.read} aria-label="How to read this">
      <h2 className="story-arm__h">Read this as</h2>
      <p>{!here ? listed ? CAVEAT : "Marks light up as the clock reaches each published estimate or reported time; a filled mark takes its reported hour's colour."
        : <>The white line is the clock ({utcAt(originUtc, t)}); no time is picked from the record.{listed && <>
        {" "}The published contours near {here.station.name} are model estimates, not a time reported there.</>}{!isSlice(here) && <> Source: {here.station.source.publisher}.</>}</>}</p>
      {here?.status === "ready"
        && <button type="button" className="story-evidence" onClick={() => onOpenEvidence(here.station.station_id)}>Rows &amp; sources</button>}
    </section>
  </>;
}
