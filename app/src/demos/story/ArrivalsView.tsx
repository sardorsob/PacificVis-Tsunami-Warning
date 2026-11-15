import { useMemo, useRef } from "react";
import { AFTER_CLOCK, BEFORE_ORIGIN, differenceWords, ESTIMATE_AFTER_CLOCK, ladderRows, notDrawn, shownArrivals } from "./arrivals";
import type { LadderRow, StoryArrivals } from "./arrivals";
import { ClockBar } from "./ClockBar";
import { kicker } from "./ClockColumn";
import { usePageClock } from "./PairedView";
import type { AnyStation } from "../types";
import { Notes, type StoryViewProps } from "./StoryView";
import { clockAt, distance, HourTicks, Lane, nceiTime, ntwcTimes } from "./ThreeClocks";
import { EventSelect, ViewSwitch } from "./ViewSwitch";
import "./style.css";

type Sort = "time" | "distance";
const NO_PATHS = new Map<number, string>();
export const many = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;
const cell = (text: string | null) => text === null ? "empty" : `“${text}”`;

function Row({ report: r, place }: LadderRow) {
  const d = r.reported_minus_estimate_minutes, doubtful = r.source_flags.includes("doubtful") ? " · NCEI marks it doubtful" : "";
  return <li className="ladder-row">
    <p><b>{r.place_text}</b>{place ? ` · ${distance(place.distance_km)}` : ""}</p>
    <Lane r={r}/>
    <p>{r.source === "ntwc" ? [ntwcTimes(r), d !== null && differenceWords(d)].filter(Boolean).join(" · ")
      : `reported ${nceiTime(r.reported_minutes!)} · ${r.gauge_kind === "deep_ocean_gauge" ? "deep-ocean gauge" : "tide gauge"}`}</p>
    <p className="ladder-row__src">{r.source === "ntwc"
      ? `Source cells: estimate ${cell(r.estimate_text)} · reported ${cell(r.reported_text)} · ${r.source_id}` : `Source: ${r.source_id}${doubtful}`}</p>
    {notDrawn(r).map(note => <p key={note} className="ladder-row__note">{note}</p>)}
  </li>;
}
function Section({ title, note, rows }: { title: string; note: string; rows: LadderRow[] }) {
  return <section className="ladder-section" aria-label={title}>
    <h2 className="story-h">{`${title} · ${many(rows.length, "row")}`}</h2><p className="story-small">{note}</p>
    {rows.length ? <><div className="ladder-axis"><HourTicks/></div>
      <ol className="ladder-rows">{rows.map(row => <Row key={row.report.report_id} {...row}/>)}</ol></>
      : <p className="story-small">None listed for this event.</p>}
  </section>;
}
type LadderProps = { arrivals: StoryArrivals; sort: Sort; onSort: (sort: Sort) => void };
/** The ladder: honest counts, what is listed but not drawn, the sort control, then NTWC rows and, apart, NCEI rows. Hook-free, so tests walk it. */
export function Ladder({ arrivals: a, sort, onSort }: LadderProps) {
  const { ntwc, ncei } = ladderRows(a, sort), acc = a.accounting;
  const hidden = (notes: string[]) => a.reports.filter(r => notDrawn(r).some(n => notes.includes(n))).length;
  const before = hidden([BEFORE_ORIGIN]), after = hidden([AFTER_CLOCK, ESTIMATE_AFTER_CLOCK]);
  return <>
    <p className="ladder-counts">{[`${many(acc.ntwc_rows_with_both_times, "estimate–reported pair")} in the NTWC table`,
      `${acc.ntwc_pairs_with_position} with a reviewed position`, `${many(ntwc.filter(r => !r.place).length, "NTWC report")} without a place`,
      many(acc.ncei_reported_durations, "NCEI reported time")].join(" · ")}</p>
    {before + after > 0 && <p className="story-small">{`Listed rows not drawn on the ladder: ${[before && `${before} before the earthquake origin `
      + "(the project does not correct dates)", after && `${after} after the 30-hour clock ends`].filter(Boolean).join(" · ")}.`}</p>}
    <div className="ladder-sort" role="group" aria-label="Sort rows"><span className="story-small">Sort rows by</span>
      {(["time", "distance"] as const).map(s => <button key={s} type="button" aria-pressed={sort === s} onClick={() => { if (s !== sort) onSort(s); }}>
        {s === "time" ? "Reported time" : "Distance"}</button>)}</div>
    <Section title="NTWC table · published estimates and reported times" rows={ntwc} note={"▽ published estimate joined to ● reported time, both from one "
      + "NTWC table row, in UTC. The estimate's method and issue time are unknown. Straight-line distances only for rows with a reviewed position."}/>
    <Section title="Reported by NCEI, timed from NCEI's own origin" rows={ncei} note={"■ tide gauge · ▲ deep-ocean gauge. Each duration counts from NCEI's "
      + "origin; NCEI rows are never differenced against NTWC rows or merged with them."}/>
  </>;
}

/** Reported times (?view=times): every listed report as a row on the shared clock, a scrolling page like Paired. */
export function ArrivalsView(props: StoryViewProps) {
  const { manifest, state } = props, origin = manifest.event.origin_time_utc;
  const stationIds = useMemo(() => (manifest.stations as readonly AnyStation[]).map(s => s.station_id), [manifest]), svgRef = useRef<SVGSVGElement>(null);
  const { clock, live, toggle, said, motionOK, clockOff } = usePageClock(props, svgRef, NO_PATHS, stationIds);
  const file = shownArrivals(props.arrivals), sort = state.sort ?? "time";
  // The rows never read the clock (its line is the CSS variable set below), so a playing clock re-renders none of the 400-odd rows.
  const rows = useMemo(() => file && <Ladder arrivals={file} sort={sort} onSort={s => props.onState({ sort: s }, live())}/>, [file, sort]);
  return <main className="story story--paired story--ladder" aria-label="Reported times">
    <header className="paired-head">
      <div><p className="story-kicker">{kicker(origin)}</p><h1 className="story-title">Reported times</h1>
        <p className="story-small">Every listed report on the clock bar's 0–30 h scale: NTWC published estimates and reported times, and NCEI reported times
          on their own. Reported times are what the sources reported, not validated onsets. A difference is plain subtraction and does not say which side
          is off; one-minute source resolution is not one-minute accuracy.</p></div>
      <div className="paired-head__tools"><ViewSwitch view="times" onView={v => props.onState({ view: v }, live())}/>
        <EventSelect events={props.events} value={props.entry.event_id} onEvent={id => props.onEvent(id, live())} onAll={() => props.onAllEvents(live())}/></div>
    </header>
    <Notes {...props}/>
    {rows ? <div style={clockAt(clock.t)}>{rows}</div>
      : props.arrivals === undefined ? <p role="status" className="story-alert">Loading the reported-times file…</p>
      : <p className="story-alert">{props.arrivals === null
        ? "This event has no reported-times file, so there are no published estimates or reported times to list."
        : "The reported-times file was rejected, so no published estimates or reported times are shown."}</p>}
    <ClockBar t={clock.t} playing={clock.playing} disabled={clockOff} contours={!!props.entry.layers} originUtc={origin} reduced={!motionOK} onToggle={toggle}
      onSeek={clock.seek}/>
    <footer className="paired-foot"><p>{manifest.bundle_id && `${manifest.bundle_id} · `}internal descriptive evidence only. Reported times come from NTWC and NCEI source records;
      nothing here is a model output or a prediction.</p></footer>
    <p className="story-sr" aria-live="polite">{said}</p>
  </main>;
}
