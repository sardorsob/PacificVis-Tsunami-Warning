import { describe, expect, it } from "vitest";
import { COLUMN_RIGHT, layoutFor } from "../layout";

// Slider width left inside the clock control after the play button, readout, gaps and padding.
const PLAY = 42, READOUT = 170, GAPS = 24, PAD = 24;
const VIEWPORTS: [number, number, "wide" | "side" | "narrow"][] = [
  [390, 844, "narrow"], [667, 375, "side"], [768, 1024, "side"], [1024, 768, "side"], [1280, 800, "wide"], [1440, 900, "wide"],
];

describe("story layout tiers", () => {
  it.each(VIEWPORTS)("%i×%i uses the %s tier", (w, h, mode) => expect(layoutFor(w, h).mode).toBe(mode));

  it.each(VIEWPORTS)("%i×%i keeps every panel on screen and the slider usable", (w, h) => {
    const L = layoutFor(w, h);
    const lensRight = L.mode === "side" ? w - L.sheet!.width - 8 : w;
    expect(L.cx - L.r).toBeGreaterThanOrEqual(0);
    expect(L.cx + L.r).toBeLessThanOrEqual(lensRight);
    expect(L.cy - L.r).toBeGreaterThanOrEqual(0);
    expect(L.titleTop).toBeGreaterThanOrEqual(0);
    expect(L.bSlot[0] + L.bR).toBeLessThanOrEqual(lensRight);
    expect(Math.hypot(L.bSlot[0] - L.cx, L.bSlot[1] - L.cy)).toBeGreaterThanOrEqual(L.r + L.bR);
    if (L.mode === "wide") {
      expect(L.record.left).toBeGreaterThanOrEqual(COLUMN_RIGHT + 8);        // never under the column
      expect(L.support.left + L.aw).toBeLessThanOrEqual(w - 8);              // never off the right edge
      expect(L.bar!.width - PLAY - READOUT - GAPS - PAD).toBeGreaterThanOrEqual(240);
      expect(L.read.top + 130).toBeLessThanOrEqual(h - 100);                // read arm clears the clock bar
      expect(L.record.top).toBeGreaterThanOrEqual(190);                     // arms clear the top-right panel
    } else {
      const sheet = L.mode === "side" ? L.sheet!.width : w;
      expect(sheet - PAD - PLAY - 12).toBeGreaterThanOrEqual(240);
    }
  });
});
