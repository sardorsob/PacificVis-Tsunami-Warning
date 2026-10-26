import { memo, useMemo } from "react";
import type { DemoGeometry, DemoManifest } from "../types";
import { hourPaths, labelAnchors, linePath, toSvg, type StoryLayers, type Coastline, type ContourFeature, type Pt } from "./layers";
import { contourColour } from "./palette";
import { contourStyle, nextHaloOpacity, pulseWidth } from "./reveal";

/** Screen transform of the stage: screen = map·k + (tx, ty). Map units are SVG-space metres. */
export type View = { k: number; tx: number; ty: number };
export const toScreen = (v: View, p: Pt): Pt => [p[0] * v.k + v.tx, p[1] * v.k + v.ty];
export const toMap = (v: View, x: number, y: number): Pt => [(x - v.tx) / v.k, (y - v.ty) / v.k];
/** The fitted Pacific every view frames (SVG-space metres: x0, y0, x1, y1). */
export const PACIFIC_CROP: [number, number, number, number] = [-6.4e6, -6.3e6, 8.9e6, 4.6e6];
/** Scale limits [min, max], set by the caller from the fitted scale so every screen shares one zoom range. */
export type KLimits = [number, number];
export const clampK = (k: number, [lo, hi]: KLimits) => Math.max(lo, Math.min(hi, k));
export function fitView(crop: [number, number, number, number], width: number, height: number, inset = { l: 0, r: 0, t: 0, b: 0 }): View {
  const w = crop[2] - crop[0], h = crop[3] - crop[1], aw = Math.max(1, width - inset.l - inset.r), ah = Math.max(1, height - inset.t - inset.b);
  const k = Math.min(aw / w, ah / h);
  return { k, tx: inset.l + (aw - w * k) / 2 - crop[0] * k, ty: inset.t + (ah - h * k) / 2 - crop[1] * k };
}
export const centreOn = (v: View, p: Pt, sx: number, sy: number): View => ({ k: v.k, tx: sx - p[0] * v.k, ty: sy - p[1] * v.k });
export function zoomAt(v: View, x: number, y: number, factor: number, limits: KLimits): View {
  const m = toMap(v, x, y), k = clampK(v.k * factor, limits);
  return { k, tx: x - m[0] * k, ty: y - m[1] * k };
}
/** Two-finger gesture from its start: zoom by the finger spread, and keep the map point under the fingers' midpoint. */
export function pinchView(v: View, from: [Pt, Pt], to: [Pt, Pt], limits: KLimits): View {
  const mid = (p: [Pt, Pt]): Pt => [(p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2];
  const spread = (p: [Pt, Pt]) => Math.max(1, Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]));
  const m0 = mid(from), m1 = mid(to), k = clampK(v.k * spread(to) / spread(from), limits);
  return centreOn({ ...v, k }, toMap(v, m0[0], m0[1]), m1[0], m1[1]);
}

export const WORLD_ID = "story-world";
/** `paths` is hourPaths(contours), computed once by the caller (it also drives the halos). */
type WorldProps = { coastline: Coastline; contours: ContourFeature[]; paths: Map<number, string>; initialT: number };
/** The map drawn once in <defs>; the stage and every lens <use> it. Contour styling is updated imperatively by paintContours. */
export const WorldDefs = memo(function WorldDefs({ coastline, contours, paths, initialT }: WorldProps) {
  const index = useMemo(() => new Set(contours.filter(f => f.index).map(f => f.hours)), [contours]);
  const land = useMemo(() => linePath(coastline.parts.filter((_, i) => coastline.closed[i]), true), [coastline]);
  const coast = useMemo(() => linePath(coastline.parts), [coastline]);
  return <defs>
    <filter id="story-land-shadow" x="-5%" y="-5%" width="110%" height="120%">
      <feDropShadow dx="0" dy="30000" stdDeviation="40000" floodColor="#000" floodOpacity="0.6"/>
    </filter>
    <g id={WORLD_ID}>
      <path className="story-land" d={land} filter="url(#story-land-shadow)"/>
      <path className="story-coast" d={coast} vectorEffect="non-scaling-stroke"/>
      <path className="story-halo story-halo--next" d="" fill="none" strokeWidth="7" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      <path className="story-halo story-halo--front" d="" fill="none" strokeWidth="9" strokeOpacity="0.22" strokeLinecap="round"
        vectorEffect="non-scaling-stroke"/>
      {[...paths].map(([h, d]) => { const s = contourStyle(h, initialT, index.has(h));
        return <path key={h} className="story-contour" data-h={h} data-index={index.has(h) ? "1" : "0"} d={d} fill="none" stroke={contourColour(h)}
          strokeOpacity={s.opacity} strokeWidth={s.width} vectorEffect="non-scaling-stroke"/>; })}
    </g>
  </defs>;
}, (a, b) => a.coastline === b.coastline && a.contours === b.contours && a.paths === b.paths);

/** Per-frame contour styling without React: opacity/width by clock, pulses, front and next halos. */
export function paintContours(root: ParentNode, t: number, pulses: Map<number, number>, now: number, paths: Map<number, string>): void {
  root.querySelectorAll<SVGPathElement>(".story-contour").forEach(p => {
    const h = Number(p.dataset.h), s = contourStyle(h, t, p.dataset.index === "1"), start = pulses.get(h);
    p.setAttribute("stroke-opacity", start === undefined ? s.opacity.toFixed(3) : "1");
    p.setAttribute("stroke-width", (start === undefined ? s.width : pulseWidth(s.width, now - start)).toFixed(2));
  });
  const front = Math.floor(t), next = front + 1;
  const f = root.querySelector(".story-halo--front"), n = root.querySelector(".story-halo--next");
  f?.setAttribute("d", front >= 1 ? paths.get(front) ?? "" : ""); f?.setAttribute("stroke", contourColour(Math.max(1, front)));
  n?.setAttribute("d", paths.get(next) ?? ""); n?.setAttribute("stroke", contourColour(next)); n?.setAttribute("stroke-opacity", nextHaloOpacity(t).toFixed(3));
}

export type MapStation = { id: string; name: string; type: "coastal" | "dart"; xy: Pt };
/** The shared stage every view draws: stations and epicentre in SVG space, coastline (the verified v2 one until the 1:50m
 * layer loads, or if it fails), published contours with their hour paths and label anchors. */
export function useStage(manifest: DemoManifest, geometry: DemoGeometry | null, layers: StoryLayers | null) {
  const stationIds = useMemo(() => manifest.stations.map(s => s.station_id), [manifest]);
  const stations = useMemo<MapStation[]>(() => geometry ? manifest.stations.map(s => {
    const p = geometry.points.find(q => q.id === s.station_id)!;
    return { id: s.station_id, name: s.name, type: s.station_type, xy: toSvg([p.x, p.y]) };
  }) : [], [geometry, manifest]);
  const epicentre = useMemo<Pt>(() => {
    const p = geometry?.points.find(q => q.id === manifest.event.event_id); return p ? toSvg([p.x, p.y]) : [0, 0];
  }, [geometry, manifest]);
  const coastline = useMemo<Coastline>(() => {
    if (layers) return layers.coastline;
    const parts = geometry ? geometry.coastline.map(part => part.map(toSvg)) : [];
    return { parts, closed: parts.map(q => q.length > 3 && q[0][0] === q.at(-1)![0] && q[0][1] === q.at(-1)![1]) };
  }, [layers, geometry]);
  const contours = useMemo(() => layers?.contours ?? [], [layers]);
  const paths = useMemo(() => hourPaths(contours), [contours]);
  const anchors = useMemo(() => labelAnchors(contours, epicentre), [contours, epicentre]);
  return { stationIds, stations, epicentre, coastline, contours, paths, anchors };
}
export function star(cx: number, cy: number, outer: number, inner: number): string {
  let d = "";
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 5, q = i % 2 ? inner : outer;
    d += `${i ? "L" : "M"}${(cx + q * Math.cos(a)).toFixed(1)} ${(cy + q * Math.sin(a)).toFixed(1)}`;
  }
  return `${d}Z`;
}
export function Marker({ s, x, y, size, filled, ring }: { s: MapStation; x: number; y: number; size: number; filled: boolean; ring?: string }) {
  const cls = `story-marker story-marker--${s.type}${filled ? " story-marker--filled" : ""}`;
  return <g aria-hidden="true">
    {ring && <circle cx={x} cy={y} r={size + 5} fill="none" stroke={ring} strokeWidth="2"/>}
    {s.type === "dart"
      ? <rect className={cls} x={x - size} y={y - size} width={2 * size} height={2 * size} transform={`rotate(45 ${x} ${y})`}/>
      : <circle className={cls} cx={x} cy={y} r={size}/>}
  </g>;
}
type Circle = { cx: number; cy: number; r: number };
type Rect = { left: number; top: number; right: number; bottom: number };
/**
 * Where a map label goes: beside its point, flipped to the left near the right edge, kept on screen, and not drawn at
 * all for a point off screen, under a lens (the lens shows that spot magnified and its title names it) or under an
 * `avoid` box such as the lens title. `middle` centres it on the point.
 */
export function placeLabel(x: number, y: number, text: string, width: number, lenses: Circle[], align: "side" | "middle" = "side",
  avoid: Rect[] = []) {
  // ponytail: width from character count (11 px labels); measure with getComputedTextLength if labels change font.
  const w = text.length * 6.2 + 4, h = 12, gap = 10;
  if (x < -gap || x > width + gap || y < -gap) return null;  // off screen: its marker is gone, so is its label
  y = Math.max(y, h + 2); // a point on the top edge keeps its label on screen, just below the edge
  let anchor: "start" | "end" | "middle" = align === "middle" ? "middle" : "start", lx = align === "middle" ? x : x + gap;
  if (anchor === "start" && lx + w > width - 4) { anchor = "end"; lx = x - gap; }
  if (anchor === "start") lx = Math.max(4, lx);
  const left = anchor === "start" ? lx : anchor === "end" ? lx - w : lx - w / 2, top = y - h + 2;
  const under = lenses.some(c => {
    const nx = Math.max(left, Math.min(c.cx, left + w)), ny = Math.max(top, Math.min(c.cy, top + h));
    return (nx - c.cx) ** 2 + (ny - c.cy) ** 2 < c.r ** 2;
  });
  const covered = avoid.some(a => left < a.right && left + w > a.left && top < a.bottom && top + h > a.top);
  return under || covered ? null : { x: lx, y, anchor };
}
type OverlayProps = {
  view: View; stations: MapStation[]; epicentre: Pt; anchors: Map<number, Pt>; t: number; aId: string | null; bId: string | null;
  /** Lenses and boxes drawn over the map (screen px) and the screen width, so labels avoid them. */
  lenses?: Circle[]; avoid?: Rect[]; width: number; labelA?: boolean;
};
/** Screen-space marks: constant size at any zoom. */
export function Overlay(props: OverlayProps) {
  const { view, stations, epicentre, anchors, t, aId, bId, lenses = [], avoid = [], width, labelA = false } = props;
  const [ex, ey] = toScreen(view, epicentre);
  const label = (x: number, y: number, text: string, strong: boolean, align: "side" | "middle" = "side") => {
    const p = placeLabel(x, y, text, width, lenses, align, avoid);
    return p && <text x={p.x} y={p.y} textAnchor={p.anchor} className={`story-label${strong ? " story-label--strong" : ""}`}>{text}</text>;
  };
  return <g className="story-overlay">
    <path d={star(ex, ey, 7, 3)} className="story-epicentre"/>
    {label(ex, ey - 8, "Tōhoku origin · 05:46 UTC", true)}
    {[...anchors].filter(([h]) => h <= t).map(([h, p]) => {
      const [x, y] = toScreen(view, p); return <g key={h}>{label(x, y, `${h} h`, false, "middle")}</g>; })}
    {stations.map(s => { const [x, y] = toScreen(view, s.xy), isA = s.id === aId, isB = s.id === bId;
      return <g key={s.id}><Marker s={s} x={x} y={y} size={isA || isB ? 5 : 4} filled={isA || isB} ring={isB ? "var(--story-b)" : undefined}/>
        {(isB || (labelA && isA)) && label(x, y + 4, `${isB ? "B" : "A"} · ${s.name}`, true)}</g>; })}
  </g>;
}
