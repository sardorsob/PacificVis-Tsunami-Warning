import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { layoutFor } from "../layout";
import type { EventsHas, EventsOrder } from "../state";
import type { EventCounts, EventEntry } from "../types";
import { many } from "./ArrivalsView";
import { T_MAX, utcDate } from "./clock";
import { toSvg, type Coastline, type Pt } from "./layers";
import { Lens } from "./Lens";
import { capture, LENS_MAG } from "./lensMath";
import { contourColour } from "./palette";
import { centreOn, fitView, PACIFIC_CROP, pinchView, star, toMap, toScreen, WorldDefs, zoomAt, type KLimits, type View } from "./StoryMap";
import { RepairNote } from "./StoryView";
import { HourTicks } from "./ThreeClocks";
import { Z_MAX, Z_MIN } from "./url";
import { reducedMotion } from "./useStoryClock";
import { EventSelect, eventOption, magnitudeText } from "./ViewSwitch";
import "./style.css";

/** The index's counts in the fixed wording, NTWC and NCEI apart. */
export const countsLine = (c: EventCounts) => [`${many(c.ntwc_pairs, "estimate–reported pair")} in the NTWC table`, `${c.ntwc_pairs_with_position} with a reviewed position`,
  many(c.ntwc_reported, "NTWC reported time"), many(c.ncei_reported, "NCEI reported time"), many(c.stations, "station record")].join(" · ");
/** A row's counts, per source, and whether contours are listed. */
export const shortCounts = ({ counts: c, layers }: EventEntry) => [`NTWC: ${c!.ntwc_reported} reported, ${many(c!.ntwc_pairs, "pair")}`, `NCEI: ${c!.ncei_reported} reported`,
  many(c!.stations, "station record"), ...(layers ? ["published contours"] : [])].join(" · ");
const ORDERS: Record<EventsOrder, string> = { date: "Date", magnitude: "Magnitude", reports: "Number of reported times" };
const FILTERS: Record<EventsHas, [string, (e: EventEntry) => boolean]> = {
  records: ["With station records", e => e.records !== null], contours: ["With published contours", e => e.layers !== null],
  pairs: ["With estimate–reported pairs", e => e.counts!.ntwc_pairs > 0], ncei: ["With NCEI reported times", e => e.counts!.ncei_reported > 0] };
/** Date is the index's order; magnitude and number of reported times (NTWC + NCEI, used only to order, never shown) put the largest first, ties in date order. */
export function sortEvents(events: readonly EventEntry[], order: EventsOrder): EventEntry[] {
  const key = (e: EventEntry) => order === "magnitude" ? e.magnitude : e.counts!.ntwc_reported + e.counts!.ncei_reported;
  return order === "date" ? [...events] : [...events].sort((a, b) => key(b) - key(a));
}
export const shownEvents = (events: readonly EventEntry[], order: EventsOrder, has: EventsHas | null) =>
  sortEvents(events, order).filter(e => !has || FILTERS[has][1](e));
/** The previous or next shown event in the current order, wrapping (from a hidden selection, the first shown one that way); null if no other is shown. */
export function stepEvent(events: readonly EventEntry[], order: EventsOrder, has: EventsHas | null, id: string, d: 1 | -1): EventEntry | null {
  const all = sortEvents(events, order), i = all.findIndex(e => e.event_id === id), n = all.length;
  for (let k = 1; k < n; k++) { const e = all[((i + d * k) % n + n) % n]; if (!has || FILTERS[has][1](e)) return e; }
  return null;
}

const GUIDE = "Bars count reported times by clock hour after the origin; NCEI hours count from NCEI's origin.";
/** reported_per_hour as two rows on one scale, NTWC above NCEI: a bar is one source's count in one clock hour, never added to the other's.
 * `big` (the arm): each row is labelled with its own total, and the clock bar's hour ticks run below. */
export function HourStrip({ perHour, big = false }: { perHour: EventCounts["reported_per_hour"]; big?: boolean }) {
  const max = Math.max(1, ...perHour.ntwc, ...perHour.ncei);
  return <span className={`events-strip${big ? " events-strip--big" : ""}`}>
    {(["ntwc", "ncei"] as const).map(src => { const n = perHour[src].reduce((a, b) => a + b, 0), name = src.toUpperCase();
      const label = `${name}: ${many(n, "reported time")} by clock hour, 0 to ${T_MAX} h${src === "ncei" ? ", counted from NCEI's origin" : ""}`;
      return <span key={src} className="events-strip__row"><span>{name}</span>
        <svg viewBox={`0 0 ${T_MAX} 1`} preserveAspectRatio="none" {...(big ? { role: "img", "aria-label": label } : { "aria-hidden": true })}>
          <line x1={0} x2={T_MAX} y1={1} y2={1} className="events-strip__base"/>
          {perHour[src].map((c, h) => c > 0 && <rect key={h} data-n={c} x={h + 0.12} y={1 - c / max} width={0.76} height={c / max} fill={contourColour(h + 1)}/>)}
        </svg></span>; })}
    {big && <span className="events-strip__row"><span/><HourTicks/></span>}
  </span>;
}

export type EventListProps = {
  events: readonly EventEntry[]; selected: EventEntry; order: EventsOrder; has: EventsHas | null;
  /** A pick is "push"; a lens settling on the nearest epicentre is "replace". */
  onSelect: (id: string, history: "push" | "replace") => void; onOrder: (order: EventsOrder) => void; onHas: (has: EventsHas | null) => void;
};
/** The column: order, filter, how many are shown, Previous/Next and one button per event. Hook-free, so tests walk it. */
export function EventList({ events, selected, order, has, onSelect, onOrder, onHas }: EventListProps) {
  const rows = shownEvents(events, order, has), alone = !rows.some(e => e !== selected);
  const pick = (e: EventEntry | null) => { if (e && e !== selected) onSelect(e.event_id, "push"); };
  const step = (d: 1 | -1) => pick(stepEvent(events, order, has, selected.event_id, d));
  return <>
    <div className="ladder-sort" role="group" aria-label="Order the events"><span className="story-small">Order by</span>
      {(Object.keys(ORDERS) as EventsOrder[]).map(o => <button key={o} type="button" aria-pressed={order === o} onClick={() => { if (o !== order) onOrder(o); }}>
        {ORDERS[o]}</button>)}</div>
    <label className="story-event events-filter"><span>Show</span><select aria-label="Show" value={has ?? ""} onChange={e => onHas((e.target.value || null) as EventsHas | null)}>
      <option value="">All events</option>{(Object.keys(FILTERS) as EventsHas[]).map(k => <option key={k} value={k}>{FILTERS[k][0]}</option>)}</select></label>
    <p className="story-small">{`${rows.length} of ${events.length} events`}</p>
    {!rows.includes(selected) && <p className="story-small">{`The selected event, ${selected.label}, is hidden by this filter.`}</p>}
    <div className="story-sheet__nav"><button type="button" disabled={alone} onClick={() => step(-1)}>‹ Previous event</button>
      <button type="button" disabled={alone} onClick={() => step(1)}>Next event ›</button></div>
    <ol className="events-list">{rows.map(e => <li key={e.event_id}>
      <button type="button" className="events-row" aria-current={e === selected ? "true" : undefined} onClick={() => pick(e)}>
        <span className="events-row__name"><b>{e.label}</b></span><span className="events-row__meta">{`${utcDate(e.origin_time_utc)} · M${magnitudeText(e.magnitude)}`}</span>
        <span className="events-row__counts">{shortCounts(e)}</span><HourStrip perHour={e.counts!.reported_per_hour}/></button></li>)}</ol>
  </>;
}

export type EventsViewProps = EventListProps & {
  basemap: Coastline; issues: string[]; onDismissIssues: () => void; onOpen: () => void;
  /** Bumped on Back/Forward: the lens jumps to the restored event instead of gliding. */
  restoreKey: number;
  /** Test seam: the first-render viewport (the browser measures window size). */
  initialSize?: { w: number; h: number };
};
const NO_CONTOURS: never[] = [], NO_PATHS = new Map<number, string>(), DRAG_SLOP = 3, SETTLE_MS = 250, TAP_PX = 16;
/** All events (?view=events): the story's stage with every listed epicentre. The lens rests on the selected event, the arms show what the index lists
 * for it, the column lists every event. No clock: nothing here may read as one clock shared across events. */
// ponytail: its own small pan, pinch, settle and glide (no clock, no steps, no B); share StoryView's input code if the two drift apart.
export function EventsView(props: EventsViewProps) {
  const { events, selected, onSelect } = props, root = useRef<HTMLElement>(null), svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState(() => props.initialSize ?? (typeof window === "undefined" ? { w: 1440, h: 848 } : { w: window.innerWidth, h: window.innerHeight }));
  const L = layoutFor(size.w, size.h), wide = L.mode === "wide", fitK = fitView(PACIFIC_CROP, size.w, size.h).k, kLimits: KLimits = [fitK * Z_MIN, fitK * Z_MAX];
  // DemoApp opens All events only with the basemap, which only index schema 2 has, and schema 2 gives every event x, y and counts.
  const points = useMemo(() => events.map(e => ({ id: e.event_id, xy: toSvg([e.x!, e.y!]) })), [events]);
  const xyOf = (id: string) => points.find(p => p.id === id)!.xy;
  const [view, setView] = useState<View>(() => centreOn({ k: fitK, tx: 0, ty: 0 }, xyOf(selected.event_id), L.cx, L.cy));
  const viewRef = useRef(view); viewRef.current = view;
  const onto = (id: string) => centreOn(viewRef.current, xyOf(id), L.cx, L.cy);
  const [sheetExpanded, setSheetExpanded] = useState(false);
  useEffect(() => setSheetExpanded(false), [L.mode]);

  // ---- the lens follows the selection: a glide after a pick, a jump after Back/Forward ----
  const anim = useRef(0);
  const cancelGlide = () => { if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(anim.current); };
  const land = (v: View) => { viewRef.current = v; setView(v); };
  const glide = (target: View) => {
    cancelGlide();
    if (reducedMotion() || typeof requestAnimationFrame !== "function" || document.visibilityState === "hidden") return land(target);
    const from = viewRef.current, t0 = performance.now();
    const frame = (now: number) => { const q = Math.min(1, (now - t0) / 420), e = 1 - (1 - q) ** 3;
      land(q < 1 ? { k: from.k + (target.k - from.k) * e, tx: from.tx + (target.tx - from.tx) * e, ty: from.ty + (target.ty - from.ty) * e } : target);
      if (q < 1) anim.current = requestAnimationFrame(frame); };
    anim.current = requestAnimationFrame(frame);
  };
  const restoreSeen = useRef(props.restoreKey);
  useEffect(() => {
    const back = restoreSeen.current !== props.restoreKey; restoreSeen.current = props.restoreKey;
    if (back) { cancelGlide(); land(onto(selected.event_id)); } else glide(onto(selected.event_id));
  }, [selected.event_id, props.restoreKey]);
  // ---- a move ends on the nearest epicentre: a new one is selected in place (replace), as a lens settle is; never written mid-move ----
  const settleTimer = useRef(0);
  const settle = () => {
    window.clearTimeout(settleTimer.current);
    const id = capture(toMap(viewRef.current, L.cx, L.cy), Infinity, points)!;
    setSaid(`${events.find(e => e.event_id === id)!.label} under the lens.`);
    if (id !== selected.event_id) onSelect(id, "replace"); else glide(onto(id));
  };
  /** The polite live region speaks only on a lens settle, as on the story's stage. */
  const [said, setSaid] = useState("");
  const settleRef = useRef(settle); settleRef.current = settle;
  const settleSoon = () => { window.clearTimeout(settleTimer.current); settleTimer.current = window.setTimeout(() => settleRef.current(), SETTLE_MS); };
  /** A tap selects the epicentre under it (push), read through the lens at its magnification; elsewhere the lens returns to the selected one. */
  const tap = ([x, y]: Pt) => {
    const v = viewRef.current, inLens = Math.hypot(x - L.cx, y - L.cy) <= L.r, k = inLens ? v.k * LENS_MAG : v.k, c = toMap(v, L.cx, L.cy);
    const id = capture(inLens ? [c[0] + (x - L.cx) / k, c[1] + (y - L.cy) / k] : toMap(v, x, y), TAP_PX / k, points);
    if (id && id !== selected.event_id) onSelect(id, "push"); else glide(onto(selected.event_id));
  };
  const step = (d: 1 | -1) => { const e = stepEvent(events, props.order, props.has, selected.event_id, d); if (e && e !== selected) onSelect(e.event_id, "push"); };

  // ---- input: one finger or the mouse pans, two fingers pinch; zoom buttons, the wheel and + / − zoom about the lens ----
  const fingers = useRef(new Map<number, Pt>()), drag = useRef<{ x: number; y: number; v: View; moved: boolean } | null>(null);
  const pinch = useRef<{ from: [Pt, Pt]; v: View } | null>(null);
  const local = (e: PointerEvent<SVGSVGElement>): Pt => { const r = e.currentTarget.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const pair = (): [Pt, Pt] => { const [a, b] = fingers.current.values(); return [a, b]; };
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    fingers.current.set(e.pointerId, local(e)); e.currentTarget.setPointerCapture(e.pointerId); cancelGlide(); window.clearTimeout(settleTimer.current);
    if (fingers.current.size === 2) { drag.current = null; pinch.current = { from: pair(), v: viewRef.current }; }
    else if (fingers.current.size === 1) drag.current = { x: e.clientX, y: e.clientY, v: viewRef.current, moved: false };
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!fingers.current.has(e.pointerId)) return;
    fingers.current.set(e.pointerId, local(e));
    const p = pinch.current; if (p) { if (fingers.current.size >= 2) land(pinchView(p.v, p.from, pair(), kLimits)); return; }
    const d = drag.current; if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y; if (Math.hypot(dx, dy) > DRAG_SLOP) d.moved = true;
    if (d.moved) land({ ...d.v, tx: d.v.tx + dx, ty: d.v.ty + dy });
  };
  const onPointerUp = (e: PointerEvent<SVGSVGElement>) => {
    if (!fingers.current.delete(e.pointerId)) return;
    if (pinch.current) { if (!fingers.current.size) { pinch.current = null; settle(); } return; }
    const d = drag.current; drag.current = null;
    if (d?.moved) settle(); else if (d) tap(local(e));
  };
  const zoom = (f: number) => { cancelGlide(); land(zoomAt(viewRef.current, L.cx, L.cy, f, kLimits)); };
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const pan: Record<string, Pt> = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] }, by = pan[e.key];
    if (by) { e.preventDefault(); cancelGlide(); const v = viewRef.current; land({ ...v, tx: v.tx + by[0], ty: v.ty + by[1] }); settleSoon(); }
    else if (e.key === "[" || e.key === "]") step(e.key === "]" ? 1 : -1);
    else if (e.key === "+" || e.key === "=" || e.key === "-") { e.preventDefault(); zoom(e.key === "-" ? 1 / 1.25 : 1.25); }
  };
  const zoomRef = useRef(zoom); zoomRef.current = zoom;
  useEffect(() => {
    const svg = svgRef.current; if (!svg) return;
    const wheel = (e: WheelEvent) => { e.preventDefault(); zoomRef.current(Math.exp(-e.deltaY * 0.0015)); };
    svg.addEventListener("wheel", wheel, { passive: false }); return () => svg.removeEventListener("wheel", wheel);
  }, []);
  // Measure the real viewport; a resize keeps the lens on the selected epicentre and the zoom relative to the fitted Pacific.
  useEffect(() => {
    const el = root.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height);
      if (w && h) setSize(s => s.w === w && s.h === h ? s : { w, h }); });
    ro.observe(el); return () => ro.disconnect();
  }, []);
  const lastFit = useRef(fitK);
  useEffect(() => {
    const k = viewRef.current.k * fitK / lastFit.current; lastFit.current = fitK; cancelGlide();
    land(centreOn({ k, tx: 0, ty: 0 }, xyOf(selected.event_id), L.cx, L.cy));
  }, [L.cx, L.cy, fitK]);
  useEffect(() => () => { cancelGlide(); window.clearTimeout(settleTimer.current); }, []);
  // Wide: the column's list keeps the selected row in view (the sheets leave the reader's scroll alone).
  useEffect(() => { if (wide) root.current?.querySelector<HTMLElement>('.events-row[aria-current="true"]')?.scrollIntoView?.({ block: "nearest" }); },
    [selected.event_id, props.order, props.has, wide]);

  // ---- display ----
  const centre = toMap(view, L.cx, L.cy), c = selected.counts!;
  const head = <><p className="story-kicker">{`Pacific · ${events[0].origin_time_utc.slice(0, 4)}–${events.at(-1)!.origin_time_utc.slice(0, 4)}`}</p>
    <h1 className="story-title">All events</h1></>;
  const armBox = (box: typeof L.record) => wide ? { ...box, maxHeight: L.armBottom - box.top } : undefined;
  const arms = <>
    <section className="story-arm" style={armBox(L.record)} aria-label="Listed for this earthquake"><h2 className="story-arm__h">Listed for this earthquake</h2>
      <p>{countsLine(c)}</p><p>{selected.layers ? "Published contours listed" : "No published contours listed"}</p></section>
    <section className="story-arm" style={armBox(L.support)} aria-label="Reported times by clock hour"><h2 className="story-arm__h">Reported times by clock hour</h2>
      <HourStrip perHour={c.reported_per_hour} big/><p>{GUIDE}</p></section>
  </>;
  // "Open this event" takes the view switch's place.
  const panel = <section className="story-panel story-compare" style={wide ? { width: L.panel } : undefined} aria-label="Selected event">
    <button type="button" className="events-open" onClick={props.onOpen}>Open this event</button>
    <EventSelect events={events} value={selected.event_id} onEvent={id => onSelect(id, "push")}/></section>;
  const column = <aside className="story-column events-column" aria-label="All events">
    {wide && head}
    <p className="story-small">Each star is one earthquake's epicentre. Choose one on the map or in the list; the lens and its arms show what the sources list for it.</p>
    <RepairNote issues={props.issues} onDismissIssues={props.onDismissIssues}/>
    <EventList events={events} selected={selected} order={props.order} has={props.has} onSelect={onSelect} onOrder={props.onOrder} onHas={props.onHas}/>
    <p className="story-credits">Counts: NTWC and NCEI source records, as the events index lists them. Natural Earth 1:110m · Equal Earth, 160° W. Internal descriptive
      evidence only.</p>
  </aside>;
  return <main className={`story story--${L.mode} story--events`} ref={root} style={{ ["--ui" as string]: L.ui }}>
    <svg ref={svgRef} className="story-map" width={size.w} height={size.h} tabIndex={0} role="img"
      aria-label={`Pacific map with ${events.length} earthquake epicentres; the lens is on ${eventOption(selected)}. `
        + "Drag or use arrow keys to move the map under the lens; + and − zoom; [ and ] step through the list."}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onKeyDown={onKeyDown}>
      <WorldDefs coastline={props.basemap} contours={NO_CONTOURS} paths={NO_PATHS} initialT={0}/>
      <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}><use href="#story-world"/></g>
      <g className="story-overlay" aria-hidden="true">{points.map(p => { const [x, y] = toScreen(view, p.xy);
        return <path key={p.id} d={star(x, y, 6, 2.5)} className="story-epicentre events-star"/>; })}</g>
      {wide && <g className="story-leads" aria-hidden="true"><line x1={L.cx - L.r} y1={L.cy} x2={L.record.left + L.aw} y2={L.cy - L.r + 6}/>
        <line x1={L.cx + L.r} y1={L.cy} x2={L.support.left} y2={L.cy - L.r + 6}/></g>}
      <Lens id="story-lens-a" view={view} cx={L.cx} cy={L.cy} centre={centre} r={L.r} mag={LENS_MAG} stations={[]} epicentre={xyOf(selected.event_id)} variant="a"
        others={points.filter(p => p.id !== selected.event_id).map(p => p.xy)}/>
    </svg>
    <div className="story-zoom" role="group" aria-label="Map zoom">
      <button type="button" aria-label="Zoom in" onClick={() => zoom(1.25)}>+</button>
      <button type="button" aria-label="Zoom out" onClick={() => zoom(1 / 1.25)}>−</button>
      <button type="button" aria-label="Reset view" onClick={() => glide(centreOn({ k: fitK, tx: 0, ty: 0 }, xyOf(selected.event_id), L.cx, L.cy))}>Reset</button>
    </div>
    <div className="story-lens-title" style={{ left: L.cx, top: L.titleBottom, maxWidth: L.titleW }}>
      <p className="story-lens-title__name">{selected.label}</p>
      <p className="story-lens-title__sub">{`${utcDate(selected.origin_time_utc)} · M${magnitudeText(selected.magnitude)}`}</p></div>
    {wide ? <>{arms}{column}{panel}</>
      : <div className={`story-sheet story-sheet--${L.mode}${sheetExpanded ? " story-sheet--expanded" : ""}`} style={L.sheet ?? undefined}>
        <div className="story-sheet__top"><div className="story-sheet__head">{head}</div>
          <button type="button" className="story-sheet__handle" aria-expanded={sheetExpanded} onClick={() => setSheetExpanded(x => !x)}>
            {sheetExpanded ? "Collapse panel" : "Expand panel"}</button></div>
        {arms}{panel}{column}
      </div>}
    <p className="story-sr" aria-live="polite">{said}</p>
  </main>;
}
