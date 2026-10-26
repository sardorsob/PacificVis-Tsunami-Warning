import type { Pt } from "./layers";
import { Marker, star, WORLD_ID, type MapStation, type View } from "./StoryMap";

type LensProps = {
  id: string; view: View; cx: number; cy: number; centre: Pt; r: number; mag: number;
  stations: MapStation[]; epicentre: Pt; variant: "a" | "b"; caption?: string;
};
/** A magnifier over the shared world: same map, same contours, larger. Its size carries no quantity. */
export function Lens({ id, view, cx, cy, centre, r, mag, stations, epicentre, variant, caption }: LensProps) {
  const K = view.k * mag, at = (p: Pt): Pt => [cx + (p[0] - centre[0]) * K, cy + (p[1] - centre[1]) * K];
  const inside = stations.map(s => ({ s, p: at(s.xy) })).filter(({ p }) => Math.hypot(p[0] - cx, p[1] - cy) <= r + 10);
  const [ex, ey] = at(epicentre);
  return <g className={`story-lens story-lens--${variant}`} aria-hidden="true">
    <defs><clipPath id={id}><circle cx={cx} cy={cy} r={r}/></clipPath></defs>
    <circle className="story-lens__bg" cx={cx} cy={cy} r={r}/>
    <g clipPath={`url(#${id})`}>
      <g transform={`translate(${cx},${cy}) scale(${K}) translate(${-centre[0]},${-centre[1]})`}><use href={`#${WORLD_ID}`}/></g>
      {inside.map(({ s, p }) => { const half = s.name.length * 3.1 + 2, fits = variant === "a"   // the name's box (y + 9 … y + 23) inside the rim
          && Math.hypot(Math.abs(p[0] - cx) + half, Math.max(Math.abs(p[1] + 9 - cy), Math.abs(p[1] + 23 - cy))) < r - 4;
        return <g key={s.id}><Marker s={s} x={p[0]} y={p[1]} size={6} filled/>
          {fits && <text x={p[0]} y={p[1] + 20} textAnchor="middle" className="story-label story-label--strong">{s.name}</text>}</g>; })}
      {Math.hypot(ex - cx, ey - cy) < r && <path d={star(ex, ey, 9, 4)} className="story-epicentre"/>}
      {variant === "a" && <path d={`M${cx - 7} ${cy}H${cx + 7}M${cx} ${cy - 7}V${cy + 7}`} className="story-lens__cross"/>}
    </g>
    <circle className="story-lens__ring" cx={cx} cy={cy} r={r}/>
    {/* Right-aligned to the lens: every tier keeps the lens's right edge inside the map area. */}
    {caption && <text x={cx + r} y={cy + r + 16} textAnchor="end" className="story-label story-label--strong">{caption}</text>}
  </g>;
}
