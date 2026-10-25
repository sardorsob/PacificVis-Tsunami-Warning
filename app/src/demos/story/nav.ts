import type { Pt } from "./layers";
import { STEPS, type StepId } from "./steps";
import type { StoryParams } from "./url";

/** Everything the URL restores: story fields plus station A (selected) and B (pinned). */
export type StoryNav = StoryParams & { a: string; b: string | null };
export type NavEvent =
  | { type: "next" } | { type: "back" } | { type: "returnToStep" } | { type: "explore" } | { type: "resumeStory" }
  | { type: "compareOn" } | { type: "compareOff" } | { type: "pin"; id: string }
  /** explicit: a station chosen by name (push); otherwise a drag, zoom or key move settling (replace). */
  | { type: "lensSettle"; at: Pt; z: number; station: string | null; explicit?: boolean }
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
export type NavResult = { nav: StoryNav; history: "push" | "replace" | "back" | "none"; effects: Effect[] };

const stay = (nav: StoryNav): NavResult => ({ nav, history: "none", effects: [] });
function enter(nav: StoryNav, id: StepId, ctx: NavContext, history: NavResult["history"]): NavResult {
  const step = STEPS[id - 1], animate = !!step.play && ctx.motionOK;
  const lensStation = "station" in step.lens ? step.lens.station : null;
  const effects: Effect[] = [{ kind: "stopPlay" }, { kind: "aim", instant: false }, { kind: "focus", target: "step" }];
  if (animate) effects.push({ kind: "play", from: step.play![0], until: step.play![1] });
  return {
    nav: { ...nav, step: id, from: null, t: animate ? step.play![0] : step.t, compare: step.compare, at: null, z: 1,
      a: lensStation ?? nav.a, b: step.b ?? nav.b },
    history, effects,
  };
}

/**
 * The navigation contract (canonical in context/story/STORYBOARD.md): explicit actions push, passive ones replace,
 * browser Back/Forward restores without writing, and story Back uses history.back() when the previous entry is that step.
 */
export function reduce(nav: StoryNav, ev: NavEvent, ctx: NavContext): NavResult {
  const step = typeof nav.step === "number" ? nav.step : null;
  switch (ev.type) {
    case "next":
      if (step === null) return stay(nav);
      return step < STEPS.length ? enter(nav, (step + 1) as StepId, ctx, "push") : reduce(nav, { type: "explore" }, ctx);
    case "back":
      if (step === null || step === 1) return stay(nav);
      if (ctx.prevEntryStep === step - 1) return { nav, history: "back", effects: [{ kind: "stopPlay" }] };
      return enter(nav, (step - 1) as StepId, ctx, "replace");
    case "returnToStep":
      return step === null ? stay(nav) : enter(nav, step, ctx, "replace");
    case "explore":
      return { nav: { ...nav, step: "explore", from: step ?? nav.from }, history: "push", effects: [{ kind: "focus", target: "panel" }] };
    case "resumeStory":
      return enter(nav, nav.from ?? 1, ctx, "push");
    case "compareOn": {
      const valid = nav.b !== null && nav.b !== nav.a && ctx.stationIds.includes(nav.b);
      const b = valid ? nav.b : ctx.stationIds.find(id => id !== nav.a) ?? null;
      return { nav: { ...nav, compare: true, b }, history: "push", effects: [] };
    }
    case "compareOff":
      return { nav: { ...nav, compare: false }, history: "push", effects: [] };
    case "pin":
      if (ev.id === nav.a || !ctx.stationIds.includes(ev.id)) return stay(nav);
      return { nav: { ...nav, b: ev.id }, history: "push", effects: [] };
    case "lensSettle":
      return { nav: { ...nav, at: ev.at, z: ev.z, a: ev.station ?? nav.a }, history: ev.explicit ? "push" : "replace", effects: [] };
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
