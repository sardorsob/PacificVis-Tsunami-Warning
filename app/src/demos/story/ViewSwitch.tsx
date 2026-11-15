import type { DemoState, EventEntry } from "../types";
import { utcDate } from "./clock";

const LABEL: Record<DemoState["view"], string> = { story: "Story", paired: "Paired", radial: "Station lens", times: "Reported times" };
/** The four views; the current one is pressed and inert. */
export function ViewSwitch({ view, onView }: { view: DemoState["view"]; onView: (view: DemoState["view"]) => void }) {
  return <nav className="story-views" aria-label="Views">
    {(Object.keys(LABEL) as DemoState["view"][]).map(v =>
      <button key={v} type="button" aria-pressed={view === v} onClick={() => { if (v !== view) onView(v); }}>{LABEL[v]}</button>)}
  </nav>;
}

/** A magnitude with at least one decimal, the source value never rounded: 7 → "7.0", 8.16 → "8.16". */
export const magnitudeText = (m: number) => Number.isInteger(m) ? m.toFixed(1) : String(m);
/** An event's option: label, full UTC date (labels repeat within a year) and the USGS magnitude, e.g. "Illapel, Chile · 16 September 2015 · M8.3". */
export const eventOption = (e: EventEntry) => `${e.label} · ${utcDate(e.origin_time_utc)} · M${magnitudeText(e.magnitude)}`;
/** Every listed event, in the index's order (by origin instant, validateIndex); the open one is selected. */
export function EventSelect({ events, value, onEvent }: { events: readonly EventEntry[]; value: string; onEvent: (id: string) => void }) {
  return <label className="story-event"><span>Event</span><select aria-label="Event" value={value} onChange={e => { if (e.target.value !== value) onEvent(e.target.value); }}>
    {events.map(e => <option key={e.event_id} value={e.event_id}>{eventOption(e)}</option>)}</select></label>;
}
