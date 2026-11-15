import type { Pt } from "./layers";
import { STEPS, type StepId } from "./steps";
import type { StoryParams } from "./url";

/** Everything the URL restores: story fields plus station A (selected) and B (pinned). */
export type StoryNav = StoryParams & { a: string; b: string | null };
export type NavEvent =
  | { type: "next" } | { type: "back" } | { type: "returnToStep" } | { type: "explore" } | { type: "resumeStory" }
  | { type: "compareOn" } | { type: "compareOff" } | { type: "pin"; id: string } | { type: "unpin" }
  /** explicit: a station chosen by name (push); otherwise a drag, zoom or key move settling (replace). */
  | { type: "lensSettle"; at: Pt | null; z: number; station: string | null; explicit?: boolean }
  | { type: "seekEnd"; t: number } | { type: "playEnd"; t: number }
  | { type: "popstate"; nav: StoryNav } | { type: "escape" };
type Effect =
  | { kind: "stopPlay" } | { kind: "play"; from: number; until: number }
  /** Move the lens to `nav.at`, or to the step's authored target when `at` is null. */
  | { kind: "aim"; instant: boolean }
  | { kind: "focus"; target: "step" | "panel" } | { kind: "collapseSheet" };
export type NavContext = {
  motionOK: boolean; stationIds: readonly string[];
  /** The step recorded in the previous history entry, if this session wrote it. */
  prevEntryStep?: StoryNav["step"] | null;
  evidenceOpen?: boolean; playing?: boolean; sheetExpanded?: boolean;
};
/** `entered`: the result enters `nav.step` as authored; when that step lives in another view, event or All events, the writer goes there. */
export type NavResult = { nav: StoryNav; history: "push" | "replace" | "back" | "none"; effects: Effect[]; entered?: true };
/** The step recorded in the previous history entry (written by DemoApp's writers), if any. */
export function historyPrev(): StoryNav["step"] | null {
  const prev = typeof window === "undefined" ? null : (window.history.state as { prev?: unknown } | null)?.prev;
  return typeof prev === "number" || prev === "explore" ? prev as StoryNav["step"] : null;
}
/** A step entered across a remount (another view, event or All events, or Back/Forward onto one) leaves its id here; that step's panel takes focus
 * as it mounts and clears it. */
// ponytail: one module-level request instead of a focus prop through DemoApp, both demos and every view; it holds one id and is read once.
export const stepFocus: { step: StepId | null } = { step: null };
/** The history entry DemoApp writes: a push records the step it came from; a replace keeps this entry's own previous step. */
export function entryFor(current: unknown, step: StoryNav["step"], history: "push" | "replace") {
  const c = current as { step?: unknown; prev?: unknown } | null;
  return { step, prev: (history === "push" ? c?.step : c?.prev) ?? null };
}
/** On reload, history.state survives: keep the previous step it records when it belongs to this step. */
export function keptPrev(state: unknown, step: StoryNav["step"]): StoryNav["step"] | null {
  const s = state as { step?: unknown; prev?: unknown } | null;
  const prev = s?.step === step ? s.prev : null;
  return typeof prev === "number" || prev === "explore" ? prev as StoryNav["step"] : null;
}

const stay = (nav: StoryNav): NavResult => ({ nav, history: "none", effects: [] });
/** B is never A: keep a valid pinned B, else pin the first station that is not A. */
const validB = (nav: StoryNav, ids: readonly string[]) =>
  nav.b !== null && nav.b !== nav.a && ids.includes(nav.b) ? nav.b : ids.find(id => id !== nav.a) ?? null;
/** After A moves (a step's lens station, a lens settle), re-pick B if A landed on it. */
export const distinct = (nav: StoryNav, ids: readonly string[]): StoryNav => nav.b === nav.a ? { ...nav, b: validB(nav, ids) } : nav;
function enter(nav: StoryNav, id: StepId, ctx: NavContext, history: NavResult["history"]): NavResult {
  const step = STEPS[id], animate = !!step.play && ctx.motionOK;
  const lensStation = "station" in step.lens ? step.lens.station : null;
  const effects: Effect[] = [{ kind: "stopPlay" }, { kind: "aim", instant: false }, { kind: "focus", target: "step" }];
  if (animate) effects.push({ kind: "play", from: step.play![0], until: step.play![1] });
  return {
    nav: distinct({ ...nav, step: id, from: null, t: animate ? step.play![0] : step.t, compare: step.compare, at: null, z: 1,
      a: lensStation ?? nav.a, b: step.b ?? nav.b }, ctx.stationIds),
    history, effects, entered: true,
  };
}
const LAST = STEPS.length - 1;

/**
 * The navigation contract (canonical in context/story/STORYBOARD.md): explicit actions push, passive ones replace,
 * browser Back/Forward restores without writing, and story Back uses history.back() when the previous entry is that step.
 */
export function reduce(nav: StoryNav, ev: NavEvent, ctx: NavContext): NavResult {
  const step = typeof nav.step === "number" ? nav.step : null;
  switch (ev.type) {
    case "next": // the last step has no Next: the reader picks an event there
      return step === null || step === LAST ? stay(nav) : enter(nav, (step + 1) as StepId, ctx, "push");
    case "back":
      if (step === null || step === 0) return stay(nav);
      if (ctx.prevEntryStep === step - 1) return { nav, history: "back", effects: [{ kind: "stopPlay" }] };
      return enter(nav, (step - 1) as StepId, ctx, "replace");
    case "returnToStep":
      return step === null ? stay(nav) : enter(nav, step, ctx, "replace");
    case "explore":
      return { nav: { ...nav, step: "explore", from: step ?? nav.from }, history: "push", effects: [{ kind: "focus", target: "panel" }] };
    case "resumeStory": // a step carried into another view (Story showing step 7), else the step Explore was entered from
      return enter(nav, step ?? nav.from ?? 1, ctx, "push");
    case "compareOn":
      return { nav: { ...nav, compare: true, b: validB(nav, ctx.stationIds) }, history: "push", effects: [] };
    case "compareOff":
      return { nav: { ...nav, compare: false }, history: "push", effects: [] };
    case "pin":
      if (ev.id === nav.a || !ctx.stationIds.includes(ev.id)) return stay(nav);
      return { nav: { ...nav, b: ev.id }, history: "push", effects: [] };
    case "unpin":
      return nav.b === null ? stay(nav) : { nav: { ...nav, b: null, compare: false }, history: "push", effects: [] };
    case "lensSettle":
      return { nav: distinct({ ...nav, at: ev.at, z: ev.z, a: ev.station ?? nav.a }, ctx.stationIds), history: ev.explicit ? "push" : "replace",
        effects: [] };
    case "seekEnd":
    case "playEnd":
      return { nav: { ...nav, t: ev.t }, history: "replace", effects: [] };
    case "popstate":
      return { nav: ev.nav, history: "none", effects: [{ kind: "stopPlay" }, { kind: "aim", instant: true }, { kind: "focus", target: "step" }] };
    case "escape":
      if (ctx.evidenceOpen) return stay(nav); // the native modal <dialog> closes itself on Escape
      if (ctx.playing) return { nav, history: "replace", effects: [{ kind: "stopPlay" }] }; // a pause, recorded like Pause
      if (ctx.sheetExpanded) return { nav, history: "none", effects: [{ kind: "collapseSheet" }] };
      return stay(nav);
  }
}
