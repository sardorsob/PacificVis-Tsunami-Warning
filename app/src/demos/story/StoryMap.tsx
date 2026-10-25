import { memo, useMemo } from "react";
import { hourPaths, linePath, type Coastline, type ContourFeature, type Pt } from "./layers";
import { contourColour } from "./palette";
import { contourStyle, nextHaloOpacity, pulseWidth } from "./reveal";

/** Screen transform of the stage: screen = map·k + (tx, ty). Map units are SVG-space metres. */
export type View = { k: number; tx: number; ty: number };
export const toScreen = (v: View, p: Pt): Pt => [p[0] * v.k + v.tx, p[1] * v.k + v.ty];
export const toMap = (v: View, x: number, y: number): Pt => [(x - v.tx) / v.k, (y - v.ty) / v.k];
export const K_MIN = 2e-5, K_MAX = 6e-4;
export function fitView(crop: [number, number, number, number], width: number, height: number, inset = { l: 0, r: 0, t: 0, b: 0 }): View {
  const w = crop[2] - crop[0], h = crop[3] - crop[1], aw = Math.max(1, width - inset.l - inset.r), ah = Math.max(1, height - inset.t - inset.b);
  const k = Math.min(aw / w, ah / h);
  return { k, tx: inset.l + (aw - w * k) / 2 - crop[0] * k, ty: inset.t + (ah - h * k) / 2 - crop[1] * k };
}
export const centreOn = (v: View, p: Pt, sx: number, sy: number): View => ({ k: v.k, tx: sx - p[0] * v.k, ty: sy - p[1] * v.k });
export function zoomAt(v: View, x: number, y: number, factor: number): View {
  const m = toMap(v, x, y), k = Math.max(K_MIN, Math.min(K_MAX, v.k * factor));
  return { k, tx: x - m[0] * k, ty: y - m[1] * k };
}
/** Two-finger gesture from its start: zoom by the finger spread, and keep the map point under the fingers' midpoint. */
export function pinchView(v: View, from: [Pt, Pt], to: [Pt, Pt]): View {
  const mid = (p: [Pt, Pt]): Pt => [(p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2];
  const spread = (p: [Pt, Pt]) => Math.max(1, Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]));
  const m0 = mid(from), m1 = mid(to), k = Math.max(K_MIN, Math.min(K_MAX, v.k * spread(to) / spread(from)));
  return centreOn({ ...v, k }, toMap(v, m0[0], m0[1]), m1[0], m1[1]);
}

export const WORLD_ID = "story-world";
type WorldProps = { coastline: Coastline; contours: ContourFeature[]; initialT: number; smooth: boolean };
/** The map drawn once in <defs>; the stage and every lens <use> it. Contour styling is updated imperatively by paintContours. */
export const WorldDefs = memo(function WorldDefs({ coastline, contours, initialT, smooth }: WorldProps) {
  const paths = useMemo(() => hourPaths(contours), [contours]);
  const index = useMemo(() => new Set(contours.filter(f => f.index).map(f => f.hours)), [contours]);
  const land = useMemo(() => linePath(coastline.parts.filter((_, i) => coastline.closed[i]), true), [coastline]);
  const coast = useMemo(() => linePath(coastline.parts), [coastline]);
  return <defs>
    <filter id="story-land-shadow" x="-5%" y="-5%" width="110%" height="120%"><feDropShadow dx="0" dy="30000" stdDeviation="40000" floodColor="#000" floodOpacity="0.6"/></filter>
    <g id={WORLD_ID}>
      <path className="story-land" d={land} filter="url(#story-land-shadow)"/>
      <path className="story-coast" d={coast} vectorEffect="non-scaling-stroke"/>
      <path className="story-halo story-halo--next" d="" fill="none" strokeWidth="7" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      <path className="story-halo story-halo--front" d="" fill="none" strokeWidth="9" strokeOpacity="0.22" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      {[...paths].map(([h, d]) => { const s = contourStyle(h, initialT, smooth, index.has(h));
        return <path key={h} className="story-contour" data-h={h} data-index={index.has(h) ? "1" : "0"} d={d} fill="none" stroke={contourColour(h)} strokeOpacity={s.opacity} strokeWidth={s.width} vectorEffect="non-scaling-stroke"/>; })}
    </g>
  </defs>;
}, (a, b) => a.coastline === b.coastline && a.contours === b.contours);

/** Per-frame contour styling without React: opacity/width by clock, pulses, front and next halos. */
export function paintContours(root: ParentNode, t: number, pulses: Map<number, number>, now: number, paths: Map<number, string>): void {
  const smooth = true;
  root.querySelectorAll<SVGPathElement>(".story-contour").forEach(p => {
    const h = Number(p.dataset.h), s = contourStyle(h, t, smooth, p.dataset.index === "1"), start = pulses.get(h);
    p.setAttribute("stroke-opacity", start === undefined ? s.opacity.toFixed(3) : "1");
    p.setAttribute("stroke-width", (start === undefined ? s.width : pulseWidth(s.width, now - start)).toFixed(2));
  });
  const front = Math.floor(t), next = front + 1;
  const f = root.querySelector(".story-halo--front"), n = root.querySelector(".story-halo--next");
  f?.setAttribute("d", front >= 1 ? paths.get(front) ?? "" : ""); f?.setAttribute("stroke", contourColour(Math.max(1, front)));
  n?.setAttribute("d", smooth ? paths.get(next) ?? "" : ""); n?.setAttribute("stroke", contourColour(next)); n?.setAttribute("stroke-opacity", nextHaloOpacity(t, smooth).toFixed(3));
}

export type MapStation = { id: string; name: string; type: "coastal" | "dart"; xy: Pt };
export function star(cx: number, cy: number, outer: number, inner: number): string {
  let d = ""; for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, q = i % 2 ? inner : outer; d += `${i ? "L" : "M"}${(cx + q * Math.cos(a)).toFixed(1)} ${(cy + q * Math.sin(a)).toFixed(1)}`; }
  return `${d}Z`;
}
export function Marker({ s, x, y, size, filled, ring }: { s: MapStation; x: number; y: number; size: number; filled: boolean; ring?: string }) {
  const cls = `story-marker story-marker--${s.type}${filled ? " story-marker--filled" : ""}`;
  return <g aria-hidden="true">
    {ring && <circle cx={x} cy={y} r={size + 5} fill="none" stroke={ring} strokeWidth="2"/>}
    {s.type === "dart" ? <rect className={cls} x={x - size} y={y - size} width={2 * size} height={2 * size} transform={`rotate(45 ${x} ${y})`}/> : <circle className={cls} cx={x} cy={y} r={size}/>}
  </g>;
}
type OverlayProps = { view: View; stations: MapStation[]; epicentre: Pt; anchors: Map<number, Pt>; t: number; aId: string | null; bId: string | null };
/** Screen-space marks: constant size at any zoom. */
export function Overlay({ view, stations, epicentre, anchors, t, aId, bId }: OverlayProps) {
  const [ex, ey] = toScreen(view, epicentre);
  return <g className="story-overlay">
    <path d={star(ex, ey, 7, 3)} className="story-epicentre"/>
    <text x={ex + 10} y={ey - 8} className="story-label story-label--strong">Tōhoku origin · 05:46 UTC</text>
    {[...anchors].filter(([h]) => h <= t).map(([h, p]) => { const [x, y] = toScreen(view, p); return <text key={h} x={x} y={y} className="story-label" textAnchor="middle">{h} h</text>; })}
    {stations.map(s => { const [x, y] = toScreen(view, s.xy), isA = s.id === aId, isB = s.id === bId;
      return <g key={s.id}><Marker s={s} x={x} y={y} size={isA || isB ? 5 : 4} filled={isA || isB} ring={isB ? "var(--story-b)" : undefined}/>
        {isB && <text x={x + 12} y={y + 4} className="story-label story-label--strong">B · {s.name}</text>}</g>; })}
  </g>;
}
