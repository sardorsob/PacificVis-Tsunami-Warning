import { RecordChart, SliceChart } from "./RecordChart";
import { SliceSupport, SupportView } from "./SupportView";
import { safeSourceUrl } from "./loader";
import { isSlice } from "./slices";
import { ClockNote, kindLabel } from "./story/Arms";
import type { ReactNode } from "react";
import type { AnySelection, ProductKey } from "./types";

export type StationCardProps = {
  selection: AnySelection; role: "selected" | "pinned"; windowId: string; productKey: ProductKey;
  /** The shared clock: a time on the record, never an arrival pick. */
  cursorMs?: number;
  onOpenEvidence: (stationId: string) => void; onRetryStation: (stationId: string) => void;
  /** Shown under the header whatever the record's state (Station lens: the station's three-clocks strip). */
  clocks?: ReactNode;
};
/** One station's full record on the shared clock: chart, gap support and source. Hook-free, so tests can walk it. */
export function StationCard({ selection, role, windowId, productKey, cursorMs, onOpenEvidence, onRetryStation, clocks }: StationCardProps) {
  const { station, status, error } = selection, ready = status === "ready" && selection.records !== null, url = safeSourceUrl(station.source.url);
  const tag = role === "selected" ? "A" : "B";
  // A schema-2 bundle has no publisher, title, time basis or horizontal datum: those lines are left out, not filled in.
  const body = !ready ? null : isSlice(selection) ? <>
    <SliceChart station={selection.station} records={selection.records!} role={role} cursorMs={cursorMs}/>
    <SliceSupport station={selection.station} records={selection.records!}/>
  </> : <>
    <RecordChart station={selection.station} records={selection.records!} windowId={windowId} productKey={productKey} role={role} cursorMs={cursorMs}/>
    {cursorMs !== undefined && <ClockNote s={selection} windowId={windowId} cursorMs={cursorMs}/>}
    <SupportView station={selection.station} records={selection.records!} windowId={windowId} productKey={productKey} cursorMs={cursorMs}/>
  </>;
  return <article className={`story-card story-card--${role}`} aria-label={`${role === "selected" ? "Selected" : "Pinned reference"}: ${station.name}`}>
    <header className="story-card__head"><span className={`story-tag story-tag--${tag.toLowerCase()}`}>{tag}</span>
      <h2>{station.name} <span>{station.station_id}</span></h2><p>{kindLabel(station)}</p></header>
    {clocks}
    {ready ? body : status === "error" ? <div className="story-card__error" role="alert"><p>{station.name}: {error}</p>
      <button type="button" aria-label={`Retry ${station.name}`} onClick={() => onRetryStation(station.station_id)}>Retry {station.name}</button></div>
      : <p className="story-card__loading" role="status">Loading and verifying {station.name} records…</p>}
    <footer className="story-card__source">
      {isSlice(selection) ? <p>{selection.station.units} · vertical datum {selection.station.vertical_datum} · source {selection.station.source.source_id}.
        Plotted in UTC; source QC retained and never used to filter.</p> : <>
        <p>Source: {selection.station.source.publisher} · {selection.station.source.title}</p>
        <p>Source time basis: {selection.station.time_basis}; verified observations plotted in UTC. Vertical datum: {selection.station.vertical_reference}; horizontal datum:
          {" "}{selection.station.horizontal_datum}. Source QC retained; empty flags do not certify QC pass.</p></>}
      <div>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{isSlice(selection) ? "Source file ↗" : "Publisher record ↗"}</a> : <span>Source link unavailable; provenance retained.</span>}
        <button type="button" aria-label={`Rows & sources: ${station.name}`} disabled={!ready} onClick={() => onOpenEvidence(station.station_id)}>
          Rows &amp; sources</button></div>
    </footer>
  </article>;
}
export const NoReference = () => <article className="story-card story-card--empty" aria-label="Pinned reference: none">
  <h2>No reference pinned</h2><p>Pick a B station to compare its record on the same clock. Heights stay station-local.</p></article>;
