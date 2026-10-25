import { describe, expect, it } from "vitest";
import { STATION_IDS } from "../loader";
import { reduce, type NavContext, type StoryNav } from "./nav";
import { parseStoryParams, storyQuery } from "./url";

const ctx: NavContext = { motionOK: true, stationIds: STATION_IDS };
const at = (step: StoryNav["step"], extra: Partial<StoryNav> = {}): StoryNav =>
  ({ step, from: null, t: 0, compare: false, at: null, z: 1, a: "1617760", b: "saip", ...extra });
const kinds = (r: ReturnType<typeof reduce>) => r.effects.map(e => e.kind);

describe("navigation contract — explicit actions push", () => {
  it("Next enters the following step with its authored state", () => {
    const r = reduce(at(3, { t: 4, at: [100, 200], z: 2 }), { type: "next" }, ctx);
    expect(r.history).toBe("push");
    expect(r.nav).toMatchObject({ step: 4, t: 7.5, compare: false, a: "1617760", at: null, z: 1 });
    expect(kinds(r)).toEqual(["stopPlay", "aim", "focus"]);
  });
  it("Next on the last step opens Explore and remembers where it came from", () => {
    const r = reduce(at(6, { t: 12 }), { type: "next" }, ctx);
    expect(r).toMatchObject({ history: "push", nav: { step: "explore", from: 6, t: 12 } });
  });
  it("step 2 plays 0 → 8 h, or jumps to 8 h under reduced motion", () => {
    const played = reduce(at(1), { type: "next" }, ctx);
    expect(played.nav.t).toBe(0);
    expect(played.effects).toContainEqual({ kind: "play", from: 0, until: 8 });
    const jumped = reduce(at(1), { type: "next" }, { ...ctx, motionOK: false });
    expect(jumped.nav.t).toBe(8);
    expect(kinds(jumped)).not.toContain("play");
  });
  it("step 5 pins Saipan as B and turns Compare on", () => {
    expect(reduce(at(4, { b: "valp" }), { type: "next" }, ctx).nav).toMatchObject({ step: 5, compare: true, a: "1617760", b: "saip" });
  });
  it("Explore keeps the reader's screen; Resume returns to the step they left, not step 1", () => {
    const explored = reduce(at(4, { t: 9, at: [1, 2], z: 3 }), { type: "explore" }, ctx);
    expect(explored).toMatchObject({ history: "push", nav: { step: "explore", from: 4, t: 9, at: [1, 2], z: 3 } });
    const resumed = reduce(explored.nav, { type: "resumeStory" }, ctx);
    expect(resumed).toMatchObject({ history: "push", nav: { step: 4, t: 7.5, at: null } });
    expect(reduce(at("explore"), { type: "resumeStory" }, ctx).nav.step).toBe(1);
  });
  it("Compare on picks a valid B when none is pinned or B equals A", () => {
    expect(reduce(at("explore", { b: null }), { type: "compareOn" }, ctx).nav).toMatchObject({ compare: true, b: "1770000" });
    expect(reduce(at("explore", { b: "1617760" }), { type: "compareOn" }, ctx).nav.b).toBe("1770000");
    expect(reduce(at("explore"), { type: "compareOn" }, ctx)).toMatchObject({ history: "push", nav: { compare: true, b: "saip" } });
    expect(reduce(at("explore", { compare: true }), { type: "compareOff" }, ctx)).toMatchObject({ history: "push", nav: { compare: false, b: "saip" } });
  });
  it("pinning A as B is refused; pinning another station pushes", () => {
    expect(reduce(at("explore"), { type: "pin", id: "1617760" }, ctx).history).toBe("none");
    expect(reduce(at("explore"), { type: "pin", id: "valp" }, ctx)).toMatchObject({ history: "push", nav: { b: "valp" } });
  });
});

describe("navigation contract — story Back never fights browser Back", () => {
  it("goes back in history when the previous entry is that step", () => {
    const r = reduce(at(4), { type: "back" }, { ...ctx, prevEntryStep: 3 });
    expect(r.history).toBe("back");
    expect(r.nav.step).toBe(4); // the browser restores step 3 via popstate
    expect(kinds(r)).toEqual(["stopPlay"]);
  });
  it("replaces when the reader did not arrive from that step (deep link)", () => {
    expect(reduce(at(4), { type: "back" }, { ...ctx, prevEntryStep: null })).toMatchObject({ history: "replace", nav: { step: 3, t: 1 } });
  });
  it("is inert on step 1", () => {
    expect(reduce(at(1, { t: 0 }), { type: "back" }, ctx)).toMatchObject({ history: "none", effects: [] });
  });
});

describe("navigation contract — passive changes replace", () => {
  it("Return to this step restores the authored state without a new entry", () => {
    const r = reduce(at(5, { t: 20, b: "valp", at: [5, 5], z: 4 }), { type: "returnToStep" }, ctx);
    expect(r).toMatchObject({ history: "replace", nav: { step: 5, t: 7.5, b: "saip", compare: true, at: null, z: 1 } });
  });
  it("lens settle records the lens point and zoom, and the station under it", () => {
    expect(reduce(at(4), { type: "lensSettle", at: [10, 20], z: 2.5, station: "valp" }, ctx))
      .toMatchObject({ history: "replace", nav: { step: 4, at: [10, 20], z: 2.5, a: "valp" } });
    expect(reduce(at(4), { type: "lensSettle", at: [10, 20], z: 1, station: null }, ctx).nav.a).toBe("1617760");
    expect(reduce(at(4), { type: "lensSettle", at: [10, 20], z: 1, station: "valp", explicit: true }, ctx).history).toBe("push");
  });
  it("slider release and play end write the clock once", () => {
    expect(reduce(at("explore"), { type: "seekEnd", t: 11.25 }, ctx)).toMatchObject({ history: "replace", nav: { t: 11.25 } });
    expect(reduce(at(2), { type: "playEnd", t: 8 }, ctx)).toMatchObject({ history: "replace", nav: { t: 8 } });
  });
});

describe("navigation contract — popstate restores without writing", () => {
  it("stops play, aims instantly at the restored lens and never writes history", () => {
    const restored = at(3, { t: 1, a: "21418" });
    const r = reduce(at(2, { t: 4 }), { type: "popstate", nav: restored }, ctx);
    expect(r.history).toBe("none");
    expect(r.nav).toEqual(restored);
    expect(r.effects).toEqual([{ kind: "stopPlay" }, { kind: "aim", instant: true }, { kind: "focus", target: "step" }]);
  });
});

describe("Escape closes the topmost transient only", () => {
  it("closes evidence first, then pauses, then collapses the sheet, else nothing", () => {
    const e = { type: "escape" } as const;
    expect(kinds(reduce(at(4), e, { ...ctx, evidenceOpen: true, playing: true }))).toEqual(["closeEvidence"]);
    expect(kinds(reduce(at(4), e, { ...ctx, playing: true, sheetExpanded: true }))).toEqual(["stopPlay"]);
    expect(kinds(reduce(at(4), e, { ...ctx, sheetExpanded: true }))).toEqual(["collapseSheet"]);
    expect(reduce(at(4), e, ctx)).toMatchObject({ history: "none", effects: [] });
    expect(reduce(at(4), e, { ...ctx, evidenceOpen: true }).nav).toEqual(at(4));
  });
});

describe("story URL — the URL is the screen", () => {
  it("round-trips lens point, zoom and the step to resume", () => {
    const params = { t: 9.5, compare: true, step: "explore" as const, at: [-4282, 3827] as [number, number], z: 2.25, from: 4 as const };
    expect(parseStoryParams(`?${storyQuery(params)}`)).toEqual({ params, issues: [] });
  });
  it("a step link without clock or compare opens that step as authored", () => {
    expect(parseStoryParams("?step=4").params).toMatchObject({ step: 4, t: 7.5, compare: false });
    expect(parseStoryParams("?step=5").params).toMatchObject({ step: 5, compare: true });
    expect(parseStoryParams("?step=2").params.t).toBe(8); // a link never auto-plays
    expect(parseStoryParams("?step=4&t=0&cmp=1").params).toMatchObject({ t: 0, compare: true });
  });
  it("repairs bad lens, zoom and resume values", () => {
    const bad = parseStoryParams("?at=x,2&z=999&from=9");
    expect(bad.params).toMatchObject({ at: null, z: 20, from: null });
    expect(bad.issues.length).toBe(3);
  });
});
