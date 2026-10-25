import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { RadialProps } from "../types";
import { Arms } from "./Arms";
import { ClockBar } from "./ClockBar";
import { ClockColumn, hourlySamples } from "./ClockColumn";
import { clockLabel, T_MAX, utcAt } from "./clock";
import { hourPaths, labelAnchors, nearestHours, pointBetween, type Coastline, type Pt, type StoryLayers } from "./layers";
import { B_LENS_MAG, B_LENS_RADIUS, capture, footprintRadius, LENS_MAG, LENS_RADIUS, slot } from "./lensMath";
import { Lens } from "./Lens";
import { reduce, type NavEvent, type NavResult, type StoryNav } from "./nav";
import { STEPS, validateSteps, type StoryStep } from "./steps";
import { centreOn, fitView, Overlay, toMap, toScreen, WorldDefs, zoomAt, type MapStation, type View } from "./StoryMap";
import type { StoryParams } from "./url";
import { useStoryClock } from "./useStoryClock";
import "./style.css";

export type StoryViewProps = RadialProps & {
  layers: StoryLayers | null; layersError: string | null; onRetryLayers: () => void;
  /** URL story fields; with state.selectedStationId (A) and state.pinnedStationId (B) they are the whole screen. */
  params: StoryParams;
  /** The single history writer (DemoApp). */
  onNav: (result: NavResult) => void;
  /** Bumped on browser Back/Forward: restore without writing history. */
  restoreKey: number;
  evidenceOpen: boolean; issues: string[]; onDismissIssues: () => void; onView: (view: "paired" | "radial") => void;
  /** Test seam: the first-render viewport (the browser measures window size). */
  initialSize?: { w: number; h: number };
};
const CROP: [number, number, number, number] = [-6.4e6, -6.3e6, 8.9e6, 4.6e6];
const COLUMN = 300, RIGHT = 270, GAP = 44, READING_RADIUS = 450_000, DRAG_SLOP = 3, SETTLE_MS = 250;
const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
/** After React commits (a timeout, not an animation frame, so a hidden tab still gets it). */
const afterCommit = (f: () => void) => { if (typeof window !== "undefined") window.setTimeout(f, 0); };

type Mode = "wide" | "narrow" | "short";
/** wide: lens + arms + column; narrow (< 768 px): lens in the upper third, bottom sheet; short landscape: lens left, side sheet. */
export function layoutFor(w: number, h: number) {
  const mode: Mode = w < 768 ? "narrow" : h <= 450 ? "short" : "wide";
  if (mode !== "wide") {
    const r = mode === "narrow" ? Math.min(82, w * 0.21) : Math.min(82, h * 0.27);
    const cx = mode === "narrow" ? w / 2 : w * 0.29, cy = mode === "narrow" ? Math.max(r + 64, h * 0.25) : h * 0.56;
    return { mode, cx, cy, r, aw: 0, gap: 0, record: {}, support: {}, read: {}, titleTop: cy - r - 54,
      bSlot: [cx + r + (mode === "narrow" ? 48 : 70), cy + r - 6] as Pt, bR: 38 };
  }
  const cx = COLUMN + (w - COLUMN - RIGHT) / 2, cy = h * 0.4, r = LENS_RADIUS;
  const aw = Math.max(250, Math.min(330, (w - COLUMN - RIGHT) / 2 - r - GAP - 10));
  return { mode, cx, cy, r, aw, gap: GAP,
    record: { left: cx - r - GAP - aw, top: cy - r - 30, width: aw },
    support: { left: cx + r + GAP, top: cy - r - 30, width: aw },
    read: { left: cx - 150, top: cy + r + 30, width: 300 },
    titleTop: cy - r - 76, bSlot: slot(cx, cy, r, GAP, aw, h), bR: B_LENS_RADIUS };
}
const flipped = (parts: number[][][]): Pt[][] => parts.map(part => part.map(([x, y]) => [x, -y] as Pt));
/** The step recorded in the previous history entry (written by DemoApp's story writer), if any. */
function historyPrev(): StoryNav["step"] | null {
  const prev = typeof window === "undefined" ? null : (window.history.state as { prev?: unknown } | null)?.prev;
  return typeof prev === "number" || prev === "explore" ? prev as StoryNav["step"] : null;
}

export function StoryView(props: StoryViewProps) {
  const { manifest, geometry, layers, state, selected, params } = props;
  const origin = manifest.event.origin_time_utc;
  const root = useRef<HTMLElement>(null), svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState(() => props.initialSize ?? (typeof window === "undefined" ? { w: 1440, h: 848 } : { w: window.innerWidth, h: window.innerHeight }));
  const L = layoutFor(size.w, size.h), motionOK = !reducedMotion();
  const stationIds = useMemo(() => manifest.stations.map(s => s.station_id), [manifest]);
  const stations = useMemo<MapStation[]>(() => geometry ? manifest.stations.map(s => {
    const p = geometry.points.find(q => q.id === s.station_id)!; return { id: s.station_id, name: s.name, type: s.station_type, xy: [p.x, -p.y] as Pt };
  }) : [], [geometry, manifest]);
  const epicentre = useMemo<Pt>(() => { const p = geometry?.points.find(q => q.id === manifest.event.event_id); return p ? [p.x, -p.y] : [0, 0]; }, [geometry, manifest]);
  const coastline = useMemo<Coastline>(() => layers?.coastline ?? (geometry ? (() => { const parts = flipped(geometry.coastline);
    return { parts, closed: parts.map(p => p.length > 3 && p[0][0] === p.at(-1)![0] && p[0][1] === p.at(-1)![1]) }; })() : { parts: [], closed: [] }), [layers, geometry]);
  const contours = useMemo(() => layers?.contours ?? [], [layers]);
  const paths = useMemo(() => hourPaths(contours), [contours]);
  const anchors = useMemo(() => labelAnchors(contours, epicentre), [contours, epicentre]);
  const between = useMemo(() => { const a = anchors.get(10); return a ? pointBetween(contours, a, 11) : null; }, [anchors, contours]);
  const stepsError = useMemo(() => { try { validateSteps(stationIds); return null; } catch (e) { return e instanceof Error ? e.message : "Story steps are invalid."; } }, [stationIds]);

  // ---- navigation: one reducer, one writer ----
  const nav: StoryNav = { ...params, a: state.selectedStationId, b: state.pinnedStationId };
  const navRef = useRef(nav); navRef.current = nav;
  const stepNow = typeof params.step === "number" ? STEPS[params.step - 1] : null;
  const fitK = fitView(CROP, size.w, size.h).k;
  const stepTarget = (step: StoryStep): Pt | null => "station" in step.lens ? stations.find(x => "station" in step.lens && x.id === step.lens.station)?.xy ?? null
    : step.lens.point === "epicentre" ? epicentre : between ?? epicentre;
  const targetOf = (n: StoryNav): Pt => n.at ? [n.at[0] * 1000, n.at[1] * 1000]
    : (typeof n.step === "number" ? stepTarget(STEPS[n.step - 1]) : null) ?? stations.find(s => s.id === n.a)?.xy ?? epicentre;
  const viewFor = (n: StoryNav): View => centreOn({ k: fitK * n.z, tx: 0, ty: 0 }, targetOf(n), L.cx, L.cy);
  const [view, setView] = useState<View>(() => viewFor(nav));
  const viewRef = useRef(view); viewRef.current = view;
  const [sheetExpanded, setSheetExpanded] = useState(false);
  const clock = useStoryClock({ initialT: params.t, svgRef, paths, motionOK, onCommit: (kind, t) => dispatch({ type: kind, t }) });
  const anim = useRef(0), userMoved = useRef(false), settleTimer = useRef(0), moving = useRef(false);
  const cancelGlide = () => { moving.current = false; if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(anim.current); };
  const glide = (target: View, done?: () => void) => {
    cancelGlide();
    // A hidden tab pauses animation frames: land at once rather than leave the lens stranded mid-glide.
    if (!motionOK || typeof requestAnimationFrame !== "function" || document.visibilityState === "hidden") { setView(target); done?.(); return; }
    const from = viewRef.current, t0 = performance.now(); moving.current = true;
    const step = (now: number) => { const p = Math.min(1, (now - t0) / 420), e = 1 - (1 - p) ** 3;
      setView({ k: from.k + (target.k - from.k) * e, tx: from.tx + (target.tx - from.tx) * e, ty: from.ty + (target.ty - from.ty) * e });
      if (p < 1) anim.current = requestAnimationFrame(step); else { moving.current = false; done?.(); } };
    anim.current = requestAnimationFrame(step);
  };
  const run = (r: NavResult) => {
    for (const e of r.effects) {
      if (e.kind === "stopPlay") clock.stop(false);
      else if (e.kind === "play") clock.play(e.from, e.until);
      else if (e.kind === "aim") { const v = viewFor(r.nav); if (e.instant) { cancelGlide(); setView(v); } else glide(v); }
      else if (e.kind === "focus") afterCommit(() => root.current?.querySelector<HTMLElement>(e.target === "step" ? "#story-step-title" : ".story-focus-panel")?.focus({ preventScroll: true }));
      else if (e.kind === "collapseSheet") setSheetExpanded(false);
    }
    if (r.history !== "back" && !r.effects.some(e => e.kind === "play") && r.nav.t !== clock.tRef.current) clock.set(r.nav.t);
  };
  const ctx = () => ({ motionOK, stationIds, prevEntryStep: historyPrev(), evidenceOpen: props.evidenceOpen, playing: clock.playing, sheetExpanded });
  const dispatch = (ev: NavEvent) => { const r = reduce(navRef.current, ev, ctx()); run(r); navRef.current = r.nav; props.onNav(r); };

  // Browser Back/Forward: the URL is already restored by DemoApp; move lens and clock to it without writing history.
  const restoreSeen = useRef(props.restoreKey);
  useEffect(() => { if (props.restoreKey === restoreSeen.current) return; restoreSeen.current = props.restoreKey; run(reduce(nav, { type: "popstate", nav }, ctx())); }, [props.restoreKey]);
  // Geometry or contours can arrive after the first render: aim once each, unless the reader has moved the map.
  const placed = useRef(stations.length > 0);
  useEffect(() => { if (!placed.current && stations.length) { placed.current = true; setView(viewFor(navRef.current)); } }, [stations.length]);
  useEffect(() => { if (between && !userMoved.current && !navRef.current.at && stepNow && "point" in stepNow.lens && stepNow.lens.point === "between-10-11") setView(viewFor(navRef.current)); }, [between]);

  const centre = toMap(view, L.cx, L.cy);
  const lensStation = stations.length ? capture(centre, footprintRadius(L.r, view.k, LENS_MAG), stations) : null;
  // The station under the lens drives the panels; while the map moves the URL is untouched, at rest it is corrected in place.
  useEffect(() => { if (lensStation && lensStation !== state.selectedStationId)
    props.onNav({ nav: { ...navRef.current, a: lensStation }, history: moving.current ? "none" : "replace", effects: [] }); },
    [lensStation, state.selectedStationId]);
  const settle = (explicit = false) => {
    window.clearTimeout(settleTimer.current);
    const v = viewRef.current, c = toMap(v, L.cx, L.cy);
    const station = stations.length ? capture(c, footprintRadius(L.r, v.k, LENS_MAG), stations) : null;
    dispatch({ type: "lensSettle", at: [Math.round(c[0] / 1000), Math.round(c[1] / 1000)], z: Math.round((v.k / fitK) * 100) / 100, station, explicit });
  };
  const settleSoon = () => { window.clearTimeout(settleTimer.current); settleTimer.current = window.setTimeout(() => settle(), SETTLE_MS); };
  const focusStation = (id: string, explicit = false) => { const s = stations.find(x => x.id === id); if (s) glide(centreOn(viewRef.current, s.xy, L.cx, L.cy), () => settle(explicit)); };
  const cycle = (d: 1 | -1) => { const i = Math.max(0, stations.findIndex(s => s.id === (lensStation ?? state.selectedStationId))); focusStation(stations[(i + d + stations.length) % stations.length].id); };
  const atOrigin = !lensStation && Math.hypot(epicentre[0] - centre[0], epicentre[1] - centre[1]) < footprintRadius(L.r, view.k, LENS_MAG);
  const reading = useMemo(() => lensStation || atOrigin ? null : nearestHours(contours, centre[0], centre[1], READING_RADIUS), [lensStation, atOrigin, contours, centre[0], centre[1]]);
  const nearest = useMemo(() => stations.reduce<MapStation | null>((best, s) => !best || Math.hypot(s.xy[0] - centre[0], s.xy[1] - centre[1]) < Math.hypot(best.xy[0] - centre[0], best.xy[1] - centre[1]) ? s : best, null), [stations, centre[0], centre[1]]);

  // ---- input ----
  const drag = useRef<{ x: number; y: number; v: View; moved: boolean } | null>(null);
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (!e.isPrimary) return;
    cancelGlide(); clock.stop();
    moving.current = true; drag.current = { x: e.clientX, y: e.clientY, v: viewRef.current, moved: false }; e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    const d = drag.current; if (!d || !e.isPrimary) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y; if (Math.hypot(dx, dy) > DRAG_SLOP) d.moved = true;
    if (d.moved) setView({ ...d.v, tx: d.v.tx + dx, ty: d.v.ty + dy });
  };
  const onPointerUp = () => { const d = drag.current; drag.current = null; moving.current = false; if (!d?.moved) return; userMoved.current = true; if (lensStation) focusStation(lensStation); else settle(); };
  const zoom = (factor: number) => { cancelGlide(); userMoved.current = true; setView(v => zoomAt(v, L.cx, L.cy, factor)); settleSoon(); };
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const pan: Record<string, [number, number]> = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] };
    if (pan[e.key]) { e.preventDefault(); cancelGlide(); userMoved.current = true; setView(v => ({ ...v, tx: v.tx + pan[e.key][0], ty: v.ty + pan[e.key][1] })); settleSoon(); }
    else if (e.key === "[" || e.key === "]") cycle(e.key === "]" ? 1 : -1);
    else if (e.key === "+" || e.key === "=" || e.key === "-") { e.preventDefault(); zoom(e.key === "-" ? 1 / 1.25 : 1.25); }
  };
  const toggleRef = useRef(() => {}), escapeRef = useRef(() => {});
  toggleRef.current = () => { if (!layers) return; if (motionOK) clock.toggle(); else if (clock.tRef.current < T_MAX) clock.seek(Math.min(T_MAX, Math.floor(clock.tRef.current) + 1)); };
  escapeRef.current = () => dispatch({ type: "escape" });
  useEffect(() => {
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") escapeRef.current();
      else if (e.key === " " && !e.repeat && (e.target === document.body || e.target === svgRef.current)) { e.preventDefault(); toggleRef.current(); }
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => { const svg = svgRef.current; if (!svg) return;
    const wheel = (e: WheelEvent) => { e.preventDefault(); cancelGlide(); userMoved.current = true; const r = svg.getBoundingClientRect();
      setView(v => zoomAt(v, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015))); settleSoon(); };
    svg.addEventListener("wheel", wheel, { passive: false }); return () => svg.removeEventListener("wheel", wheel); }, [geometry]);
  // Resize: keep the map point under the lens.
  useEffect(() => { const el = root.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height); if (w && h) setSize(s => s.w === w && s.h === h ? s : { w, h }); });
    ro.observe(el); return () => ro.disconnect(); }, []);
  const lastLayout = useRef(L);
  useEffect(() => { const prev = lastLayout.current; if (prev.cx !== L.cx || prev.cy !== L.cy) setView(v => centreOn(v, toMap(v, prev.cx, prev.cy), L.cx, L.cy)); lastLayout.current = L; }, [L.cx, L.cy]);

  // ---- derived display ----
  const t = clock.t, ocean = lensStation === null;
  const lensMeta = manifest.stations.find(s => s.station_id === lensStation) ?? selected.station;
  const aSel = selected.station.station_id === lensMeta.station_id ? selected : { station: lensMeta, status: "loading" as const, records: null, error: null };
  const counts = useMemo(() => !ocean && aSel.records ? hourlySamples(aSel.records, state.windowId, origin) : null, [ocean, aSel.records, state.windowId, origin]);
  const title = atOrigin ? { name: "Tōhoku epicentre", sub: "USGS origin 05:46:24 UTC · magnitude 9.1 · where the published clock starts" }
    : ocean ? { name: "Open Pacific", sub: reading ? `nearest published contours: ${reading.a} h and ${reading.b} h` : "no published contour nearby" }
    : { name: lensMeta.name, sub: `${lensMeta.station_type === "dart" ? "Deep-ocean DART buoy" : "Coastal tide gauge"} · ${clockLabel(t)} · ${utcAt(origin, t)}` };
  const b = params.compare ? props.pinned : null;
  const bStation = b ? stations.find(s => s.id === b.station.station_id) ?? null : null;
  const bSlot = L.bSlot, bScreen = bStation ? toScreen(view, bStation.xy) : null;
  const bOff = !!bScreen && (bScreen[0] < 0 || bScreen[0] > size.w || bScreen[1] < 0 || bScreen[1] > size.h);
  const bTarget: Pt | null = bScreen ? [Math.max(8, Math.min(size.w - 8, bScreen[0])), Math.max(8, Math.min(size.h - 8, bScreen[1]))] : null;
  const wide = L.mode === "wide", cine = clock.playing && motionOK && wide;

  if (!geometry) return <main className="story story--loading" ref={root}>{props.geometryError
    ? <div role="alert"><p>{props.geometryError}</p><button type="button" onClick={props.onRetryGeometry}>Retry map</button></div>
    : <p role="status">Loading the verified map…</p>}</main>;
  const alert = <>{props.layersError && <div role="alert" className="story-alert"><p>Published contour layer unavailable: {props.layersError}</p><button type="button" onClick={props.onRetryLayers}>Retry contours</button></div>}
    {stepsError && <div role="alert" className="story-alert"><p>{stepsError}</p></div>}
    {props.issues.length > 0 && <div role="status" className="story-alert"><p>This link was repaired:</p><ul>{props.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
      <button type="button" onClick={props.onDismissIssues}>Dismiss</button></div>}</>;
  const canPlayStep = !!stepNow?.play && motionOK && !!layers && !clock.playing && t < stepNow.play[1];
  const lead = stepNow && !stepsError ? <section className="story-step" aria-label={`Story step ${stepNow.id} of ${STEPS.length}`}>
    <p className="story-kicker">{stepNow.id} of {STEPS.length}</p>
    <h2 className="story-step__title" id="story-step-title" tabIndex={-1}>{stepNow.title}</h2>
    <p className="story-step__body">{stepNow.body}</p>
    {canPlayStep && <button type="button" className="story-step__play" onClick={() => clock.play(stepNow.play![0], stepNow.play![1])}>▶ Play this step</button>}
    <div className="story-step__nav"><button type="button" aria-disabled={stepNow.id === 1} onClick={() => dispatch({ type: "back" })}>Back</button>
      <button type="button" onClick={() => dispatch({ type: "next" })}>{stepNow.id < STEPS.length ? "Next" : "Explore"}</button></div>
    <p className="story-step__links"><button type="button" className="story-link" onClick={() => dispatch({ type: "returnToStep" })}>Return to this step</button>{" "}
      <button type="button" className="story-link" onClick={() => dispatch({ type: "explore" })}>Skip to free exploration</button></p>
  </section> : null;
  const extra = stepNow ? null : <><p className="story-step__links"><button type="button" className="story-link story-focus-panel" onClick={() => dispatch({ type: "resumeStory" })}>
    Back to the guided story (step {params.from ?? 1})</button></p><StationChips stations={stations} lensStation={lensStation} onPick={id => focusStation(id, true)}/></>;
  const column = <ClockColumn t={t} originUtc={origin} stationName={ocean ? null : lensMeta.name} counts={counts} alert={alert} lead={wide ? lead : null} className={wide ? "" : "story-column--sheet"}>{extra}</ClockColumn>;
  const compare = <section className="story-panel story-compare" aria-label="Views and comparison">
    <nav className="story-views" aria-label="Views"><button type="button" aria-pressed="true">Story</button>
      <button type="button" onClick={() => props.onView("paired")}>Paired</button><button type="button" onClick={() => props.onView("radial")}>Station lens</button></nav>
    <button type="button" aria-pressed={params.compare} onClick={() => dispatch({ type: params.compare ? "compareOff" : "compareOn" })}>{params.compare ? "Close compare ✕" : "⇄ Compare"}</button>
    <label className="story-compare__pick"><span className="story-tag story-tag--b">B</span><span className="story-sr">Pinned station B</span>
      <select value={state.pinnedStationId ?? ""} onChange={e => dispatch({ type: "pin", id: e.target.value })}>
        {state.pinnedStationId === null && <option value="">Choose B…</option>}
        {manifest.stations.filter(s => s.station_id !== state.selectedStationId || s.station_id === state.pinnedStationId).map(s => <option key={s.station_id} value={s.station_id}>{s.name}</option>)}
      </select></label>
    <p className="story-small">B is pinned while A follows the lens. Both share the UTC axis and the clock; heights stay station-local.</p>
  </section>;
  const bar = <ClockBar t={t} playing={clock.playing} disabled={!layers} originUtc={origin} reduced={!motionOK} onToggle={() => toggleRef.current()} onSeek={clock.seek}/>;
  const arms = <Arms ocean={ocean} atOrigin={atOrigin} nearestName={nearest?.name ?? "none"} reading={reading} t={t} originUtc={origin} a={aSel} b={b}
    windowId={state.windowId} productKey={state.productKey} onRetry={id => props.onRetryStation(id)} onOpenEvidence={props.onOpenEvidence}
    styles={{ record: L.record, support: L.support, read: L.read }}/>;
  return <main className={`story story--${L.mode}${cine ? " story--cine" : ""}`} ref={root} data-ocean={ocean ? "1" : "0"}>
    <svg ref={svgRef} className="story-map" width={size.w} height={size.h} tabIndex={0} role="img"
      aria-label="Pacific map of NOAA/NCEI published hourly travel-time contours with ten station records. Drag or use arrow keys to move the map under the lens; [ and ] change station; + and − zoom; Space plays the clock."
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onKeyDown={onKeyDown}>
      <WorldDefs coastline={coastline} contours={contours} initialT={t} smooth/>
      <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}><use href="#story-world"/></g>
      <Overlay view={view} stations={stations} epicentre={epicentre} anchors={anchors} t={t} aId={lensStation} bId={b?.station.station_id ?? null}/>
      <g className="story-leads" aria-hidden="true">
        {wide && <><line x1={L.cx - L.r * 0.7} y1={L.cy - L.r * 0.7} x2={Number(L.record.left) + L.aw} y2={L.cy - L.r + 6}/>
          <line x1={L.cx + L.r * 0.7} y1={L.cy - L.r * 0.7} x2={Number(L.support.left)} y2={L.cy - L.r + 6}/>
          <line x1={L.cx} y1={L.cy + L.r} x2={L.cx} y2={Number(L.read.top)}/></>}
        {bTarget && <path className="story-lead-b" d={`M${bSlot[0]} ${bSlot[1] - L.bR}Q${(bSlot[0] + bTarget[0]) / 2} ${Math.min(bSlot[1], bTarget[1]) - 60} ${bTarget[0]} ${bTarget[1]}`}/>}
      </g>
      <Lens id="story-lens-a" view={view} cx={L.cx} cy={L.cy} centre={centre} r={L.r} mag={LENS_MAG} stations={stations} epicentre={epicentre} variant="a"/>
      {bStation && <Lens id="story-lens-b" view={view} cx={bSlot[0]} cy={bSlot[1]} centre={bStation.xy} r={L.bR} mag={B_LENS_MAG} stations={stations} epicentre={epicentre}
        variant="b" caption={`B · ${bStation.name}${bOff ? " (off-screen)" : ""}`}/>}
    </svg>
    <div className="story-lens-title" style={{ left: L.cx, top: L.titleTop }}><p className="story-lens-title__name">{title.name}</p><p className="story-lens-title__sub">{title.sub}</p></div>
    {wide ? <>{arms}{column}{compare}{bar}</> : <div className={`story-sheet story-sheet--${L.mode}${sheetExpanded ? " story-sheet--expanded" : ""}`}>
      <button type="button" className="story-sheet__handle" aria-expanded={sheetExpanded} onClick={() => setSheetExpanded(x => !x)}>{sheetExpanded ? "Collapse panel" : "Expand panel"}</button>
      {lead}
      <div className="story-sheet__nav"><button type="button" onClick={() => cycle(-1)}>‹ Previous station</button><button type="button" onClick={() => cycle(1)}>Next station ›</button></div>
      {bar}{arms}{compare}{column}
    </div>}
    <p className="story-sr" aria-live="polite">{`${title.name}. Clock ${clockLabel(Math.floor(t))}.`}</p>
  </main>;
}

export function StationChips({ stations, lensStation, onPick }: { stations: MapStation[]; lensStation: string | null; onPick: (id: string) => void }) {
  return <>
    <h2 className="story-h">Station records</h2>
    {(["dart", "coastal"] as const).map(kind => <div key={kind}><p className="story-small">{kind === "dart" ? "◆ Deep-ocean DART" : "● Coastal gauges"}</p>
      {stations.filter(s => s.type === kind).map(s => <button key={s.id} type="button" className={`story-chip${s.id === lensStation ? " story-chip--on" : ""}`}
        aria-pressed={s.id === lensStation} onClick={() => onPick(s.id)}>{s.name}</button>)}</div>)}
  </>;
}
