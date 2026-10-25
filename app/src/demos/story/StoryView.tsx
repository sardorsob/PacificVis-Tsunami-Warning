import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { RadialProps } from "../types";
import { Arms } from "./Arms";
import { ClockBar } from "./ClockBar";
import { ClockColumn, hourlySamples } from "./ClockColumn";
import { clockLabel, seek, T_MAX, tick, toggle, utcAt } from "./clock";
import { hourPaths, labelAnchors, nearestHours, pointBetween, type Coastline, type Pt, type StoryLayers } from "./layers";
import { B_LENS_MAG, B_LENS_RADIUS, capture, footprintRadius, LENS_MAG, LENS_RADIUS, slot } from "./lensMath";
import { Lens } from "./Lens";
import { PULSE_MS } from "./reveal";
import { STEPS, validateSteps, type StepId, type StoryStep } from "./steps";
import { centreOn, fitView, Overlay, paintContours, toMap, toScreen, WorldDefs, zoomAt, type MapStation, type View } from "./StoryMap";
import type { StoryParams } from "./url";
import "./style.css";

export type StoryViewProps = RadialProps & {
  layers: StoryLayers | null; layersError: string | null; onRetryLayers: () => void;
  params: StoryParams; onParams: (params: StoryParams, push: boolean) => void; onPinStation: (stationId: string) => void;
  /** Map point to place under the lens on first render (defaults to the selected station). */
  initialCentre?: Pt;
  /** Test seam: the first-render viewport before ResizeObserver reports. */
  initialSize?: { w: number; h: number };
};
const CROP: [number, number, number, number] = [-6.4e6, -6.3e6, 8.9e6, 4.6e6];
const COLUMN = 300, RIGHT = 270, GAP = 44, READING_RADIUS = 450_000;
export const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export type Mode = "wide" | "narrow" | "short";
/** wide: lens + arms + column; narrow (< 768 px): lens in the upper third, bottom sheet; short landscape: lens left, side sheet. */
export function layoutFor(w: number, h: number) {
  const mode: Mode = w < 768 ? "narrow" : h <= 450 ? "short" : "wide";
  if (mode !== "wide") {
    const r = mode === "narrow" ? Math.min(82, w * 0.21) : Math.min(82, h * 0.27);
    const cx = mode === "narrow" ? w / 2 : w * 0.29, cy = mode === "narrow" ? Math.max(r + 64, h * 0.25) : h * 0.56;
    return { mode, cx, cy, r, aw: 0, gap: 0, record: {}, support: {}, read: {}, titleTop: cy - r - 54, bSlot: [cx + r + (mode === "narrow" ? 48 : 70), cy + r - 6] as Pt, bR: 38 };
  }
  const cx = COLUMN + (w - COLUMN - RIGHT) / 2, cy = h * 0.4, r = LENS_RADIUS;
  const aw = Math.max(250, Math.min(330, (w - COLUMN - RIGHT) / 2 - r - GAP - 10));
  return { mode, cx, cy, r, aw, gap: GAP,
    record: { left: cx - r - GAP - aw, top: cy - r - 30, width: aw },
    support: { left: cx + r + GAP, top: cy - r - 30, width: aw },
    read: { left: cx - 150, top: cy + r + 30, width: 300 },
    titleTop: cy - r - 76, bSlot: slot(cx, cy, r, GAP, aw, h), bR: B_LENS_RADIUS };
}
function flipped(parts: number[][][]): Pt[][] { return parts.map(part => part.map(([x, y]) => [x, -y] as Pt)); }

export function StoryView(props: StoryViewProps) {
  const { manifest, geometry, layers, state, selected, params } = props;
  const origin = manifest.event.origin_time_utc;
  const root = useRef<HTMLElement>(null), svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState(props.initialSize ?? { w: 1440, h: 848 });
  const L = layoutFor(size.w, size.h);
  const stations = useMemo<MapStation[]>(() => geometry ? manifest.stations.map(s => {
    const p = geometry.points.find(q => q.id === s.station_id)!; return { id: s.station_id, name: s.name, type: s.station_type, xy: [p.x, -p.y] as Pt };
  }) : [], [geometry, manifest]);
  const epicentre = useMemo<Pt>(() => { const p = geometry?.points.find(q => q.id === manifest.event.event_id); return p ? [p.x, -p.y] : [0, 0]; }, [geometry, manifest]);
  const coastline = useMemo<Coastline>(() => layers?.coastline ?? (geometry ? (() => { const parts = flipped(geometry.coastline); return { parts, closed: parts.map(p => p.length > 3 && p[0][0] === p.at(-1)![0] && p[0][1] === p.at(-1)![1]) }; })() : { parts: [], closed: [] }), [layers, geometry]);
  const contours = useMemo(() => layers?.contours ?? [], [layers]);
  const paths = useMemo(() => hourPaths(contours), [contours]);
  const anchors = useMemo(() => labelAnchors(contours, epicentre), [contours, epicentre]);
  const stepNow = typeof params.step === "number" ? STEPS[params.step - 1] : null;
  const between = useMemo(() => { const a = anchors.get(10); return a ? pointBetween(contours, a, 11) : null; }, [anchors, contours]);
  const stepTarget = (step: StoryStep): Pt | null => "station" in step.lens ? stations.find(x => "station" in step.lens && x.id === step.lens.station)?.xy ?? null
    : step.lens.point === "epicentre" ? epicentre : between ?? epicentre;
  const stepsError = useMemo(() => { try { validateSteps(manifest.stations.map(x => x.station_id)); return null; } catch (e) { return e instanceof Error ? e.message : "Story steps are invalid."; } }, [manifest]);
  const start = props.initialCentre ?? (stepNow && stations.length ? stepTarget(stepNow) : null) ?? stations.find(s => s.id === state.selectedStationId)?.xy ?? [0, 0];
  const [view, setView] = useState<View>(() => centreOn(fitView(CROP, size.w, size.h), start, L.cx, L.cy));
  // Geometry can arrive after the first render: centre the starting point once it does.
  const placed = useRef(stations.length > 0), userMoved = useRef(false);
  useEffect(() => { if (!placed.current && stations.length) { placed.current = true; setView(v => centreOn(v, start, L.cx, L.cy)); } }, [stations.length]);
  // A step aimed between two contours needs the contour layer; re-aim once it loads unless the reader has moved the map.
  useEffect(() => { if (between && stepNow && "point" in stepNow.lens && stepNow.lens.point === "between-10-11" && !userMoved.current) setView(v => centreOn(v, between, L.cx, L.cy)); }, [between]);
  const centre = toMap(view, L.cx, L.cy);
  const lensStation = stations.length ? capture(centre, footprintRadius(L.r, view.k, LENS_MAG), stations) : null;
  const atOrigin = !lensStation && Math.hypot(epicentre[0] - centre[0], epicentre[1] - centre[1]) < footprintRadius(L.r, view.k, LENS_MAG);
  const reading = useMemo(() => lensStation || atOrigin ? null : nearestHours(contours, centre[0], centre[1], READING_RADIUS), [lensStation, atOrigin, contours, centre[0], centre[1]]);
  const nearest = useMemo(() => stations.reduce<MapStation | null>((best, s) => !best || Math.hypot(s.xy[0] - centre[0], s.xy[1] - centre[1]) < Math.hypot(best.xy[0] - centre[0], best.xy[1] - centre[1]) ? s : best, null), [stations, centre[0], centre[1]]);

  // ---- the story clock: React state at ≤10 Hz, contours painted every frame ----
  const [t, setT] = useState(params.t), [playing, setPlaying] = useState(false);
  const tRef = useRef(params.t), playingRef = useRef(false), loop = useRef(0), pulses = useRef(new Map<number, number>()), untilRef = useRef(T_MAX);
  const paramsRef = useRef(params); paramsRef.current = params;
  const motionOK = !reducedMotion();
  useEffect(() => { if (!playingRef.current) { tRef.current = params.t; setT(params.t); } }, [params.t]);
  const paint = (now: number) => { if (svgRef.current) paintContours(svgRef.current, tRef.current, true, pulses.current, now, paths); };
  useEffect(() => { paint(typeof performance === "undefined" ? 0 : performance.now()); }, [t, paths]);
  const commit = (value: number) => props.onParams({ ...paramsRef.current, t: Math.round(value * 100) / 100 }, false);
  const prune = (now: number) => { for (const [h, s] of pulses.current) if (now - s > PULSE_MS) pulses.current.delete(h); };
  const pulseOut = () => { const frame = (now: number) => { paint(now); prune(now); if (pulses.current.size && !playingRef.current) requestAnimationFrame(frame); else paint(now); }; requestAnimationFrame(frame); };
  const stop = () => { playingRef.current = false; cancelAnimationFrame(loop.current); setPlaying(false); };
  const run = () => {
    let last = performance.now(), ui = 0;
    const frame = (now: number) => {
      const r = tick({ t: tRef.current, playing: true }, (now - last) / 1000); last = now;
      const nt = Math.min(r.clock.t, untilRef.current), going = r.clock.playing && nt < untilRef.current; tRef.current = nt;
      for (const h of r.crossed) if (h <= nt) pulses.current.set(h, now);
      prune(now); paint(now);
      if (now - ui > 100 || !going) { ui = now; setT(nt); }
      if (going && playingRef.current) loop.current = requestAnimationFrame(frame);
      else { stop(); commit(nt); if (pulses.current.size) pulseOut(); }
    };
    loop.current = requestAnimationFrame(frame);
  };
  const playTo = (from: number) => { tRef.current = from; setT(from); playingRef.current = true; setPlaying(true); run(); };
  const togglePlay = () => {
    if (!layers) return;
    if (!motionOK) { onSeek(Math.min(T_MAX, Math.floor(tRef.current) + 1)); return; } // reduced motion: step one published hour
    const c = toggle({ t: tRef.current, playing: playingRef.current });
    if (!c.playing) { stop(); commit(tRef.current); } else { untilRef.current = T_MAX; playTo(c.t); }
  };
  const onSeek = (v: number) => {
    if (playingRef.current) stop();
    const r = seek({ t: tRef.current, playing: false }, v); tRef.current = r.clock.t; setT(r.clock.t); commit(r.clock.t);
    if (motionOK && r.crossed.length) { const now = performance.now(); for (const h of r.crossed.slice(-3)) pulses.current.set(h, now); pulseOut(); }
  };
  const toggleRef = useRef(togglePlay); toggleRef.current = togglePlay;
  // Guided steps: each sets its authored clock, lens target, compare flag and pinned station.
  const goToStep = (n: StepId) => {
    const step = STEPS[n - 1], animate = !!step.play && motionOK && !!layers, startT = animate ? step.play![0] : step.t;
    if (step.b && step.b !== state.pinnedStationId) props.onPinStation(step.b);
    const target = stepTarget(step); if (target) focusPoint(target);
    if (playingRef.current) stop();
    tRef.current = startT; setT(startT);
    props.onParams({ ...params, t: startT, compare: step.compare, step: n, at: null, z: 1, from: null }, true);
    if (animate) { untilRef.current = step.play![1]; playTo(step.play![0]); }
  };
  const explore = () => props.onParams({ ...params, t: tRef.current, step: "explore" }, true);
  useEffect(() => { if (stepNow?.b && state.pinnedStationId !== stepNow.b) props.onPinStation(stepNow.b); }, []);
  useEffect(() => {
    const key = (e: globalThis.KeyboardEvent) => { if (e.key === " " && (e.target === document.body || e.target === svgRef.current)) { e.preventDefault(); toggleRef.current(); } };
    window.addEventListener("keydown", key); return () => { window.removeEventListener("keydown", key); cancelAnimationFrame(loop.current); };
  }, []);

  // Resize: keep the map point under the lens.
  useEffect(() => { const el = root.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height); if (w && h) setSize(s => s.w === w && s.h === h ? s : { w, h }); });
    ro.observe(el); return () => ro.disconnect(); }, []);
  const lastLayout = useRef(L);
  useEffect(() => { const prev = lastLayout.current; if (prev.cx !== L.cx || prev.cy !== L.cy) setView(v => centreOn(v, toMap(v, prev.cx, prev.cy), L.cx, L.cy)); lastLayout.current = L; }, [L.cx, L.cy]);
  // The lens selects the station it covers; DemoApp loads its verified record.
  useEffect(() => { if (lensStation && lensStation !== state.selectedStationId) props.onSelectStation(lensStation); }, [lensStation]);

  const anim = useRef(0);
  const glide = (target: View) => {
    cancelAnimationFrame(anim.current);
    if (!motionOK || typeof requestAnimationFrame !== "function") { setView(target); return; }
    const from = view, t0 = performance.now();
    const step = (now: number) => { const p = Math.min(1, (now - t0) / 420), e = 1 - (1 - p) ** 3;
      setView({ k: from.k + (target.k - from.k) * e, tx: from.tx + (target.tx - from.tx) * e, ty: from.ty + (target.ty - from.ty) * e }); if (p < 1) anim.current = requestAnimationFrame(step); };
    anim.current = requestAnimationFrame(step);
  };
  const focusPoint = (p: Pt) => glide(centreOn(view, p, L.cx, L.cy));
  const focusStation = (id: string) => { const s = stations.find(x => x.id === id); if (s) focusPoint(s.xy); };
  const drag = useRef<{ x: number; y: number; v: View } | null>(null);
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => { userMoved.current = true; drag.current = { x: e.clientX, y: e.clientY, v: view }; e.currentTarget.setPointerCapture(e.pointerId); };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => { const d = drag.current; if (d) setView({ ...d.v, tx: d.v.tx + e.clientX - d.x, ty: d.v.ty + e.clientY - d.y }); };
  const onPointerUp = () => { if (!drag.current) return; drag.current = null; if (lensStation) focusStation(lensStation); };
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    userMoved.current = true;
    const pan: Record<string, [number, number]> = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] };
    if (pan[e.key]) { e.preventDefault(); setView(v => ({ ...v, tx: v.tx + pan[e.key][0], ty: v.ty + pan[e.key][1] })); }
    else if (e.key === "[" || e.key === "]") { const i = Math.max(0, stations.findIndex(s => s.id === (lensStation ?? state.selectedStationId)));
      focusStation(stations[(i + (e.key === "]" ? 1 : stations.length - 1)) % stations.length].id); }
    else if (e.key === "+" || e.key === "=" || e.key === "-") { e.preventDefault(); setView(v => zoomAt(v, L.cx, L.cy, e.key === "-" ? 1 / 1.25 : 1.25)); }
  };
  useEffect(() => { const svg = svgRef.current; if (!svg) return;
    const wheel = (e: WheelEvent) => { e.preventDefault(); const r = svg.getBoundingClientRect(); setView(v => zoomAt(v, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015))); };
    svg.addEventListener("wheel", wheel, { passive: false }); return () => svg.removeEventListener("wheel", wheel); }, [geometry]);

  const ocean = lensStation === null;
  const lensMeta = manifest.stations.find(s => s.station_id === lensStation) ?? selected.station;
  const aSel = selected.station.station_id === lensMeta.station_id ? selected : { station: lensMeta, status: "loading" as const, records: null, error: null };
  const counts = useMemo(() => !ocean && aSel.records ? hourlySamples(aSel.records, state.windowId, origin) : null, [ocean, aSel.records, state.windowId, origin]);
  const title = atOrigin ? { name: "Tōhoku epicentre", sub: "USGS origin 05:46:24 UTC · magnitude 9.1 · where the published clock starts" }
    : ocean ? { name: "Open Pacific", sub: reading ? `nearest published contours: ${reading.a} h and ${reading.b} h` : "no published contour nearby" }
    : { name: lensMeta.name, sub: `${lensMeta.station_type === "dart" ? "Deep-ocean DART buoy" : "Coastal tide gauge"} · ${clockLabel(t)} · ${utcAt(origin, t)}` };
  const b = params.compare ? props.pinned : null;
  const bStation = b ? stations.find(s => s.id === b.station.station_id) ?? null : null;
  const bSlot = L.bSlot;
  const bScreen = bStation ? toScreen(view, bStation.xy) : null;
  const bOff = !!bScreen && (bScreen[0] < 0 || bScreen[0] > size.w || bScreen[1] < 0 || bScreen[1] > size.h);
  const bTarget: Pt | null = bScreen ? [Math.max(8, Math.min(size.w - 8, bScreen[0])), Math.max(8, Math.min(size.h - 8, bScreen[1]))] : null;
  const wide = L.mode === "wide", cine = playing && motionOK && wide;
  const cycle = (d: 1 | -1) => { const i = Math.max(0, stations.findIndex(s => s.id === (lensStation ?? state.selectedStationId))); focusStation(stations[(i + d + stations.length) % stations.length].id); };

  if (!geometry) return <main className="story story--loading" ref={root}>{props.geometryError ? <div role="alert"><p>{props.geometryError}</p><button type="button" onClick={props.onRetryGeometry}>Retry map</button></div> : <p role="status">Loading the verified map…</p>}</main>;
  const alert = <>{props.layersError && <div role="alert" className="story-alert"><p>Published contour layer unavailable: {props.layersError}</p><button type="button" onClick={props.onRetryLayers}>Retry contours</button></div>}
    {stepsError && <div role="alert" className="story-alert"><p>{stepsError}</p></div>}</>;
  const lead = stepNow && !stepsError ? <section className="story-step" aria-label={`Story step ${stepNow.id} of ${STEPS.length}`}>
    <p className="story-kicker">{stepNow.id} of {STEPS.length}</p>
    <h2 className="story-step__title">{stepNow.title}</h2>
    <p className="story-step__body">{stepNow.body}</p>
    <div className="story-step__nav"><button type="button" disabled={stepNow.id === 1} onClick={() => goToStep((stepNow.id - 1) as StepId)}>Back</button>
      {stepNow.id < STEPS.length ? <button type="button" onClick={() => goToStep((stepNow.id + 1) as StepId)}>Next</button> : <button type="button" onClick={explore}>Explore</button>}</div>
    <p className="story-step__links"><button type="button" className="story-link" onClick={() => goToStep(stepNow.id)}>Return to this step</button> <button type="button" className="story-link" onClick={explore}>Skip to free exploration</button></p>
  </section> : null;
  const extra = stepNow ? null : <><StationChips stations={stations} lensStation={lensStation} onPick={focusStation}/><p className="story-step__links"><button type="button" className="story-link" onClick={() => goToStep(1)}>Back to the guided story</button></p></>;
  const column = <ClockColumn t={t} originUtc={origin} stationName={ocean ? null : lensMeta.name} counts={counts} alert={alert} lead={wide ? lead : null} className={wide ? "" : "story-column--sheet"}>{extra}</ClockColumn>;
  const compare = <section className="story-panel story-compare" aria-label="Compare two records">
    <button type="button" aria-pressed={params.compare} onClick={() => props.onParams({ ...params, t: tRef.current, compare: !params.compare }, true)}>⇄ Compare</button>
    <label className="story-compare__pick"><span className="story-tag story-tag--b">B</span><span className="story-sr">Pinned station B</span>
      <select value={state.pinnedStationId ?? ""} onChange={e => props.onPinStation(e.target.value)}>{manifest.stations.map(s => <option key={s.station_id} value={s.station_id}>{s.name}</option>)}</select></label>
    <p className="story-small">Adds a pinned second lens. Both records share the UTC axis and the clock; heights stay station-local.</p>
  </section>;
  const bar = <ClockBar t={t} playing={playing} disabled={!layers} originUtc={origin} reduced={!motionOK} onToggle={togglePlay} onSeek={onSeek}/>;
  const arms = <Arms ocean={ocean} atOrigin={atOrigin} nearestName={nearest?.name ?? "none"} reading={reading} t={t} originUtc={origin} a={aSel} b={b}
    windowId={state.windowId} productKey={state.productKey} onRetry={() => props.onRetryStation(lensMeta.station_id)} styles={{ record: L.record, support: L.support, read: L.read }}/>;
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
      {bStation && <Lens id="story-lens-b" view={view} cx={bSlot[0]} cy={bSlot[1]} centre={bStation.xy} r={L.bR} mag={B_LENS_MAG} stations={stations} epicentre={epicentre} variant="b" caption={`B · ${bStation.name}${bOff ? " (off-screen)" : ""}`}/>}
    </svg>
    <div className="story-lens-title" style={{ left: L.cx, top: L.titleTop }}><p className="story-lens-title__name">{title.name}</p><p className="story-lens-title__sub">{title.sub}</p></div>
    {wide ? <>{arms}{column}{compare}{bar}</> : <div className={`story-sheet story-sheet--${L.mode}`}>
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
      {stations.filter(s => s.type === kind).map(s => <button key={s.id} type="button" className={`story-chip${s.id === lensStation ? " story-chip--on" : ""}`} aria-pressed={s.id === lensStation} onClick={() => onPick(s.id)}>{s.name}</button>)}</div>)}
  </>;
}
