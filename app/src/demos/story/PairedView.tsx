import { useEffect, useRef, useState } from "react";
import { NoReference, StationCard } from "../StationCard";
import { ClockBar } from "./ClockBar";
import { clockLabel } from "./clock";
import { reduce, type NavEvent, type StoryNav } from "./nav";
import { StationTools } from "./StationTools";
import { fitView, Overlay, PACIFIC_CROP, toScreen, useStage, WorldDefs } from "./StoryMap";
import { Notes, type StoryViewProps } from "./StoryView";
import { reducedMotion, useStoryClock } from "./useStoryClock";
import { ViewSwitch } from "./ViewSwitch";
import "./style.css";

/** Paired: two stations' full records, side by side on the shared clock, under a Pacific band that names A and B. */
export function PairedView(props: StoryViewProps) {
  const { manifest, geometry, layers, state, selected, pinned, params } = props;
  const origin = manifest.event.origin_time_utc, motionOK = !reducedMotion();
  const { stationIds, stations, epicentre, coastline, contours, paths, anchors } = useStage(manifest, geometry, layers);
  const band = useRef<HTMLDivElement>(null), svgRef = useRef<SVGSVGElement>(null);
  // ponytail: a fitted, fixed Pacific band (no pan or zoom); Station lens is the place to explore the map.
  const [size, setSize] = useState({ w: 960, h: 260 });
  useEffect(() => {
    const el = band.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height);
      if (w && h) setSize(s => s.w === w && s.h === h ? s : { w, h });
    });
    ro.observe(el); return () => ro.disconnect();
  }, [geometry]);
  const view = fitView(PACIFIC_CROP, size.w, size.h);

  // Same contract as the story: one reducer, DemoApp's single writer, every action from the live clock.
  const navRef = useRef<StoryNav>({ ...params, a: state.selectedStationId, b: state.pinnedStationId });
  navRef.current = { ...params, a: state.selectedStationId, b: state.pinnedStationId };
  const [said, setSaid] = useState("");
  const clock = useStoryClock({ initialT: params.t, svgRef, paths, motionOK, onCommit: (kind, t) => dispatch({ type: kind, t }),
    onPause: t => setSaid(`Clock paused at ${clockLabel(t)}.`) });
  const live = (): StoryNav => ({ ...navRef.current, t: clock.tRef.current });
  const dispatch = (ev: NavEvent) => {
    const r = reduce(live(), ev, { motionOK: motionOK && !!layers, stationIds, evidenceOpen: props.evidenceOpen, playing: clock.playing });
    if (r.effects.some(e => e.kind === "stopPlay")) clock.stop(false);
    props.onNav(r);
  };
  const pick = (id: string) => {
    if (id === state.selectedStationId) return;
    const s = stations.find(x => x.id === id);
    dispatch({ type: "lensSettle", at: s ? [Math.round(s.xy[0] / 1000), Math.round(s.xy[1] / 1000)] : null, z: navRef.current.z, station: id, explicit: true });
  };
  const toggle = () => { if (!layers) return; const next = clock.playOrStep(); if (next !== null) setSaid(`Clock ${clockLabel(next)}.`); };
  const keys = useRef({ toggle, escape: () => dispatch({ type: "escape" }) }); keys.current = { toggle, escape: () => dispatch({ type: "escape" }) };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") keys.current.escape();
      else if (e.key === " " && !e.repeat && e.target === document.body) { e.preventDefault(); keys.current.toggle(); }
    };
    const drop = () => clock.cancelSeek();
    window.addEventListener("keydown", key); window.addEventListener("popstate", drop);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("popstate", drop); };
  }, []);
  // Browser Back/Forward: DemoApp restored the URL; bring the clock to it without writing history.
  const restoreSeen = useRef(props.restoreKey);
  useEffect(() => {
    if (props.restoreKey === restoreSeen.current) return;
    restoreSeen.current = props.restoreKey; clock.stop(false); clock.set(params.t);
  }, [props.restoreKey]);

  const t = clock.t, cursorMs = Date.parse(origin) + t * 3_600_000, A = state.selectedStationId, B = state.pinnedStationId;
  const card = { windowId: state.windowId, productKey: state.productKey, cursorMs, onOpenEvidence: props.onOpenEvidence, onRetryStation: props.onRetryStation };
  return <main className="story story--paired" aria-label="Paired station records">
    <header className="paired-head">
      <div><p className="story-kicker">Pacific · 11 March 2011</p><h1 className="story-title">Paired records</h1>
        <p className="story-small">Two stations on one clock. Each keeps its own scale and datum; heights are not compared. Contours are NOAA/NCEI
          published travel-time estimates, not arrivals.</p></div>
      <ViewSwitch view="paired" onView={v => props.onState({ view: v }, live())}/>
    </header>
    <Notes {...props}/>
    <section className="paired-band" aria-label="Station map" ref={band}>
      {geometry ? <>
        <svg ref={svgRef} width={size.w} height={size.h} aria-hidden="true">
          <WorldDefs coastline={coastline} contours={contours} paths={paths} initialT={t}/>
          <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}><use href="#story-world"/></g>
          <Overlay view={view} stations={stations} epicentre={epicentre} anchors={anchors} t={t} aId={A} bId={B} labelA/>
        </svg>
        {stations.map(s => {
          const [x, y] = toScreen(view, s.xy), isA = s.id === A, isB = s.id === B, name = `${s.name} (${s.id})`;
          return <button key={s.id} type="button" className={`paired-station${isA ? " paired-station--a" : isB ? " paired-station--b" : ""}`}
            style={{ left: x, top: y }} aria-pressed={isA} onClick={() => pick(s.id)}
            aria-label={isA ? `Selected A: ${name}` : isB ? `Pinned reference B: ${name}` : `Make ${name} A`}/>;
        })}
      </> : props.geometryError ? <div role="alert" className="story-alert"><p>Map unavailable: {props.geometryError}</p>
        <button type="button" onClick={props.onRetryGeometry}>Retry map</button><p className="story-small">The records below stay available.</p></div>
        : <p role="status" className="story-small">Loading the verified map…</p>}
    </section>
    <p className="story-small paired-band__caption">Pacific locator · Equal Earth, 160° W · published hourly contours lit up to the clock. Tap a station
      to make it A; where marks crowd, use Station A below.</p>
    <StationTools stations={manifest.stations} windows={manifest.windows} selectedStationId={A} pinnedStationId={B} windowId={state.windowId}
      productKey={state.productKey} onSelect={pick} onPin={id => dispatch(id ? { type: "pin", id } : { type: "unpin" })}
      onWindow={windowId => props.onState({ windowId }, live())} onProduct={productKey => props.onState({ productKey }, live())}/>
    <div className="paired-cards">
      <StationCard selection={selected} role="selected" {...card}/>
      {pinned ? <StationCard selection={pinned} role="pinned" {...card}/> : <NoReference/>}
    </div>
    <ClockBar t={t} playing={clock.playing} disabled={!layers} originUtc={origin} reduced={!motionOK} onToggle={toggle} onSeek={clock.seek}/>
    <footer className="paired-foot"><p>{manifest.bundle_id} · internal descriptive evidence only. No validated arrivals, warning time or continuous
      ocean field.</p><p>Integrity is checked against this local manifest, not a signature against replacement of the whole bundle. Source terms and
      unknown datums remain in force.</p></footer>
    <p className="story-sr" aria-live="polite">{said}</p>
  </main>;
}
