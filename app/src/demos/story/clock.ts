/** The one owner of story time: hours after the 05:46:24 UTC origin. */
export const T_MAX = 30;
/** Published hours per second of playback (0–30 h in 12.5 s). */
export const PLAY_RATE = 2.4;
export type Clock = { t: number; playing: boolean };
type Step = { clock: Clock; crossed: number[] };

const clamp = (t: number) => Math.max(0, Math.min(T_MAX, t));
function crossedBetween(from: number, to: number): number[] {
  const out: number[] = [];
  for (let h = Math.floor(from) + 1; h <= Math.floor(to); h++) out.push(h);
  return out;
}
export function tick(c: Clock, dtSeconds: number): Step {
  if (!c.playing) return { clock: c, crossed: [] };
  const t = clamp(c.t + dtSeconds * PLAY_RATE);
  return { clock: { t, playing: t < T_MAX }, crossed: crossedBetween(c.t, t) };
}
export function seek(c: Clock, target: number): Step {
  const t = clamp(target);
  return { clock: { ...c, t }, crossed: t > c.t ? crossedBetween(c.t, t) : [] };
}
export function toggle(c: Clock): Clock {
  if (c.playing) return { ...c, playing: false };
  return { t: c.t >= T_MAX ? 0 : c.t, playing: true };
}
export function clockLabel(t: number): string {
  let h = Math.floor(t), m = Math.round((t - h) * 60);
  if (m === 60) { h += 1; m = 0; }
  return `+${h} h ${String(m).padStart(2, "0")} min`;
}
export function utcAt(originUtc: string, t: number): string {
  return `${new Date(Date.parse(originUtc) + t * 3_600_000).toISOString().slice(11, 16)} UTC`;
}
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
/** UTC calendar day at the clock time, e.g. "Friday 11 March 2011" (fixed format, no locale dependence). */
export function utcDayAt(originUtc: string, t: number): string {
  const d = new Date(Date.parse(originUtc) + t * 3_600_000);
  return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
