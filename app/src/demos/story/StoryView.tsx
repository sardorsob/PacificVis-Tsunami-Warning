import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { RadialProps } from "../types";
import { Arms } from "./Arms";
import { clockLabel, utcAt } from "./clock";
import { labelAnchors, nearestHours, type Coastline, type Pt, type StoryLayers } from "./layers";
import { capture, footprintRadius, LENS_MAG, LENS_RADIUS } from "./lensMath";
import { Lens } from "./Lens";
import { centreOn, fitView, Overlay, toMap, WorldDefs, zoomAt, type MapStation, type View } from "./StoryMap";
import type { StoryParams } from "./url";
import "./style.css";

export type StoryViewProps = RadialProps & {
  layers: StoryLayers | null; layersError: string | null; onRetryLayers: () => void;
  params: StoryParams; onParams: (params: StoryParams, push: boolean) => void; onPinStation: (stationId: string) => void;
  /** Map point to place under the lens on first render (defaults to the selected station). */
  initialCentre?: Pt;
};
const CROP: [number, number, number, number] = [-6.4e6, -6.3e6, 8.9e6, 4.6e6];
const COLUMN = 300, RIGHT = 270, GAP = 44, READING_RADIUS = 450_000;
const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export function layoutFor(w: number, h: number) {
  const cx = COLUMN + (w - COLUMN - RIGHT) / 2, cy = h * 0.4, r = LENS_RADIUS;
  const aw = Math.max(250, Math.min(330, (w - COLUMN - RIGHT) / 2 - r - GAP - 10));
  return { cx, cy, r, aw, gap: GAP,
    record: { left: cx - r - GAP - aw, top: cy - r - 30, width: aw },
    support: { left: cx + r + GAP, top: cy - r - 30, width: aw },
    read: { left: cx - 150, top: cy + r + 30, width: 300 },
    titleTop: cy - r - 76 };
}
function flipped(parts: number[][][]): Pt[][] { return parts.map(part => part.map(([x, y]) => [x, -y] as Pt)); }

export function StoryView(props: StoryViewProps) {
  const { manifest, geometry, layers, state, selected, params } = props;
  const root = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 1440, h: 848 });
  const L = layoutFor(size.w, size.h);
  const stations = useMemo<MapStation[]>(() => geometry ? manifest.stations.map(s => {
    const p = geometry.points.find(q => q.id === s.station_id)!; return { id: s.station_id, name: s.name, type: s.station_type, xy: [p.x, -p.y] as Pt };
  }) : [], [geometry, manifest]);
  const epicentre = useMemo<Pt>(() => { const p = geometry?.points.find(q => q.id === manifest.event.event_id); return p ? [p.x, -p.y] : [0, 0]; }, [geometry, manifest]);
  const coastline = useMemo<Coastline>(() => layers?.coastline ?? (geometry ? (() => { const parts = flipped(geometry.coastline); return { parts, closed: parts.map(p => p.length > 3 && p[0][0] === p.at(-1)![0] && p[0][1] === p.at(-1)![1]) }; })() : { parts: [], closed: [] }), [layers, geometry]);
  const contours = useMemo(() => layers?.contours ?? [], [layers]);
  const anchors = useMemo(() => labelAnchors(contours, epicentre), [contours, epicentre]);
  const start = props.initialCentre ?? stations.find(s => s.id === state.selectedStationId)?.xy ?? [0, 0];
  const [view, setView] = useState<View>(() => centreOn(fitView(CROP, size.w, size.h), start, L.cx, L.cy));
  // Geometry can arrive after the first render: centre the starting point once it does.
  const placed = useRef(stations.length > 0);
  useEffect(() => { if (!placed.current && stations.length) { placed.current = true; setView(v => centreOn(v, start, L.cx, L.cy)); } }, [stations.length]);
  const centre = toMap(view, L.cx, L.cy);
  const lensStation = stations.length ? capture(centre, footprintRadius(L.r, view.k, LENS_MAG), stations) : null;
  const reading = useMemo(() => lensStation ? null : nearestHours(contours, centre[0], centre[1], READING_RADIUS), [lensStation, contours, centre[0], centre[1]]);
  const nearest = useMemo(() => stations.reduce<MapStation | null>((best, s) => !best || Math.hypot(s.xy[0] - centre[0], s.xy[1] - centre[1]) < Math.hypot(best.xy[0] - centre[0], best.xy[1] - centre[1]) ? s : best, null), [stations, centre[0], centre[1]]);
  const t = params.t;

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
    if (reducedMotion() || typeof requestAnimationFrame !== "function") { setView(target); return; }
    const from = view, t0 = performance.now();
    const step = (now: number) => { const p = Math.min(1, (now - t0) / 420), e = 1 - (1 - p) ** 3;
      setView({ k: from.k + (target.k - from.k) * e, tx: from.tx + (target.tx - from.tx) * e, ty: from.ty + (target.ty - from.ty) * e }); if (p < 1) anim.current = requestAnimationFrame(step); };
    anim.current = requestAnimationFrame(step);
  };
  const focusStation = (id: string) => { const s = stations.find(x => x.id === id); if (s) glide(centreOn(view, s.xy, L.cx, L.cy)); };
  const drag = useRef<{ x: number; y: number; v: View } | null>(null);
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => { drag.current = { x: e.clientX, y: e.clientY, v: view }; e.currentTarget.setPointerCapture(e.pointerId); };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => { const d = drag.current; if (d) setView({ ...d.v, tx: d.v.tx + e.clientX - d.x, ty: d.v.ty + e.clientY - d.y }); };
  const onPointerUp = () => { if (!drag.current) return; drag.current = null; if (lensStation) focusStation(lensStation); };
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const pan: Record<string, [number, number]> = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] };
    if (pan[e.key]) { e.preventDefault(); setView(v => ({ ...v, tx: v.tx + pan[e.key][0], ty: v.ty + pan[e.key][1] })); }
    else if (e.key === "[" || e.key === "]") { const i = Math.max(0, stations.findIndex(s => s.id === (lensStation ?? state.selectedStationId)));
      focusStation(stations[(i + (e.key === "]" ? 1 : stations.length - 1)) % stations.length].id); }
    else if (e.key === "+" || e.key === "=" || e.key === "-") { e.preventDefault(); setView(v => zoomAt(v, L.cx, L.cy, e.key === "-" ? 1 / 1.25 : 1.25)); }
  };
  useEffect(() => { const svg = root.current?.querySelector<SVGSVGElement>("svg.story-map"); if (!svg) return;
    const wheel = (e: WheelEvent) => { e.preventDefault(); const r = svg.getBoundingClientRect(); setView(v => zoomAt(v, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015))); };
    svg.addEventListener("wheel", wheel, { passive: false }); return () => svg.removeEventListener("wheel", wheel); }, []);

  const ocean = lensStation === null;
  const lensMeta = manifest.stations.find(s => s.station_id === lensStation) ?? selected.station;
  const aSel = selected.station.station_id === lensMeta.station_id ? selected : { station: lensMeta, status: "loading" as const, records: null, error: null };
  const title = ocean ? { name: "Open Pacific", sub: reading ? `nearest published contours: ${reading.a} h and ${reading.b} h` : "no published contour nearby" }
    : { name: lensMeta.name, sub: `${lensMeta.station_type === "dart" ? "Deep-ocean DART buoy" : "Coastal tide gauge"} · ${clockLabel(t)} · ${utcAt(manifest.event.origin_time_utc, t)}` };
  const b = params.compare ? props.pinned : null;

  if (!geometry) return <main className="story story--loading" ref={root}>{props.geometryError ? <div role="alert"><p>{props.geometryError}</p><button type="button" onClick={props.onRetryGeometry}>Retry map</button></div> : <p role="status">Loading the verified map…</p>}</main>;
  return <main className="story" ref={root} data-ocean={ocean ? "1" : "0"}>
    <svg className="story-map" width={size.w} height={size.h} tabIndex={0} role="img"
      aria-label="Pacific map of NOAA/NCEI published hourly travel-time contours with ten station records. Drag or use arrow keys to move the map under the lens; [ and ] change station; + and − zoom."
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onKeyDown={onKeyDown}>
      <WorldDefs coastline={coastline} contours={contours} initialT={t} smooth/>
      <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}><use href="#story-world"/></g>
      <Overlay view={view} stations={stations} epicentre={epicentre} anchors={anchors} t={t} aId={lensStation} bId={b?.station.station_id ?? null}/>
      <g className="story-leads" aria-hidden="true">
        <line x1={L.cx - L.r * 0.7} y1={L.cy - L.r * 0.7} x2={L.record.left + L.aw} y2={L.cy - L.r + 6}/>
        <line x1={L.cx + L.r * 0.7} y1={L.cy - L.r * 0.7} x2={L.support.left} y2={L.cy - L.r + 6}/>
        <line x1={L.cx} y1={L.cy + L.r} x2={L.cx} y2={L.read.top}/>
      </g>
      <Lens id="story-lens-a" view={view} cx={L.cx} cy={L.cy} centre={centre} r={L.r} mag={LENS_MAG} stations={stations} epicentre={epicentre} variant="a"/>
    </svg>
    <div className="story-lens-title" style={{ left: L.cx, top: L.titleTop }}><p className="story-lens-title__name">{title.name}</p><p className="story-lens-title__sub">{title.sub}</p></div>
    <Arms ocean={ocean} nearestName={nearest?.name ?? "none"} reading={reading} t={t} originUtc={manifest.event.origin_time_utc} a={aSel} b={b}
      windowId={state.windowId} productKey={state.productKey} onRetry={() => props.onRetryStation(lensMeta.station_id)} styles={{ record: L.record, support: L.support, read: L.read }}/>
    <aside className="story-column" aria-label="Story">
      <p className="story-kicker">Pacific · 11 March 2011</p>
      <h1 className="story-title">How the published tsunami clock spread</h1>
      <p className="story-small">NOAA/NCEI travel-time contours, one line per hour after the 05:46 UTC Tōhoku origin.</p>
      {props.layersError && <div role="alert" className="story-alert"><p>Published contour layer unavailable: {props.layersError}</p><button type="button" onClick={props.onRetryLayers}>Retry contours</button></div>}
      <h2 className="story-h">Station records</h2>
      {(["dart", "coastal"] as const).map(kind => <div key={kind}><p className="story-small">{kind === "dart" ? "◆ Deep-ocean DART" : "● Coastal gauges"}</p>
        {stations.filter(s => s.type === kind).map(s => <button key={s.id} type="button" className={`story-chip${s.id === lensStation ? " story-chip--on" : ""}`} aria-pressed={s.id === lensStation} onClick={() => focusStation(s.id)}>{s.name}</button>)}</div>)}
      <p className="story-credits">NOAA/NCEI travel-time layer 17 · NOAA CO-OPS, NCEI DART, UHSLC, IOC records · Natural Earth 1:50m · Equal Earth, 160° W. Internal descriptive evidence only.</p>
    </aside>
    <p className="story-sr" aria-live="polite">{`${title.name}. ${title.sub}. Clock ${clockLabel(Math.floor(t))}.`}</p>
  </main>;
}
