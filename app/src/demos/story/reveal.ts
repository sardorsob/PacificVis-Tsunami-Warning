/** How a published contour looks at a clock time. Only opacity and width change; no line moves. */
export type Style = { opacity: number; width: number };
export const HIDDEN_OPACITY = 0.055;
export const PULSE_MS = 900;

const baseOpacity = (hour: number) => (hour <= 24 ? 0.95 : Math.max(0.15, 0.6 - (hour - 24) * 0.03));
export function contourStyle(hour: number, t: number, smooth: boolean, isIndex: boolean): Style {
  const width = isIndex ? 1.7 : 0.8, base = baseOpacity(hour), next = Math.floor(t) + 1;
  if (hour <= t) return { opacity: base, width };
  if (smooth && hour === next) { const f = t - Math.floor(t); return { opacity: HIDDEN_OPACITY + (base - HIDDEN_OPACITY) * f * f, width }; }
  return { opacity: HIDDEN_OPACITY, width };
}
/** Stroke width while an hour pulses after the clock crosses it (ease-out over 0.9 s). */
export function pulseWidth(base: number, elapsedMs: number): number {
  const p = Math.min(1, Math.max(0, elapsedMs / PULSE_MS)), e = 1 - (1 - p) ** 2;
  return base + 4.5 * (1 - e);
}
/** Halo on the next hour, proportional to the fraction of the hour elapsed (smooth reveal only). */
export const nextHaloOpacity = (t: number, smooth: boolean) => (smooth ? 0.16 * (t - Math.floor(t)) : 0);
