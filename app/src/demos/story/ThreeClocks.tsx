import { differenceWords, linkedReports, markKind, notDrawn, onClock, WITHIN_1KM, type Report, type StoryArrivals } from "./arrivals";
import { HOUR_TICKS } from "./ClockBar";
import { T_MAX } from "./clock";
import { ReportMark } from "./StoryMap";

const pct = (minutes: number) => `${(minutes / (T_MAX * 60)) * 100}%`;
/** Places the clock line on every lane inside (a CSS variable, so a moving clock re-renders no lane). */
export const clockAt = (t: number) => ({ ["--clock" as string]: pct(t * 60) });
export const distance = (km: number) => `${km.toLocaleString("en-US")} km in a straight line from the epicentre`;
const utc = (iso: string) => `${iso.slice(11, 16)} UTC`;
/** An NTWC row's times in words, whichever it has: "published estimate 10:10 UTC · reported 10:18 UTC". */
export const ntwcTimes = (r: Report) => [r.estimate_utc && `published estimate ${utc(r.estimate_utc)}`, r.reported_utc && `reported ${utc(r.reported_utc)}`]
  .filter(Boolean).join(" · ");
/** An NCEI duration, counted from NCEI's origin: "7 h 56 min after NCEI's origin". */
export function nceiTime(minutes: number): string {
  const h = Math.floor(minutes / 60), m = Math.round((minutes - h * 60) * 1000) / 1000;
  return `${h ? `${h} h ` : ""}${m} min after NCEI's origin`;
}

/** One report on the clock bar's 0–30 h scale: ▽ published estimate joined to the reported mark (NTWC dot; NCEI square, deep-ocean
 * triangle). A time before the origin or after 30 h is not drawn ("Listed but not drawn"). The clock line is the lane's ::before. */
export function Lane({ r }: { r: Report }) {
  const est = onClock(r.estimate_minutes) ? r.estimate_minutes : null, rep = onClock(r.reported_minutes) ? r.reported_minutes : null;
  return <div className="story-lane"><svg width="100%" height={14} aria-hidden="true">
    <line className="story-lane__base" x1="0" x2="100%" y1={7} y2={7}/>
    {est !== null && rep !== null && <line className="story-lane__join" x1={pct(est)} x2={pct(rep)} y1={7} y2={7}/>}
    {est !== null && <svg x={pct(est)} y={7} overflow="visible">
      <path className="story-report story-report--estimate story-report--on" d="M-5 -4H5L0 4Z" fill="none"/></svg>}
    {rep !== null && <svg x={pct(rep)} y={7} overflow="visible"><ReportMark kind={markKind(r)} minutes={rep} x={0} y={0} on/></svg>}
  </svg></div>;
}
/** The clock bar's hours under a set of lanes. */
export const HourTicks = () => <svg className="story-lane__ticks" width="100%" height={12} aria-hidden="true">
  {HOUR_TICKS.map(h => <text key={h} x={pct(h * 60)} y={10} textAnchor={h === 0 ? "start" : h === T_MAX ? "end" : "middle"}>{h} h</text>)}</svg>;

const words = (r: Report) => r.source === "ncei"
  ? `Reported by NCEI: ${nceiTime(r.reported_minutes!)}${r.source_flags.includes("doubtful") ? " · NCEI marks it doubtful" : ""}`
  : `NTWC: ${r.reported_minus_estimate_minutes === null ? ntwcTimes(r) : differenceWords(r.reported_minus_estimate_minutes)}`;
type ClockStation = { id: string; name: string; tag?: "A" | "B" };
/** The three clocks (published estimate, reported time, the story clock) for each station: the reports at places linked to it, one lane
 * each, NTWC and NCEI never joined. A tag (Compare) names the station; the distance is its first linked place's. Hook-free. */
export function ThreeClocks({ arrivals, t, stations }: { arrivals: StoryArrivals; t: number; stations: ClockStation[] }) {
  const linked = stations.map(s => linkedReports(arrivals, s.id));
  return <div className="story-clocks" style={clockAt(t)}>
    {stations.map((s, i) => { const at = linked[i][0]?.place;
      return <div key={s.id} role="group" aria-label={`Reported times linked to ${s.name}`}>
        {(s.tag || at) && <p className="story-clocks__who">{s.tag && <><span className={`story-tag story-tag--${s.tag.toLowerCase()}`}>{s.tag}</span>
          <b>{s.name}</b></>}{at && `${s.tag ? " · " : ""}${distance(at.distance_km)}`}</p>}
        {linked[i].length ? linked[i].map(({ report, place }) => <div key={report.report_id}><Lane r={report}/>
          <p>{`${[words(report), place.record?.link === "within_1km" && WITHIN_1KM].filter(Boolean).join(" · ")}.`
            + notDrawn(report).map(n => ` ${n}`).join("")}</p>
        </div>) : <p>No reported times are linked to this station.</p>}
      </div>; })}
    {linked.some(rows => rows.length > 0) && <HourTicks/>}
  </div>;
}
