import type { EventEntry } from "../types";
import { linkedReports, type StoryArrivals } from "./arrivals";
import { nceiTime, utcDate } from "./clock";

/** The event steps 1–7 are authored for (Tōhoku 2011). Step 8 is Illapel 2015; steps 0 and 9 are All events. Any other event opens in free exploration. */
export const STORY_EVENT_ID = "official20110311054624120_30";
const ILLAPEL = "us20003k7a", HILO = "1617760";
/** The ten guided steps, as data, in order: an id is its place in STEPS, and the reader sees position id + 1 ("1 of 10"). Ids 1–6 keep their old links.
 * Copy: STORYBOARD "Copy draft v2" and "Copy sweep v2" (2026-11-14). */
export type StepId = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;
type LensTarget = { station: string } | { point: "epicentre" } | { point: "between-10-11" };
/** What a step's copy may read: the listed events, the open event's entry and its verified, permitted reported-times file (shownArrivals). */
export type StepData = { events: readonly EventEntry[]; entry: EventEntry; arrivals: StoryArrivals | null };
/** Station A is the lens station (when the lens targets one); B is pinned only for Compare steps. A body read from the bundles is a function.
 * `event` null: any event (step 9 keeps the selection). On All events (`view: "events"`) there is no clock or lens: t and lens are unused there. */
export type StoryStep = {
  id: StepId; title: string; body: string | ((d: StepData, step: StoryStep) => string);
  event: string | null; view: "events" | "story" | "times"; sort?: "time";
  t: number; play: [number, number] | null; lens: LensTarget;
  compare: boolean; b: string | null;
};
/** A sentence read from the bundles goes after the fixed copy; a value that is not there leaves it out, never a placeholder. */
const and = (fixed: string, line: string | null) => line ? `${fixed} ${line}` : fixed;
/** The first NCEI report at a place linked to the station (only by `link`, if given), with its place. */
const nceiAt = (a: StoryArrivals | null, station: string, link?: "within_1km") =>
  a && linkedReports(a, station).find(({ report, place }) => report.source === "ncei" && (!link || place.record!.link === link)) || null;
const km = (d: number) => `${Math.round(d).toLocaleString("en-US")} km`;
const sum = (events: readonly EventEntry[], key: "ntwc_pairs" | "ntwc_pairs_with_position") => events.reduce((n, e) => n + e.counts![key], 0);
const year = (e: EventEntry) => e.origin_time_utc.slice(0, 4);
const hhmm = (iso: string) => `${iso.slice(11, 16)} UTC`;
const TOHOKU = { event: STORY_EVENT_ID, view: "story", play: null, compare: false, b: null } as const;
const EVENTS = { view: "events", t: 0, play: null, lens: { point: "epicentre" }, compare: false, b: null } as const;

export const STEPS: readonly StoryStep[] = [
  { id: 0, title: "Many earthquakes, one question", ...EVENTS, event: STORY_EVENT_ID,
    // The index lists events by origin instant (validateIndex), so the first and last give the years; schema 2 gives every entry its counts.
    body: ({ events }) => `Each star is one of ${events.length} Pacific earthquakes from ${year(events[0])} to ${year(events.at(-1)!)}. For each, the archives list an `
      + "NTWC published estimate of a time at a coastal place, a reported time there, or both. Across these earthquakes, "
      + `${sum(events, "ntwc_pairs")} NTWC table rows have both times, and ${sum(events, "ntwc_pairs_with_position")} of them have a reviewed position and are drawn. `
      + "Where both exist, the app shows how many minutes they differ by. The story starts with one earthquake." },
  { id: 1, title: "05:46 UTC, 11 March 2011", ...TOHOKU, t: 0, lens: { point: "epicentre" },
    body: "A magnitude 9.1 earthquake ruptures the seafloor off Tōhoku, Japan (USGS). Every time in this story counts from this moment." },
  { id: 2, title: "The published clock", ...TOHOKU, t: 8, play: [0, 8], lens: { point: "epicentre" },
    body: "NOAA/NCEI's travel-time map draws one line for each hour after the earthquake, calculated from ocean depth. It is a published model estimate of travel time for the first wave only, with no wave height." },
  { id: 3, title: "A deep-ocean record", ...TOHOKU, t: 1, lens: { station: "21418" },
    body: "DART 21418 sits on the deep seafloor east of Japan and records the water column above it. Its record is shown as measured, point by point. No time is picked from this record." },
  { id: 4, title: "Hilo, seven and a half hours on", ...TOHOKU, t: 7.5, lens: { station: HILO },
    body: (d, s) => { const hilo = nceiAt(d.arrivals, HILO, "within_1km"), m = hilo?.report.reported_minutes;
      // The line says the clock has not reached that time at this step: it is left out if the file ever says otherwise.
      return and("Hilo's tide gauge records raw water level, tide included, on its own vertical scale. The white line marks the story clock on its record; it is a time on the clock, not a reported time.",
        m != null && m > s.t * 60 ? `NCEI reports a time for Hilo of ${nceiTime(m)}. The clock has not reached it yet.` : null); } },
  { id: 5, title: "When the record goes quiet", ...TOHOKU, t: 7.5, lens: { station: HILO }, compare: true, b: "saip",
    body: (d, s) => { const saipan = nceiAt(d.arrivals, s.b!), hilo = nceiAt(d.arrivals, HILO);
      return and("Saipan's record has gaps, stretches with no samples at all. A gap is a missing sample, not a zero. Hilo and Saipan use different instruments and datums, so their heights are not compared.",
        saipan && hilo ? `Each strip carries its own place's NCEI reported time: Saipan, ${km(saipan.place.distance_km)} in a straight line from the epicentre, at `
          + `${nceiTime(saipan.report.reported_minutes!)}; Hilo, ${km(hilo.place.distance_km)}, at ${nceiTime(hilo.report.reported_minutes!)}.` : null); } },
  { id: 6, title: "A contour is a published estimate", ...TOHOKU, t: 12, lens: { point: "between-10-11" },
    body: "Two times are easy to mix up: the published travel time on this map and the time a source reported for a place. Neither is a validated arrival time, and neither is when a warning was issued. The data cannot say which one is off." },
  { id: 7, title: "Tōhoku, station by station", ...TOHOKU, view: "times", sort: "time", t: 30, lens: { point: "epicentre" },
    body: ({ arrivals: a }) => and("One row for each report.", a && `${a.accounting.ntwc_rows_with_both_times} NTWC table rows have both a published estimate and a `
      + `reported time, and the row says how many minutes they differ by, not which one is off; ${a.accounting.ntwc_pairs_with_position} have a reviewed position and `
      + `appear on the map. NCEI's ${a.accounting.ncei_reported_durations} reported times are a separate source, listed with no estimate and never compared with NTWC's.`) },
  { id: 8, title: "The same question, another earthquake", ...TOHOKU, event: ILLAPEL, t: 14.5, lens: { station: HILO },
    // The NTWC row's own times and the exporter's difference; NCEI's Hilo time is never combined with them.
    body: ({ entry, arrivals }, s) => { const lens = s.lens as { station: string };
      const r = arrivals && linkedReports(arrivals, lens.station).map(x => x.report).find(x => x.source === "ntwc" && x.estimate_utc && x.reported_utc
        && x.reported_minus_estimate_minutes !== null), d = r && Math.abs(r.reported_minus_estimate_minutes!);
      return and(`${entry.label} earthquake of ${utcDate(entry.origin_time_utc)} (UTC).`, r ? `At Hilo, NTWC's published estimate was ${hhmm(r.estimate_utc!)} on `
        + `${utcDate(r.estimate_utc!).replace(/ \d+$/, "")} and its reported time ${hhmm(r.reported_utc!)}: they differ by ${d} minute${d === 1 ? "" : "s"}. `
        + "NCEI's reported time for Hilo is a separate source and is not combined with them." : null); } },
  { id: 9, title: "Choose an event", ...EVENTS, event: null,
    body: "Pick any earthquake on the map or in the list. Events with station records open with a record under the lens; events with only reported times show their marks as the clock plays." },
];
/** A step's copy, with the sentences read from the bundles. */
export const stepBody = (step: StoryStep, d: StepData) => typeof step.body === "string" ? step.body : step.body(d, step);
/** A step this event's views open: authored for the event, not on All events (Tōhoku 1–7, Illapel 8). */
export const ownStep = (id: StepId, event: string) => STEPS[id].event === event && STEPS[id].view !== "events";
/** The step whose panel this screen shows: a step in its own view (on All events, with any event selected). Elsewhere it is only carried in the URL. */
export const stepOn = (step: StepId | "explore", event: string, view: string): StoryStep | null => {
  const s = step === "explore" ? null : STEPS[step];
  return s && s.view === view && (s.view === "events" || s.event === event) ? s : null;
};

/** The stations an event's own steps name exist in its records. */
export function validateSteps(stationIds: readonly string[], event = STORY_EVENT_ID): void {
  for (const step of STEPS.filter(s => s.event === event)) {
    const named = [step.b, "station" in step.lens ? step.lens.station : null].filter((v): v is string => v !== null);
    for (const id of named) if (!stationIds.includes(id)) throw new Error(`Story step ${step.id + 1} names unknown station ${id}.`);
  }
}
