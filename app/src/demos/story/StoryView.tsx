import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { centreArm, layoutFor } from "../layout";
import type { AnySelection, AnyStation, DemoState, EventEntry, ViewProps } from "../types";
import { NoReference, StationCard } from "../StationCard";
import { recordProviders } from "../slices";
import { arrivalDisplay, shownArrivals, type StoryArrivals } from "./arrivals";
import { Arms, CAVEAT, kindLabel } from "./Arms";
import { ClockBar } from "./ClockBar";
import { ClockColumn, ColumnHead, hourlySamples } from "./ClockColumn";
import { clockLabel, utcAt } from "./clock";
import { nearestHours, pointBetween, type Coastline, type Pt, type StoryLayers } from "./layers";
import { B_LENS_MAG, capture, LENS_MAG } from "./lensMath";
import { Lens } from "./Lens";
import { distinct, historyPrev, reduce, stepFocus, type NavEvent, type NavResult, type StoryNav } from "./nav";
import { ownStep, STEPS, STORY_EVENT_ID, stepBody, stepOn, validateSteps, type StepId, type StoryStep } from "./steps";
import { centreOn, clampK, fitView, originLabel, Overlay, PACIFIC_CROP, pinchView, placeName, toMap, toScreen, useStage, WorldDefs, zoomAt } from "./StoryMap";
import type { KLimits, MapStation, View } from "./StoryMap";
import { Z_MAX, Z_MIN, type StoryParams } from "./url";
import { reducedMotion, useStoryClock } from "./useStoryClock";
import { StationTools } from "./StationTools";
import { ThreeClocks } from "./ThreeClocks";
import { EventSelect, magnitudeText, ViewSwitch } from "./ViewSwitch";
import "./style.css";

export type StoryViewProps = ViewProps & {
  layers: StoryLayers | null; layersError: string | null; layersPending: "loading" | "retrying" | null; onRetryLayers: () => void;
  /** The index's verified 1:110m basemap: the coastline when no layers bundle has loaded. */
  basemap?: Coastline | null;
  /** The verified reported-times file, "rejected" (the event shows without its marks), undefined while it loads, or null when the event has none. */
  arrivals?: StoryArrivals | "rejected" | null;
  /** URL story fields; with state.selectedStationId (A) and state.pinnedStationId (B) they are the whole screen. */
  params: StoryParams;
  /** The single history writer (DemoApp). */
  onNav: (result: NavResult) => void;
  /** Bumped on browser Back/Forward: restore without writing history. */
  restoreKey: number;
  evidenceOpen: boolean; issues: string[]; onDismissIssues: () => void;
  /** A view-level change from the live screen (view switch); DemoApp keeps this moment in the entry being left. */
  onState: (patch: Partial<DemoState>, live: StoryNav) => void;
  /** The open event's index entry (label, origin, magnitude, listed bundles) and every listed event, for the event select. */
  entry: EventEntry; events: readonly EventEntry[];
  /** An event change from the live screen (DemoApp keeps this moment in the entry being left, then pushes the new event). */
  onEvent: (eventId: string, live: StoryNav) => void;
  /** The All events button beside the event select: DemoApp keeps this moment in the entry being left, then pushes All events for this event. */
  onAllEvents: (live: StoryNav) => void;
  /** Test seam: the first-render viewport (the browser measures window size). */
  initialSize?: { w: number; h: number };
};
/** The lens subject: the nearest station within 400 km of the lens centre at zoom 1 (shrinking as you zoom in). It is set
 * in map units, not by the lens's on-screen footprint, so a URL names the same subject on a phone and on a desktop. */
const CAPTURE_M = 400_000, READING_RADIUS = 450_000, DRAG_SLOP = 3, SETTLE_MS = 250;
/** After React commits (a timeout, not an animation frame, so a hidden tab still gets it). */
const afterCommit = (f: () => void) => { if (typeof window !== "undefined") window.setTimeout(f, 0); };
/** Focus the element after React commits (the page views and All events, where no view-local root is at hand). */
export const focusSoon = (selector: string) => afterCommit(() => document.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true }));
type StepAction = "back" | "next" | "returnToStep" | "explore";
/** A guided step's panel, in every view that has steps: its position ("1 of 10"), title and body, Back (inert on the first step), Next (none on the last:
 * the reader picks an event there), Return to this step where the view has it, and Skip. Hook-free; the heading takes focus as it mounts when its step
 * was entered across a remount (stepFocus). */
export function StepPanel({ step, body, onNav, canReturn = true, children }: { step: StoryStep; body: string; onNav: (type: StepAction) => void;
  canReturn?: boolean; children?: ReactNode }) {
  const n = step.id + 1;
  return <section className="story-step" aria-label={`Story step ${n} of ${STEPS.length}`}>
    <p className="story-kicker">{n} of {STEPS.length}</p>
    <h2 className="story-step__title" id="story-step-title" tabIndex={-1}
      ref={el => { if (el && stepFocus.step === step.id) { stepFocus.step = null; el.focus({ preventScroll: true }); } }}>{step.title}</h2>
    <p className="story-step__body">{body}</p>
    {children}
    <div className="story-step__nav"><button type="button" aria-disabled={step.id === 0} onClick={() => onNav("back")}>Back</button>
      {step.id < STEPS.length - 1 && <button type="button" onClick={() => onNav("next")}>Next</button>}</div>
    <p className="story-step__links">
      {canReturn && <><button type="button" className="story-link" onClick={() => onNav("returnToStep")}>Return to this step</button>{" "}</>}
      <button type="button" className="story-link" onClick={() => onNav("explore")}>Skip to free exploration</button></p>
  </section>;
}
/** "Back to the guided story (step n)", numbered by position like the step panel; it takes focus after Skip. */
export const ResumeLink = ({ step, onResume }: { step: StepId; onResume: () => void }) => <p className="story-step__links">
  <button type="button" className="story-link story-focus-panel" onClick={onResume}>Back to the guided story (step {step + 1})</button></p>;

export function StoryView(props: StoryViewProps) {
  const { manifest, geometry, layers, state, selected, params } = props;
  /** Station lens (?view=radial): the same stage, the lens always on a station, full A/B cards and station tools, no guided steps. */
  const lens = state.view === "radial";
  // Steps belong to the open event (its records manifest names it).
  const origin = manifest.event.origin_time_utc, eventId = manifest.event.event_id, { entry } = props;
  /** Contours listed for the event; the clock waits for them only then (loading or failed: off, with Retry). */
  const listed = !!entry.layers, clockOff = listed && !layers;
  const root = useRef<HTMLElement>(null), svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState(() => props.initialSize
    ?? (typeof window === "undefined" ? { w: 1440, h: 848 } : { w: window.innerWidth, h: window.innerHeight }));
  const L = layoutFor(size.w, size.h, lens ? 420 : 330), motionOK = !reducedMotion();
  const { stationIds, stations, epicentre, coastline, contours, paths, anchors } = useStage(manifest, geometry, layers, props.basemap, props.entry);
  const between = useMemo(() => { const a = anchors.get(10); return a ? pointBetween(contours, a, 11) : null; }, [anchors, contours]);
  const reported = useMemo(() => props.arrivals && props.arrivals !== "rejected" ? arrivalDisplay(props.arrivals) : props.arrivals ?? null, [props.arrivals]);
  /** Steps belong to their event (Tōhoku 1–7, Illapel 8); an event without steps has nothing to check. */
  const stepsError = useMemo(() => {
    try { validateSteps(stationIds, eventId); return null; } catch (e) { return e instanceof Error ? e.message : "Story steps are invalid."; }
  }, [stationIds, eventId]);

  // ---- navigation: one reducer, one writer ----
  const nav: StoryNav = { ...params, a: state.selectedStationId, b: state.pinnedStationId };
  const navRef = useRef(nav); navRef.current = nav;
  /** The step shown here: this event's step on the Story view. Another view's step (7, carried in from Reported times) only offers the way back to it. */
  const stepNow = lens ? null : stepOn(params.step, eventId, "story");
  const fitK = fitView(PACIFIC_CROP, size.w, size.h).k;
  const stepTarget = ({ lens }: StoryStep): Pt | null => "station" in lens ? stations.find(x => x.id === lens.station)?.xy ?? null
    : lens.point === "epicentre" ? epicentre : between ?? epicentre;
  /** The step whose lens target applies: the current step, or in Explore the step it was entered from. */
  const own = (id: StepId | null) => id !== null && ownStep(id, eventId) ? id : null;
  const lensStep = (n: StoryNav) => { const id = lens ? null : own(typeof n.step === "number" ? n.step : n.from); return id === null ? null : STEPS[id]; };
  const targetOf = (n: StoryNav): Pt => {
    if (lens) return stations.find(s => s.id === n.a)?.xy ?? epicentre; // Station lens: always on A, whatever the story's lens point
    if (n.at) return [n.at[0] * 1000, n.at[1] * 1000];
    const step = lensStep(n);
    return (step ? stepTarget(step) : null) ?? stations.find(s => s.id === n.a)?.xy ?? epicentre;
  };
  const kLimits: KLimits = [fitK * Z_MIN, fitK * Z_MAX];
  const viewFor = (n: StoryNav): View => centreOn({ k: clampK(fitK * n.z, kLimits), tx: 0, ty: 0 }, targetOf(n), L.cx, L.cy);
  const [view, setView] = useState<View>(() => viewFor(nav));
  const viewRef = useRef(view); viewRef.current = view;
  const [sheetExpanded, setSheetExpanded] = useState(false);
  useEffect(() => setSheetExpanded(false), [L.mode]);
  /** Polite announcements: lens settle, pause and the one-hour step. A step change moves focus to its heading instead. */
  const [said, setSaid] = useState("");
  const clock = useStoryClock({ initialT: params.t, svgRef, paths, motionOK, onCommit: (kind, t) => dispatch({ type: kind, t }),
    onPause: t => setSaid(`Clock paused at ${clockLabel(t)}.`) });
  const anim = useRef(0), userMoved = useRef(false), settleTimer = useRef(0), moving = useRef(false);
  /** Cancel a pending settle; settleTimer is 0 exactly when none is pending. */
  const dropSettle = () => { window.clearTimeout(settleTimer.current); settleTimer.current = 0; };
  /** The glide in flight; `settleAs` is set when it ends in a lens settle (true = explicit push). */
  const pending = useRef<{ target: View; settleAs?: boolean } | null>(null);
  /** An explicit pick (push) cut short by a drag, pinch, wheel or key still owes its push to the next settle. */
  const owedPush = useRef(false);
  const cancelGlide = () => {
    if (pending.current?.settleAs) owedPush.current = true;
    moving.current = false; pending.current = null; if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(anim.current);
  };
  /** Land on `v` now; viewRef is updated first so a settle in the same tick reads the landed view. */
  const land = (v: View, settleAs?: boolean) => { viewRef.current = v; setView(v); if (settleAs !== undefined) settle(settleAs); };
  const glide = (target: View, settleAs?: boolean) => {
    cancelGlide();
    // A hidden tab pauses animation frames: land at once rather than leave the lens stranded mid-glide.
    if (!motionOK || typeof requestAnimationFrame !== "function" || document.visibilityState === "hidden") return land(target, settleAs);
    const from = viewRef.current, t0 = performance.now(); moving.current = true; pending.current = { target, settleAs };
    const step = (now: number) => { const p = Math.min(1, (now - t0) / 420), e = 1 - (1 - p) ** 3;
      if (p >= 1) { moving.current = false; pending.current = null; land(target, settleAs); return; }
      setView({ k: from.k + (target.k - from.k) * e, tx: from.tx + (target.tx - from.tx) * e, ty: from.ty + (target.ty - from.ty) * e });
      anim.current = requestAnimationFrame(step); };
    anim.current = requestAnimationFrame(step);
  };
  const run = (r: NavResult) => {
    for (const e of r.effects) {
      if (e.kind === "stopPlay") clock.stop(false);
      else if (e.kind === "play") clock.play(e.from, e.until);
      else if (e.kind === "aim") {
        dropSettle(); // a zoom settling now would overwrite the new step's entry
        userMoved.current = false;
        const v = viewFor(r.nav); if (e.instant) { cancelGlide(); setView(v); } else glide(v);
        owedPush.current = false; // the new step's entry is already written
      }
      else if (e.kind === "focus") {
        const selector = e.target === "step" ? "#story-step-title" : ".story-focus-panel";
        afterCommit(() => root.current?.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true }));
      }
      else if (e.kind === "collapseSheet") setSheetExpanded(false);
    }
    if (r.history !== "back" && !r.effects.some(e => e.kind === "play") && r.nav.t !== clock.tRef.current) clock.set(r.nav.t);
  };
  const ctx = () => ({ motionOK: motionOK && !clockOff, stationIds, prevEntryStep: historyPrev(), evidenceOpen: props.evidenceOpen, playing: clock.playing,
    sheetExpanded });
  // The URL's t is written only when play ends or pauses, so every action starts from the live clock: otherwise a no-op
  // (Escape over the evidence dialog) or Compare during play would rewind the clock to the last committed time.
  const live = (): StoryNav => ({ ...navRef.current, t: clock.tRef.current });
  const dispatch = (ev: NavEvent) => { const r = reduce(live(), ev, ctx()); run(r); navRef.current = r.nav; props.onNav(r); };

  // Browser Back/Forward: the URL is already restored by DemoApp; move lens and clock to it without writing history.
  const restoreSeen = useRef(props.restoreKey);
  useEffect(() => {
    if (props.restoreKey === restoreSeen.current) return;
    restoreSeen.current = props.restoreKey; run(reduce(nav, { type: "popstate", nav }, ctx()));
  }, [props.restoreKey]);
  // Geometry or contours can arrive after the first render: aim once each, unless the reader has moved the map.
  const placed = useRef(stations.length > 0);
  useEffect(() => { if (!placed.current && stations.length) { placed.current = true; setView(viewFor(navRef.current)); } }, [stations.length]);
  useEffect(() => {
    const lens = lensStep(navRef.current)?.lens, aimsBetween = !!lens && "point" in lens && lens.point === "between-10-11";
    if (between && aimsBetween && !userMoved.current && !navRef.current.at) setView(viewFor(navRef.current));
  }, [between]);

  const centre = toMap(view, L.cx, L.cy);
  const reach = (v: View) => CAPTURE_M * Math.min(1, fitK / v.k); // zoomed out, the capture never grows past 400 km
  const lensStation = stations.length ? capture(centre, reach(view), stations) : null;
  // The station under the lens drives the panels; while the map moves the URL is untouched, at rest it is corrected in place.
  // Only a lens move triggers this: after Back/Forward the URL changes first and the view follows a render later, so
  // reacting to selectedStationId would rewrite the restored entry with the old lens station.
  // A glide passing over stations is not a choice (it settles at its target), and dragging across B never re-picks B.
  useEffect(() => {
    if (!lensStation || lensStation === state.selectedStationId || pending.current) return;
    if (moving.current) { if (lensStation !== state.pinnedStationId) props.onNav({ nav: { ...live(), a: lensStation }, history: "none", effects: [] }); }
    else props.onNav({ nav: distinct({ ...live(), a: lensStation }, stationIds), history: "replace", effects: [] });
  }, [lensStation]);
  const settle = (explicit = false) => {
    dropSettle();
    const v = viewRef.current, c = toMap(v, L.cx, L.cy);
    const station = stations.length ? capture(c, reach(v), stations) : null;
    // Station lens rests centred on a station: a move that ends off one glides on to it (the nearest, over open ocean), then settles.
    if (lens && stations.length) {
      const id = station ?? capture(c, Infinity, stations)!, s = stations.find(x => x.id === id)!;
      if (Math.hypot(s.xy[0] - c[0], s.xy[1] - c[1]) * v.k > 1) return focusStation(id, explicit);
    }
    setSaid(`${stations.find(s => s.id === station)?.name ?? "Open Pacific"} under the lens.`);
    const at: Pt = [Math.round(c[0] / 1000), Math.round(c[1] / 1000)], z = Math.round((v.k / fitK) * 100) / 100;
    const push = explicit || owedPush.current; owedPush.current = false;
    dispatch({ type: "lensSettle", at, z, station, explicit: push });
  };
  // Handlers bound once (wheel) and timers (settle) go through refs, so they always read the current layout and zoom.
  const settleRef = useRef(settle); settleRef.current = settle;
  const settleSoon = () => {
    dropSettle(); settleTimer.current = window.setTimeout(() => { settleTimer.current = 0; settleRef.current(); }, SETTLE_MS);
  };
  /** Leave for another view from exactly what is on screen: land a glide, settle a pending move, then hand over the live moment. */
  const handOver = () => { const g = pending.current; if (g) { cancelGlide(); land(g.target, g.settleAs); } if (settleTimer.current) settle(); };
  const switchView = (view: DemoState["view"]) => { handOver(); props.onState({ view }, live()); };
  const switchEvent = (id: string) => { handOver(); props.onEvent(id, live()); };
  const events = <EventSelect events={props.events} value={props.entry.event_id} onEvent={switchEvent} onAll={() => { handOver(); props.onAllEvents(live()); }}/>;
  const focusStation = (id: string, explicit = false) => {
    const s = stations.find(x => x.id === id); if (s) glide(centreOn(viewRef.current, s.xy, L.cx, L.cy), explicit);
  };
  const cycle = (d: 1 | -1) => {
    if (!stations.length) return;
    const i = Math.max(0, stations.findIndex(s => s.id === (lensStation ?? state.selectedStationId)));
    focusStation(stations[(i + d + stations.length) % stations.length].id);
  };
  const away = (p: Pt) => Math.hypot(p[0] - centre[0], p[1] - centre[1]);
  const atOrigin = !lensStation && away(epicentre) < reach(view);
  const reading = useMemo(() => lensStation || atOrigin ? null : nearestHours(contours, centre[0], centre[1], READING_RADIUS),
    [lensStation, atOrigin, contours, centre[0], centre[1]]);
  const nearest = useMemo(() => stations.reduce<MapStation | null>((best, s) => !best || away(s.xy) < away(best.xy) ? s : best, null),
    [stations, centre[0], centre[1]]);

  // ---- input: one finger or the mouse pans, two fingers pinch; a finger left after a pinch never re-bases the pan ----
  const fingers = useRef(new Map<number, Pt>());
  /** `g`: the glide this press interrupted; a tap without a drag lands it, so the screen matches the entry just written. */
  const drag = useRef<{ x: number; y: number; v: View; moved: boolean; g: typeof pending.current } | null>(null);
  const pinch = useRef<{ from: [Pt, Pt]; v: View } | null>(null);
  const local = (e: PointerEvent<SVGSVGElement>): Pt => {
    const r = e.currentTarget.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top];
  };
  const pair = (): [Pt, Pt] => { const [a, b] = fingers.current.values(); return [a, b]; };
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    fingers.current.set(e.pointerId, local(e)); e.currentTarget.setPointerCapture(e.pointerId);
    const g = pending.current; cancelGlide(); clock.stop(); moving.current = true;
    if (fingers.current.size === 2) { drag.current = null; pinch.current = { from: pair(), v: viewRef.current }; }
    else if (fingers.current.size === 1) drag.current = { x: e.clientX, y: e.clientY, v: viewRef.current, moved: false, g };
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!fingers.current.has(e.pointerId)) return;
    fingers.current.set(e.pointerId, local(e));
    const p = pinch.current; if (p) { if (fingers.current.size >= 2) setView(pinchView(p.v, p.from, pair(), kLimits)); return; }
    const d = drag.current; if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y; if (Math.hypot(dx, dy) > DRAG_SLOP) d.moved = true;
    if (d.moved) setView({ ...d.v, tx: d.v.tx + dx, ty: d.v.ty + dy });
  };
  const onPointerUp = (e: PointerEvent<SVGSVGElement>) => {
    if (!fingers.current.delete(e.pointerId)) return;
    if (pinch.current) {
      if (fingers.current.size === 0) { pinch.current = null; moving.current = false; userMoved.current = true; settle(); }
      return;
    }
    const d = drag.current; drag.current = null; moving.current = false;
    if (!d?.moved) { if (d?.g) land(d.g.target, d.g.settleAs); return; }
    userMoved.current = true; if (lensStation) focusStation(lensStation); else settle();
  };
  /** Zoom 1 on the step's target, or in Explore on station A; Return to this step also restores the clock. */
  const resetView = () => { userMoved.current = true; glide(viewFor({ ...navRef.current, at: null, z: 1, from: null }), false); };
  const zoom = (factor: number) => { cancelGlide(); userMoved.current = true; setView(v => zoomAt(v, L.cx, L.cy, factor, kLimits)); settleSoon(); };
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const pan: Record<string, [number, number]> = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] };
    const step = pan[e.key];
    if (step) { e.preventDefault(); cancelGlide(); userMoved.current = true; setView(v => ({ ...v, tx: v.tx + step[0], ty: v.ty + step[1] })); settleSoon(); }
    else if (e.key === "[" || e.key === "]") cycle(e.key === "]" ? 1 : -1);
    else if (e.key === "+" || e.key === "=" || e.key === "-") { e.preventDefault(); zoom(e.key === "-" ? 1 / 1.25 : 1.25); }
  };
  const toggleRef = useRef(() => {}), escapeRef = useRef(() => {});
  toggleRef.current = () => { if (clockOff) return; const next = clock.playOrStep(); if (next !== null) setSaid(`Clock ${clockLabel(next)}.`); };
  escapeRef.current = () => dispatch({ type: "escape" });
  useEffect(() => {
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") escapeRef.current();
      else if (e.key === " " && !e.repeat && (e.target === document.body || e.target === svgRef.current)) { e.preventDefault(); toggleRef.current(); }
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, []);
  const wheelRef = useRef((_: WheelEvent) => {});
  wheelRef.current = e => {
    const svg = svgRef.current; if (!svg) return;
    e.preventDefault(); cancelGlide(); userMoved.current = true; const r = svg.getBoundingClientRect();
    setView(v => zoomAt(v, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015), kLimits)); settleSoon();
  };
  useEffect(() => {
    const svg = svgRef.current; if (!svg) return;
    const wheel = (e: WheelEvent) => wheelRef.current(e);
    svg.addEventListener("wheel", wheel, { passive: false }); return () => svg.removeEventListener("wheel", wheel);
  }, [geometry]);
  // Browser Back/Forward: drop a pending settle or slider commit synchronously, before the restored state renders,
  // so neither writes the old screen over the restored entry.
  useEffect(() => {
    const drop = () => { dropSettle(); clock.cancelSeek(); };
    window.addEventListener("popstate", drop); return () => window.removeEventListener("popstate", drop);
  }, []);
  // Leaving the story view (view switch, Back to a Paired entry) must not let a pending settle or glide write history.
  useEffect(() => () => { dropSettle(); cancelGlide(); }, []);
  // Side-arm heights, for centring them on the lens (wide story only): measured after every render, before paint, so a record
  // that finishes loading re-centres its arm without a visible jump. Unchanged heights stop the loop.
  const [armH, setArmH] = useState<[number, number]>([0, 0]);
  useLayoutEffect(() => {
    const el = root.current; if (!el || L.mode !== "wide" || lens) return;
    const [a = 0, b = 0] = [...el.querySelectorAll<HTMLElement>(".story-arm--side")].map(x => x.offsetHeight);
    setArmH(h => h[0] === a && h[1] === b ? h : [a, b]);
  });
  // Measure the real viewport (the first render used the window size).
  useEffect(() => {
    const el = root.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height);
      if (w && h) setSize(s => s.w === w && s.h === h ? s : { w, h });
    });
    ro.observe(el); return () => ro.disconnect();
  }, []);
  // Live resize: keep the map point under the lens and the zoom relative to the fitted Pacific; a glide in flight lands at its target.
  const lastLayout = useRef({ cx: L.cx, cy: L.cy, fitK });
  useEffect(() => {
    const prev = lastLayout.current; lastLayout.current = { cx: L.cx, cy: L.cy, fitK };
    if (prev.cx === L.cx && prev.cy === L.cy && prev.fitK === fitK) return;
    const g = pending.current, v = g?.target ?? viewRef.current; cancelGlide();
    land(centreOn({ ...v, k: v.k * (fitK / prev.fitK) }, toMap(v, prev.cx, prev.cy), L.cx, L.cy), g?.settleAs);
  }, [L.cx, L.cy, fitK]);

  // ---- derived display ----
  const t = clock.t, ocean = lensStation === null;
  const list: readonly AnyStation[] = manifest.stations;
  // No station at all only for an event without a records bundle: the lens is then always over open water.
  const lensMeta = list.find(s => s.station_id === lensStation) ?? selected?.station ?? null;
  const aSel: AnySelection | null = !lensMeta ? null : selected?.station.station_id === lensMeta.station_id ? selected
    : { station: lensMeta, status: "loading", records: null, error: null } as AnySelection;
  const counts = useMemo(() => !ocean && aSel?.records ? hourlySamples(aSel.records, state.windowId, origin) : null,
    [ocean, aSel?.records, state.windowId, origin]);
  const title = atOrigin ? { name: `${placeName(entry.label)} epicentre`, sub: `USGS origin ${origin.slice(11, 19)} UTC · M${magnitudeText(entry.magnitude)}${listed ? " · the published clock starts here" : ""}` }
    : ocean ? { name: "Open Pacific", sub: reading ? `nearest published contours: ${reading.a} h and ${reading.b} h`
      : listed ? "no published contour nearby" : "no published contours for this event" }
    : { name: lensMeta!.name, sub: `${kindLabel(lensMeta!)} · clock ${clockLabel(t)} · ${utcAt(origin, t)}` };
  const b = lens || params.compare ? props.pinned : null;
  // The B mini-lens is the story's Compare; Station lens shows B's full card instead (B stays marked on the map).
  const bStation = !lens && b ? stations.find(s => s.id === b.station.station_id) ?? null : null;
  const bSlot = L.bSlot, bScreen = bStation ? toScreen(view, bStation.xy) : null;
  const bOff = !!bScreen && (bScreen[0] < 0 || bScreen[0] > size.w || bScreen[1] < 0 || bScreen[1] > size.h);
  const within = (v: number, max: number) => Math.max(8, Math.min(max - 8, v));
  const bTarget: Pt | null = bScreen ? [within(bScreen[0], size.w), within(bScreen[1], size.h)] : null;
  const wide = L.mode === "wide", cine = clock.playing && motionOK && wide;

  if (!geometry) return <main className="story story--loading" ref={root}>{props.geometryError
    ? <div role="alert"><p>{props.geometryError}</p><button type="button" onClick={props.onRetryGeometry}>Retry map</button>
      <p className="story-small">The Paired view shows the records without the map.</p><ViewSwitch view={state.view} onView={switchView}/>{events}</div>
    : <p role="status">Loading the verified map…</p>}</main>;
  const alert = <><Notes {...props}/>{stepsError && <div role="alert" className="story-alert"><p>{stepsError}</p></div>}</>;
  // Reduced motion: the step's play becomes a jump to its end, so a link that opens at the start still has a way there.
  const canPlayStep = !!stepNow?.play && !clockOff && !clock.playing && t < stepNow.play[1];
  const lead = stepNow && !stepsError ? <StepPanel step={stepNow} body={stepBody(stepNow, { events: props.events, entry, arrivals: shownArrivals(props.arrivals) })}
    onNav={type => dispatch({ type })}>
    {canPlayStep && (motionOK
      ? <button type="button" className="story-step__play" onClick={() => clock.play(...stepNow.play!)}>▶ Play this step</button>
      : <button type="button" className="story-step__play" onClick={() => clock.seek(stepNow.play![1])}>
        Show this step at {clockLabel(stepNow.play![1]).replace(" 00 min", "")}</button>)}
  </StepPanel> : null;
  // The way back: to a step carried in from another view, else the step Explore was entered from (Tōhoku: step 1 by default).
  const resumeTo = typeof params.step === "number" ? own(params.step) : own(params.from) ?? (eventId === STORY_EVENT_ID ? 1 : null);
  const pick = (id: string) => stations.length ? focusStation(id, id !== lensStation)
    : dispatch({ type: "lensSettle", at: null, z: navRef.current.z, station: id, explicit: true });
  const tools = <StationTools stations={manifest.stations} windows={manifest.windows} selectedStationId={state.selectedStationId}
    pinnedStationId={state.pinnedStationId} windowId={state.windowId} productKey={state.productKey} onSelect={pick}
    onPin={id => dispatch(id ? { type: "pin", id } : { type: "unpin" })} onWindow={windowId => props.onState({ windowId }, live())}
    onProduct={productKey => props.onState({ productKey }, live())}/>;
  const extra = lens ? tools : stepNow ? null : <>
    {resumeTo !== null && <ResumeLink step={resumeTo} onResume={() => dispatch({ type: "resumeStory" })}/>}
    {stations.length > 0 && <StationChips stations={stations} lensStation={lensStation} onPick={id => focusStation(id, id !== lensStation)}/>}
  </>;
  const column = <ClockColumn t={t} entry={entry} stationName={ocean ? null : lensMeta!.name} counts={counts} alert={alert}
    lead={wide ? lead : null} className={wide ? "" : "story-column--sheet"} title={lens ? "Station lens" : undefined} head={wide}
    label={lens ? "Station lens" : "Story"} reported={reported} keyOpen={!lens} providers={recordProviders(manifest)}>{extra}</ClockColumn>;
  const panelWidth = wide ? { width: L.panel } : undefined;
  const compare = lens ? <div className="story-panel story-compare" style={panelWidth}><ViewSwitch view="radial" onView={switchView}/>{events}</div>
    : <section className="story-panel story-compare" style={panelWidth} aria-label="Views and comparison">
    <ViewSwitch view="story" onView={switchView}/>{events}
    {list.length > 0 && <><button type="button" aria-pressed={params.compare} onClick={() => dispatch({ type: params.compare ? "compareOff" : "compareOn" })}>
      {params.compare ? "Close compare ✕" : "⇄ Compare"}</button>
    <label className="story-compare__pick"><span className="story-tag story-tag--b">B</span><span className="story-sr">Pinned station B</span>
      <select value={state.pinnedStationId ?? ""} onChange={e => dispatch({ type: "pin", id: e.target.value })}>
        {state.pinnedStationId === null && <option value="">Choose B…</option>}
        {list.filter(s => s.station_id !== state.selectedStationId || s.station_id === state.pinnedStationId)
          .map(s => <option key={s.station_id} value={s.station_id}>{s.name}</option>)}
      </select></label>
    <p className="story-small">B is pinned while A follows the lens. Both share the UTC axis and the clock; heights stay station-local.</p></>}
  </section>;
  const bar = <ClockBar style={L.bar ?? undefined} t={t} playing={clock.playing} disabled={clockOff} contours={listed} originUtc={origin} reduced={!motionOK}
    onToggle={() => toggleRef.current()} onSeek={clock.seek}/>;
  // Station lens: A's and B's full cards in the side arms (scrolling inside the arm above the clock bar when wide), the caveat below.
  const cursorMs = Date.parse(origin) + t * 3_600_000, armMax = (top: number) => wide ? { maxHeight: L.armBottom - top } : {};
  const card = { windowId: state.windowId, productKey: state.productKey, cursorMs, onOpenEvidence: props.onOpenEvidence, onRetryStation: props.onRetryStation };
  const file = shownArrivals(props.arrivals);
  const clocks = (s: AnySelection) => file && <ThreeClocks arrivals={file} t={t} stations={[{ id: s.station.station_id, name: s.station.name }]}/>;
  const cards = lens && <>
    <div className="story-arm story-arm--card" style={{ ...L.record, ...armMax(L.record.top) }}>
      {/* DemoApp opens Station lens only for an event with records, so A exists */}
      <StationCard selection={selected!} role="selected" {...card} clocks={clocks(selected!)}/></div>
    <div className="story-arm story-arm--card" style={{ ...L.support, ...armMax(L.support.top) }}>
      {props.pinned ? <StationCard selection={props.pinned} role="pinned" {...card} clocks={clocks(props.pinned)}/> : <NoReference/>}</div>
    <section className="story-arm story-arm--read" style={L.read} aria-label="How to read this"><h2 className="story-arm__h">Read this as</h2>
      <p>The white line on each record is the shared clock ({utcAt(origin, t)}); no time is picked from the records.{listed && <> {CAVEAT}</>}</p></section>
  </>;
  // Side arms centred on the lens (wide story): never above the title line, never into the clock bar or the zoom buttons;
  // a taller arm keeps its top and scrolls.
  const armBox = (box: typeof L.record, h: number) => {
    if (!wide) return box;
    const top = h ? centreArm(L.cy, h, box.top, L.armBottom) : box.top;
    return { ...box, top, maxHeight: L.armBottom - top };
  };
  const leadY = (box: typeof L.record, h: number) => { const b = armBox(box, h); return Math.min(Math.max(L.cy, b.top + 14), b.top + Math.max(h, 28) - 14); };
  const arms = lens ? cards : <Arms listed={listed} ocean={ocean} atOrigin={atOrigin} nearestName={nearest?.name ?? null} reading={reading} t={t} originUtc={origin}
    a={aSel} b={b} arrivals={file}
    windowId={state.windowId} productKey={state.productKey} onRetry={id => props.onRetryStation(id)} onOpenEvidence={props.onOpenEvidence}
    styles={{ record: armBox(L.record, armH[0]), support: armBox(L.support, armH[1]), read: L.read }}/>;
  return <main className={`story story--${L.mode}${cine ? " story--cine" : ""}`} ref={root} data-ocean={ocean ? "1" : "0"}
    style={{ ["--ui" as string]: L.ui }}>
    <svg ref={svgRef} className="story-map" width={size.w} height={size.h} tabIndex={0} role="img"
      aria-label={`Pacific map${listed ? " of NOAA/NCEI published hourly travel-time contours" : ""} with ${stations.length ? `${stations.length} station` : "no station"} records. `
        + "Drag or use arrow keys to move the map under the lens; pinch, + and − zoom; [ and ] change station; Space plays the clock."}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onKeyDown={onKeyDown}>
      <WorldDefs coastline={coastline} contours={contours} paths={paths} initialT={t}/>
      <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}><use href="#story-world"/></g>
      <Overlay view={view} stations={stations} epicentre={epicentre} anchors={anchors} t={t} aId={lensStation} width={size.w} height={size.h}
        lenses={[{ cx: L.cx, cy: L.cy, r: L.r }, ...(bStation ? [{ cx: bSlot[0], cy: bSlot[1], r: L.bR }] : [])]}
        avoid={[{ left: L.cx - L.titleW / 2, right: L.cx + L.titleW / 2, top: L.titleBottom - 80 * L.ui, bottom: L.titleBottom }]}
        bId={b?.station.station_id ?? null} marks={reported && reported !== "rejected" ? reported.marks : undefined} origin={originLabel(entry.label, origin)}/>
      <g className="story-leads" aria-hidden="true">
        {wide && <><line x1={L.cx - L.r} y1={L.cy} x2={L.record.left + L.aw} y2={lens ? L.cy - L.r + 6 : leadY(L.record, armH[0])}/>
          <line x1={L.cx + L.r} y1={L.cy} x2={L.support.left} y2={lens ? L.cy - L.r + 6 : leadY(L.support, armH[1])}/>
          <line x1={L.cx} y1={L.cy + L.r} x2={L.cx} y2={Number(L.read.top)}/></>}
        {bTarget && <path className="story-lead-b"
          d={`M${bSlot[0]} ${bSlot[1] - L.bR}Q${(bSlot[0] + bTarget[0]) / 2} ${Math.min(bSlot[1], bTarget[1]) - 60} ${bTarget[0]} ${bTarget[1]}`}/>}
      </g>
      <Lens id="story-lens-a" view={view} cx={L.cx} cy={L.cy} centre={centre} r={L.r} mag={LENS_MAG} stations={stations} epicentre={epicentre}
        variant="a"/>
      {bStation && <Lens id="story-lens-b" view={view} cx={bSlot[0]} cy={bSlot[1]} centre={bStation.xy} r={L.bR} mag={B_LENS_MAG} stations={stations}
        epicentre={epicentre} variant="b" caption={`B · ${bStation.name}${bOff ? " (off-screen)" : ""}`}/>}
    </svg>
    <div className="story-zoom" role="group" aria-label="Map zoom">
      <button type="button" aria-label="Zoom in" onClick={() => zoom(1.25)}>+</button>
      <button type="button" aria-label="Zoom out" onClick={() => zoom(1 / 1.25)}>−</button>
      <button type="button" aria-label="Reset view" onClick={resetView}>Reset</button>
    </div>
    <div className="story-lens-title" style={{ left: L.cx, top: L.titleBottom, maxWidth: L.titleW }}>
      <p className="story-lens-title__name">{title.name}</p><p className="story-lens-title__sub">{title.sub}</p></div>
    {wide ? <>{arms}{column}{compare}{bar}</>
      : <div className={`story-sheet story-sheet--${L.mode}${sheetExpanded ? " story-sheet--expanded" : ""}`} style={L.sheet ?? undefined}>
        <div className="story-sheet__top"><div className="story-sheet__head"><ColumnHead originUtc={origin} title={lens ? "Station lens" : undefined}/></div>
          <button type="button" className="story-sheet__handle" aria-expanded={sheetExpanded} onClick={() => setSheetExpanded(x => !x)}>
            {sheetExpanded ? "Collapse panel" : "Expand panel"}</button></div>
        {lead}
        {!lens && stations.length > 0 && <div className="story-sheet__nav"><button type="button" onClick={() => cycle(-1)}>‹ Previous station</button>
          <button type="button" onClick={() => cycle(1)}>Next station ›</button></div>}
        {lens ? <>{bar}{column}{arms}{compare}</> : <>{bar}{arms}{compare}{column}</>}
      </div>}
    <p className="story-sr" aria-live="polite">{said}</p>
  </main>;
}

type NotesProps = Pick<StoryViewProps, "layersPending" | "layersError" | "onRetryLayers" | "issues" | "onDismissIssues" | "entry">;
/** Layer loading/failure (or, calmly, no contours listed) and URL repair notes, shared by every view. */
export function Notes({ layersPending, layersError, onRetryLayers, issues, onDismissIssues, entry }: NotesProps) {
  return <>
    {!entry.layers && <p className="story-small">No published travel-time contours are listed for this event.</p>}
    {layersPending && <p role="status" className="story-alert">{layersPending === "retrying" ? "Retrying" : "Loading"} the published contour layer…</p>}
    {layersError && <div role="alert" className="story-alert"><p>Published contour layer unavailable: {layersError}</p>
      <button type="button" onClick={onRetryLayers}>Retry contours</button></div>}
    <RepairNote issues={issues} onDismissIssues={onDismissIssues}/>
  </>;
}
/** What a repaired link restored, dismissible (every view and All events). */
export const RepairNote = ({ issues, onDismissIssues }: Pick<NotesProps, "issues" | "onDismissIssues">) => issues.length > 0 &&
  <div role="status" className="story-alert"><p>This link was repaired:</p>
    <ul>{issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
    <button type="button" onClick={onDismissIssues}>Dismiss</button></div>;

type ChipsProps = { stations: MapStation[]; lensStation: string | null; onPick: (id: string) => void };
/** Chips up to 12 stations; beyond that a native select, so the column keeps every control on screen. */
function StationChips({ stations, lensStation, onPick }: ChipsProps) {
  if (stations.length > 12) return <><h2 className="story-h">Station records</h2>
    <label className="story-event"><span>Station</span><select aria-label="Station" value={lensStation ?? ""} onChange={e => { if (e.target.value) onPick(e.target.value); }}>
      {lensStation === null && <option value="">No station under the lens</option>}
      {stations.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label></>;
  return <>
    <h2 className="story-h">Station records</h2>
    {/* Records schema 2 gives no station type: one unheaded list */}
    {(stations.some(s => s.type === "record") ? ["record"] as const : ["dart", "coastal"] as const).map(kind => <div key={kind}>
      {kind !== "record" && <p className="story-small">{kind === "dart" ? "◆ Deep-ocean DART" : "● Coastal gauges"}</p>}
      {stations.filter(s => s.type === kind).map(s => <button key={s.id} type="button"
        className={`story-chip${s.id === lensStation ? " story-chip--on" : ""}`} aria-pressed={s.id === lensStation} onClick={() => onPick(s.id)}>
        {s.name}</button>)}</div>)}
  </>;
}
