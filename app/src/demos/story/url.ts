import { T_MAX } from "./clock";
import type { Pt } from "./layers";
import { STEPS, type StepId } from "./steps";

/** Story fields of the URL. With selected/pinned/window/product they restore the whole screen at any viewport size. */
export type StoryParams = {
  t: number; compare: boolean; step: StepId | "explore";
  /** Lens centre in display-CRS kilometres; null = the step's authored target (or the selected station). */
  at: Pt | null;
  /** Zoom relative to the fitted Pacific. */
  z: number;
  /** In Explore: the step to resume. */
  from: StepId | null;
};
export const STORY_FIELDS = ["t", "cmp", "step", "at", "z", "from"] as const;
const Z_MIN = 0.25, Z_MAX = 20;
const stepId = (v: string): StepId | null => /^[1-6]$/.test(v) ? Number(v) as StepId : null;

export function parseStoryParams(search: string): { params: StoryParams; issues: string[] } {
  const q = new URLSearchParams(search), issues: string[] = [];
  const params: StoryParams = { t: 0, compare: false, step: 1, at: null, z: 1, from: null };
  const step = q.get("step");
  if (step !== null) {
    if (step === "explore") params.step = "explore";
    else if (stepId(step)) params.step = stepId(step)!;
    else issues.push("Invalid story step: step 1 restored.");
  }
  // A hand-written step link opens that step as authored; the app always writes t and cmp itself.
  if (typeof params.step === "number") { const s = STEPS[params.step - 1]; params.t = s.play ? s.play[0] : s.t; params.compare = s.compare; }
  const t = q.get("t");
  if (t !== null) {
    const n = Number(t);
    if (!Number.isFinite(n)) issues.push("Invalid story clock: the step's time restored.");
    else { params.t = Math.max(0, Math.min(T_MAX, n)); if (n !== params.t) issues.push(`Story clock limited to 0–${T_MAX} h.`); }
  }
  const cmp = q.get("cmp");
  if (cmp !== null) { if (cmp === "1" || cmp === "0") params.compare = cmp === "1"; else issues.push("Invalid compare flag: the step's setting restored."); }
  const at = q.get("at");
  if (at !== null) {
    const xy = at.split(",").map(Number);
    if (xy.length === 2 && xy.every(Number.isFinite)) params.at = [xy[0], xy[1]];
    else issues.push("Invalid lens position: the step's view restored.");
  }
  const z = q.get("z");
  if (z !== null) {
    const n = Number(z);
    if (!Number.isFinite(n)) issues.push("Invalid zoom: default restored.");
    else { params.z = Math.max(Z_MIN, Math.min(Z_MAX, n)); if (n !== params.z) issues.push(`Zoom limited to ${Z_MIN}–${Z_MAX}.`); }
  }
  const from = q.get("from");
  if (from !== null) { if (stepId(from)) params.from = stepId(from); else issues.push("Invalid resume step: step 1 will be used."); }
  return { params, issues };
}
/** Defaults are left out so a plain story link stays short. */
export function storyQuery(p: StoryParams): string {
  const q = [`t=${Math.round(p.t * 100) / 100}`, `cmp=${p.compare ? 1 : 0}`, `step=${p.step}`];
  if (p.at) q.push(`at=${Math.round(p.at[0])},${Math.round(p.at[1])}`);
  if (p.z !== 1) q.push(`z=${Math.round(p.z * 100) / 100}`);
  if (p.from !== null) q.push(`from=${p.from}`);
  return q.join("&");
}
