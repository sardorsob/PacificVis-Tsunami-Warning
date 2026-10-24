import { T_MAX } from "./clock";
import type { StepId } from "./steps";

export type StoryParams = { t: number; compare: boolean; step: StepId | "explore" };
export const STORY_FIELDS = ["t", "cmp", "step"] as const;

export function parseStoryParams(search: string): { params: StoryParams; issues: string[] } {
  const q = new URLSearchParams(search), issues: string[] = [];
  const params: StoryParams = { t: 0, compare: false, step: 1 };
  const t = q.get("t");
  if (t !== null) {
    const n = Number(t);
    if (!Number.isFinite(n)) issues.push("Invalid story clock: start restored.");
    else { params.t = Math.max(0, Math.min(T_MAX, n)); if (n !== params.t) issues.push(`Story clock limited to 0–${T_MAX} h.`); }
  }
  const cmp = q.get("cmp");
  if (cmp !== null) { if (cmp === "1" || cmp === "0") params.compare = cmp === "1"; else issues.push("Invalid compare flag: off restored."); }
  const step = q.get("step");
  if (step !== null) {
    if (step === "explore") params.step = "explore";
    else if (/^[1-6]$/.test(step)) params.step = Number(step) as StepId;
    else issues.push("Invalid story step: step 1 restored.");
  }
  return { params, issues };
}
export const storyQuery = (p: StoryParams) => `t=${Math.round(p.t * 100) / 100}&cmp=${p.compare ? 1 : 0}&step=${p.step}`;
