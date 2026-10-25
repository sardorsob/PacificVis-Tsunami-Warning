import { describe, expect, it } from "vitest";
import { clockLabel, seek, tick, toggle, utcAt, T_MAX } from "./clock";
import { contourStyle, pulseWidth } from "./reveal";
import { capture, slot } from "./lensMath";
import type { Pt } from "./layers";
import { pinchView, toMap, toScreen, type KLimits } from "./StoryMap";
import { STEPS, validateSteps } from "./steps";
import { parseStoryParams, storyQuery } from "./url";
import { parseState } from "../state";
import { STATION_IDS } from "../loader";
import type { DemoManifest } from "../types";

describe("story clock", () => {
  it("advances at the play rate and reports crossed published hours", () => {
    const r = tick({ t: 6.9, playing: true }, 0.25);
    expect(r.clock.t).toBeCloseTo(7.5);
    expect(r.crossed).toEqual([7]);
  });
  it("does not move while paused", () => {
    expect(tick({ t: 3, playing: false }, 5)).toEqual({ clock: { t: 3, playing: false }, crossed: [] });
  });
  it("stops at the end and restarts from zero on play", () => {
    const end = tick({ t: 29.9, playing: true }, 1).clock;
    expect(end).toEqual({ t: T_MAX, playing: false });
    expect(toggle(end)).toEqual({ t: 0, playing: true });
    expect(toggle({ t: 4, playing: true })).toEqual({ t: 4, playing: false });
  });
  it("seeking backwards crosses nothing; forwards crosses each hour once", () => {
    expect(seek({ t: 9, playing: false }, 2).crossed).toEqual([]);
    expect(seek({ t: 2.5, playing: false }, 5).crossed).toEqual([3, 4, 5]);
    expect(seek({ t: 2, playing: false }, 99).clock.t).toBe(T_MAX);
  });
  it("formats the clock and its UTC time from the USGS origin", () => {
    expect(clockLabel(7.5)).toBe("+7 h 30 min");
    expect(clockLabel(0)).toBe("+0 h 00 min");
    expect(clockLabel(2.999)).toBe("+3 h 00 min");
    expect(utcAt("2011-03-11T05:46:24.120Z", 7.5)).toBe("13:16 UTC");
  });
});

describe("reveal", () => {
  it("shows passed hours fully and fades in only the next hour", () => {
    expect(contourStyle(7, 7.5, false).opacity).toBeCloseTo(0.95);
    expect(contourStyle(8, 7.5, false).opacity).toBeCloseTo(0.055 + (0.95 - 0.055) * 0.25);
    expect(contourStyle(9, 7.5, false).opacity).toBeCloseTo(0.055);
    expect(contourStyle(30, 31, false).opacity).toBeCloseTo(0.42);
    expect(contourStyle(10, 12, true).width).toBe(1.7);
    expect(contourStyle(11, 12, false).width).toBe(0.8);
  });
  it("pulses for 0.9 s then settles", () => {
    expect(pulseWidth(0.8, 0)).toBeCloseTo(5.3);
    expect(pulseWidth(0.8, 900)).toBeCloseTo(0.8);
    expect(pulseWidth(0.8, 5000)).toBeCloseTo(0.8);
  });
});

describe("lens", () => {
  it("captures the nearest station inside the radius only", () => {
    const r = 337_500;
    const stations = [{ id: "near", xy: [100000, 0] as [number, number] }, { id: "far", xy: [9e6, 0] as [number, number] }];
    expect(capture([0, 0], r, stations)).toBe("near");
    expect(capture([5e6, 0], r, stations)).toBeNull();
  });
  it("keeps the compare slot above the clock bar", () => {
    expect(slot(700, 360, 108, 44, 330, 848)).toEqual([700 + 108 + 44 + 165, 618]);
    expect(slot(700, 600, 108, 44, 330, 848)[1]).toBe(848 - 170);
  });
});

describe("pinch", () => {
  const v = { k: 1e-4, tx: 400, ty: 300 }, limits: KLimits = [2e-5, 6e-4];
  it("scales by the finger spread and keeps the map point under the fingers", () => {
    const from: [Pt, Pt] = [[100, 100], [200, 100]], to: [Pt, Pt] = [[50, 150], [250, 150]];
    const next = pinchView(v, from, to, limits), under = toMap(v, 150, 100), after = toScreen(next, under);
    expect(next.k).toBeCloseTo(2e-4);
    expect(after[0]).toBeCloseTo(150);
    expect(after[1]).toBeCloseTo(150);
  });
  it("clamps the zoom and survives touching fingers", () => {
    expect(pinchView(v, [[0, 0], [1, 0]], [[0, 0], [1e6, 0]], limits).k).toBe(6e-4);
    expect(Number.isFinite(pinchView(v, [[5, 5], [5, 5]], [[0, 0], [10, 0]], limits).k)).toBe(true);
  });
});

describe("guided steps", () => {
  it("authors six steps that all name real stations", () => {
    expect(STEPS.map(s => s.id)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(() => validateSteps(STATION_IDS)).not.toThrow();
    expect(() => validateSteps(["1617760"])).toThrow(/unknown station/);
  });
  it("never claims an arrival or warning time in step copy", () => {
    for (const step of STEPS) expect(`${step.title} ${step.body}`).not.toMatch(/arrived|arrival time is|warning time is|minutes of warning/i);
    expect(STEPS[4]).toMatchObject({ compare: true, lens: { station: "1617760" }, b: "saip" });
  });
});

describe("story URL: B is never A", () => {
  it("repairs a story link that pins the selected station", () => {
    const m = { default_state: { selectedStationId: "1617760", pinnedStationId: "saip", windowId: "common_day", productKey: "raw_value" },
      stations: STATION_IDS.map(station_id => ({ station_id })), windows: [{ id: "common_day" }] } as unknown as DemoManifest;
    const r = parseState("?view=story&selected=1617760&pinned=1617760", m);
    expect(r.state.pinnedStationId).toBe(STATION_IDS.find(id => id !== "1617760"));
    expect(r.issues.join(" ")).toMatch(/B cannot be the selected station/);
    expect(parseState("?view=story&selected=1617760&pinned=", m).state.pinnedStationId).toBeNull();
    expect(parseState("?view=paired&selected=saip&pinned=saip", m).state.pinnedStationId).toBe("1617760"); // every view
  });
});

describe("story URL", () => {
  it("round-trips story params and repairs bad values", () => {
    expect(parseStoryParams("?" + storyQuery({ t: 7.5, compare: true, step: 5, at: null, z: 1, from: null })).params).toEqual({ t: 7.5, compare: true, step: 5, at: null, z: 1, from: null });
    expect(parseStoryParams("?step=explore").params.step).toBe("explore");
    const bad = parseStoryParams("?t=99&step=9");
    expect(bad.params.t).toBe(T_MAX);
    expect(bad.params.step).toBe(1);
    expect(bad.issues.length).toBe(2);
  });
  it("lets the shared demo state accept the story view and its fields", () => {
    const manifest = { stations: STATION_IDS.map(station_id => ({ station_id })), windows: [{ id: "common_day" }],
      default_state: { selectedStationId: "1617760", pinnedStationId: "saip", windowId: "common_day", productKey: "raw_value" } } as unknown as DemoManifest;
    const parsed = parseState("?view=story&t=2&cmp=1&step=3", manifest);
    expect(parsed.state.view).toBe("story");
    expect(parsed.issues).toEqual([]);
  });
});
