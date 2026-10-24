/** Lens geometry. Lens size and leader length never encode a quantity. */
import type { Pt } from "./layers";
export const LENS_RADIUS = 108, LENS_MAG = 3.2, B_LENS_RADIUS = 58, B_LENS_MAG = 3;

/** Map-unit radius the lens magnifies at the current stage scale (px per map unit). */
export const footprintRadius = (lensPx: number, scale: number, mag: number) => lensPx / (scale * mag);
/** Nearest station inside the footprint, or null over empty ocean. */
export function capture(center: Pt, radius: number, stations: { id: string; xy: Pt }[]): string | null {
  let best: string | null = null, bestD = Infinity;
  for (const s of stations) { const d = Math.hypot(s.xy[0] - center[0], s.xy[1] - center[1]); if (d < radius && d < bestD) { bestD = d; best = s.id; } }
  return best;
}
/** Fixed screen slot for the pinned B lens: under the right arm, above the clock bar. */
export const slot = (cx: number, cy: number, r: number, gap: number, armWidth: number, viewH: number): Pt =>
  [cx + r + gap + armWidth / 2, Math.min(viewH - 170, cy + r + 150)];
