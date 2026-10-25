import { RecordChart } from "./RecordChart";
import { SupportView } from "./SupportView";
import { safeSourceUrl } from "./loader";
import { ClockNote, typeLabel } from "./story/Arms";
import type { ProductKey, StationSelection } from "./types";

export type StationCardProps = {
  selection: StationSelection; role: "selected" | "pinned"; windowId: string; productKey: ProductKey;
  /** The shared clock: a time on the record, never an arrival pick. */
  cursorMs?: number;
  onOpenEvidence: (stationId: string) => void; onRetryStation: (stationId: string) => void;
};
/** One station's full record on the shared clock: chart, gap support and source. Hook-free, so tests can walk it. */
export function StationCard({ selection, role, windowId, productKey, cursorMs, onOpenEvidence, onRetryStation }: StationCardProps) {
  const { station, records, status, error } = selection, ready = status === "ready" && records !== null, url = safeSourceUrl(station.source.url);
  const tag = role === "selected" ? "A" : "B";
  return <article className={`story-card story-card--${role}`} aria-label={`${role === "selected" ? "Selected" : "Pinned reference"}: ${station.name}`}>
    <header className="story-card__head"><span className={`story-tag story-tag--${tag.toLowerCase()}`}>{tag}</span>
      <h2>{station.name} <span>{station.station_id}</span></h2><p>{typeLabel(station.station_type)}</p></header>
    {ready ? <>
      <RecordChart station={station} records={records} windowId={windowId} productKey={productKey} role={role} cursorMs={cursorMs}/>
      {cursorMs !== undefined && <ClockNote s={selection} windowId={windowId} cursorMs={cursorMs}/>}
      <SupportView station={station} records={records} windowId={windowId} productKey={productKey} cursorMs={cursorMs}/>
    </> : status === "error" ? <div className="story-card__error" role="alert"><p>{station.name}: {error}</p>
      <button type="button" aria-label={`Retry ${station.name}`} onClick={() => onRetryStation(station.station_id)}>Retry {station.name}</button></div>
      : <p className="story-card__loading" role="status">Loading and verifying {station.name} records…</p>}
    <footer className="story-card__source">
      <p>Source: {station.source.publisher} · {station.source.title}</p>
      <p>Source time basis: {station.time_basis}; verified observations plotted in UTC. Vertical datum: {station.vertical_reference}; horizontal datum:
        {" "}{station.horizontal_datum}. Source QC retained; empty flags do not certify QC pass.</p>
      <div>{url ? <a href={url} target="_blank" rel="noopener noreferrer">Publisher record ↗</a> : <span>Source link unavailable; provenance retained.</span>}
        <button type="button" aria-label={`Rows & sources: ${station.name}`} disabled={!ready} onClick={() => onOpenEvidence(station.station_id)}>
          Rows &amp; sources</button></div>
    </footer>
  </article>;
}
export const NoReference = () => <article className="story-card story-card--empty" aria-label="Pinned reference: none">
  <h2>No reference pinned</h2><p>Pick a B station to compare its record on the same clock. Heights stay station-local.</p></article>;
