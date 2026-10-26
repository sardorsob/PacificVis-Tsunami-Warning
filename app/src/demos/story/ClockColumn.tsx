import type { ReactNode } from "react";
import type { StationRecords } from "../types";
import { clockLabel, T_MAX, utcAt, utcDayAt } from "./clock";
import { contourColour } from "./palette";

/** Samples with a raw value in each hour after origin; null where the loaded window does not cover the whole hour. */
// ponytail: one station's strip, from the record already loaded; an all-station strip would load every record (~33 MB).
export function hourlySamples(records: StationRecords, windowId: string, originUtc: string): (number | null)[] {
  const w = records.support.find(s => s.window_id === windowId), origin = Date.parse(originUtc);
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
  t: number; originUtc: string; stationName: string | null; counts: (number | null)[] | null;
  lead?: ReactNode; children: ReactNode; alert: ReactNode; className?: string; title?: string; label?: string; head: boolean;
};
/** The page kicker and title: top of the column when wide, top of the sheet otherwise. */
export const ColumnHead = ({ title = "How the published tsunami clock spread" }: { title?: string }) => <>
  <p className="story-kicker">Pacific · 11 March 2011</p><h1 className="story-title">{title}</h1></>;
/** Editorial column: what this is, the clock, a strip tied to the lens, the legend, then step or station controls. */
export function ClockColumn({ t, originUtc, stationName, counts, lead, children, alert, className = "", title, label = "Story",
  head }: ClockColumnProps) {
  const max = counts ? Math.max(0, ...counts.map(c => c ?? 0)) : 0;
  return <aside className={`story-column ${className}`} aria-label={label}>
    {head && <ColumnHead title={title}/>}
    <p className="story-small">NOAA/NCEI travel-time contours, one line per hour after the 05:46 UTC Tōhoku origin.</p>
    {alert}
    {lead}
    <p className="story-bigclock">{clockLabel(t)}</p>
    <p className="story-utc">{utcAt(originUtc, t)} · {utcDayAt(originUtc, t)}</p>
    <p className="story-small"><b>{stationName ? `Samples per hour in ${stationName}'s record` : "Published hours on the map"}</b>
      {stationName ? ` (busiest hour: ${max})` : ""}</p>
    <Strip counts={counts} t={t} label={stationName
      ? `Samples per hour after the earthquake in ${stationName}'s record; dashed where no record is loaded`
      : "Published contour hours lit up to the clock"}/>
    <p className="story-legend"><b>Colour shows the published hour.</b> Not wave height, not an arrival, not warning time.</p>
    {children}
    <p className="story-credits">NOAA/NCEI travel-time layer 17: hours after the earthquake, computed by NCEI from a point at the epicentre (not the full rupture), first arrival only, no wave height. Records: NOAA CO-OPS, NCEI DART, UHSLC/NTWC, IOC. Natural Earth 1:50m · Equal Earth, 160° W. Internal descriptive evidence only.</p>
  </aside>;
}
