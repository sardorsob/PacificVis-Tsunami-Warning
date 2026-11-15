import type { ReactNode } from "react";
import type { SliceRecords } from "../slices";
import type { EventEntry, StationRecords } from "../types";
import type { ArrivalDisplay } from "./arrivals";
import { clockLabel, T_MAX, utcAt, utcDate, utcDayAt } from "./clock";
import { contourColour } from "./palette";
import { placeName, ReportMark } from "./StoryMap";

/** Samples with a raw value in each hour after origin; null where the loaded window does not cover the whole hour. */
// ponytail: one station's strip, from the record already loaded; an all-station strip would load every record (~33 MB).
export function hourlySamples(records: StationRecords | SliceRecords, windowId: string, originUtc: string): (number | null)[] {
  const origin = Date.parse(originUtc);
  if ("segments" in records) { // schema 2: drawn points per hour; its display window (origin − 6 h to + 30 h) covers every clock hour
    const out: number[] = Array(T_MAX).fill(0);
    for (const p of records.segments.flat()) { const h = Math.floor((p.t - origin) / 3_600_000); if (h >= 0 && h < T_MAX) out[h]++; }
    return out;
  }
  const w = records.support.find(s => s.window_id === windowId);
  const from = w ? Date.parse(w.start_utc) : 0, to = w ? Date.parse(w.end_utc_exclusive) : 0, out: (number | null)[] = [];
  for (let h = 0; h < T_MAX; h++) { const a = origin + h * 3_600_000, b = a + 3_600_000; out.push(a >= from && b <= to ? 0 : null); }
  for (const r of records.rows) { if (r.raw_value === null) continue; const h = Math.floor((Date.parse(r.observed_at_utc) - origin) / 3_600_000);
    if (h >= 0 && h < T_MAX && out[h] !== null) out[h] = (out[h] as number) + 1; }
  return out;
}
function Strip({ counts, t, label }: { counts: (number | null)[] | null; t: number; label: string }) {
  const w = 252, h = 44, cw = w / T_MAX, max = counts ? Math.max(1, ...counts.map(c => c ?? 0)) : 1;
  return <svg className="story-strip" width={w} height={h + 14} role="img" aria-label={label}>
    {Array.from({ length: T_MAX }, (_, i) => { const past = i + 1 <= t + 1e-9, cur = i === Math.floor(t), c = counts ? counts[i] : 1, x = i * cw + 0.5;
      if (c === null) return <rect key={i} x={x} y={h - 6} width={cw - 1} height={6} className="story-strip__none"/>;
      const bh = counts ? Math.max(2, (c / max) * (h - 4)) : 12;
      return <rect key={i} x={x} y={h - bh} width={cw - 1} height={bh} rx={1} fill={past || cur ? contourColour(i + 1) : "var(--story-muted)"}
        opacity={past ? 1 : cur ? 0.7 : 0.28}/>; })}
    <line x1={(t / T_MAX) * w} x2={(t / T_MAX) * w} y1={0} y2={h} className="story-strip__now"/>
    {[0, 10, 20, 30].map(v => <text key={v} x={Math.min(w - 10, (v / T_MAX) * w)} y={h + 12} textAnchor={v ? "middle" : "start"}
      className="story-strip__tick">{v} h</text>)}
  </svg>;
}
type ClockColumnProps = {
  /** The open event's index entry: its origin, label and listed bundles word the column. */
  t: number; entry: EventEntry; stationName: string | null; counts: (number | null)[] | null;
  lead?: ReactNode; children: ReactNode; alert: ReactNode; className?: string; title?: string; label?: string; head: boolean;
  /** The reported-times file's marks and counts, "rejected", or null while it loads (or when the event has none). */
  reported?: ArrivalDisplay | "rejected" | null;
  /** The key starts open (Station lens folds it, so its station tools fit the column). */
  keyOpen?: boolean;
  /** Who supplied the records (recordProviders), credited at the foot. */
  providers?: readonly string[];
};
const KEY = [["estimate", "NTWC published estimate"], ["ntwc", "NTWC reported time"], ["tide", "NCEI reported time (timed from NCEI's own origin)"],
  ["deep", "NCEI deep-ocean reported time"]] as const;
/** The reported-times key: the four marks, the source tables' counts, what reported times are not, and what is listed but not drawn. */
function ReportedKey({ d, open }: { d: ArrivalDisplay; open: boolean }) {
  const a = d.accounting, hidden = [d.unplaced && `${d.unplaced} without a place`,
    d.beforeOrigin && `${d.beforeOrigin} before the earthquake origin (the project does not correct dates)`,
    d.afterClock && `${d.afterClock} after the 30-hour clock ends`];
  return <details className="story-legend story-key" open={open}>
    <summary>Reported times and published estimates</summary>
    <p>They light up when the clock reaches them; a filled mark takes its reported hour's colour.</p>
    <ul>{KEY.map(([kind, label]) => <li key={kind}>
      <svg width="14" height="14" aria-hidden="true"><ReportMark kind={kind} minutes={360} x={7} y={7} on/></svg>{label}</li>)}</ul>
    <p>{`${a.ntwc_rows_with_both_times} estimate–reported pairs in the NTWC table · ${a.ntwc_pairs_with_position} with a reviewed position · `
      + `${a.ncei_reported_durations} NCEI reported times`}</p>
    <p>Reported times are what the sources reported, not validated arrival times; a difference does not say which side is off.</p>
    {hidden.some(Boolean) && <p>{`Listed reports not drawn on the map: ${hidden.filter(Boolean).join(" · ")}.`}</p>}
  </details>;
}
/** Every view's kicker: "Pacific · {UTC date of the origin}". */
export const kicker = (originUtc: string) => `Pacific · ${utcDate(originUtc)}`;
/** The page kicker and title: top of the column when wide, top of the sheet otherwise. */
export const ColumnHead = ({ originUtc, title = "How the published tsunami clock spread" }: { originUtc: string; title?: string }) => <>
  <p className="story-kicker">{kicker(originUtc)}</p><h1 className="story-title">{title}</h1></>;
/** Editorial column: what this is, the clock, a strip tied to the lens, the legend, then step or station controls. */
export function ClockColumn({ t, entry, stationName, counts, lead, children, alert, className = "", title, label = "Story",
  head, reported, keyOpen = true, providers = [] }: ClockColumnProps) {
  const max = counts ? Math.max(0, ...counts.map(c => c ?? 0)) : 0, originUtc = entry.origin_time_utc, listed = !!entry.layers;
  return <aside className={`story-column ${className}`} aria-label={label}>
    {head && <ColumnHead originUtc={originUtc} title={title}/>}
    {/* Without listed contours, Notes (in `alert`) says so instead. */}
    {listed && <p className="story-small">NOAA/NCEI travel-time contours, one line per hour after the {utcAt(originUtc, 0)} {placeName(entry.label)} origin.</p>}
    {alert}
    {lead}
    <p className="story-bigclock">{clockLabel(t)}</p>
    <p className="story-utc">{utcAt(originUtc, t)} · {utcDayAt(originUtc, t)}</p>
    <p className="story-small"><b>{stationName ? `Samples per hour in ${stationName}'s record` : listed ? "Published hours on the map" : "Hours after the earthquake"}</b>
      {stationName ? ` (busiest hour: ${max})` : ""}</p>
    <Strip counts={counts} t={t} label={stationName
      ? `Samples per hour after the earthquake in ${stationName}'s record; dashed where no record is loaded`
      : listed ? "Published contour hours lit up to the clock" : "Hours after the earthquake, lit up to the clock"}/>
    {listed && <p className="story-legend"><b>Colour shows the published hour</b>: not wave height, not a reported time, and not when a warning was issued.</p>}
    {reported === "rejected"
      ? <p className="story-legend">The reported-times file was rejected, so no published estimates or reported times are shown.</p>
      : reported && <ReportedKey d={reported} open={keyOpen}/>}
    {children}
    <p className="story-credits">{listed && "NOAA/NCEI travel-time contours: hours after the earthquake, computed by NCEI from a point at the epicentre (not the full rupture), for the first wave only, with no wave height. "}
      {providers.length > 0 && `Records: ${providers.join(" · ")}. `}{entry.arrivals && "Reported times: NTWC and NCEI source records. "}
      Natural Earth {listed ? "1:50m" : "1:110m"} · Equal Earth, 160° W. Internal descriptive evidence only.</p>
  </aside>;
}
