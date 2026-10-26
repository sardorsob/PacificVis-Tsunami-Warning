import { describe, expect, it } from "vitest";
import { centreArm, columnRight, layoutFor } from "../layout";

// Slider width left inside the clock control after the play button, readout, gaps and padding.
// Lens title worst cases: phones and side sheets wrap the epicentre subtitle to 3 lines under a 20 px name
// (22 + 3 × 18.2); wide wraps it to 2 lines under a 26 px name (28.6 + 2 × 18.2).
const PLAY = 42, READOUT = 170, GAPS = 24, PAD = 24, TITLE_H = { narrow: 77, side: 77, wide: 65 };
const VIEWPORTS: [number, number, "wide" | "side" | "narrow"][] = [
  [360, 640, "narrow"], [390, 844, "narrow"], [568, 320, "side"], [667, 375, "side"], [768, 1024, "side"], [1024, 768, "side"],
  [1280, 800, "wide"], [1440, 900, "wide"], [1920, 1080, "wide"],
];

describe("story layout tiers", () => {
  it.each(VIEWPORTS)("%i×%i uses the %s tier", (w, h, mode) => expect(layoutFor(w, h).mode).toBe(mode));

  it.each(VIEWPORTS)("%i×%i keeps every panel on screen and the slider usable", (w, h) => {
    const L = layoutFor(w, h);
    const lensRight = L.mode === "side" ? w - L.sheet!.width - 8 : w;
    expect(L.cx - L.r).toBeGreaterThanOrEqual(0);
    expect(L.cx + L.r).toBeLessThanOrEqual(lensRight);
    expect(L.cy - L.r).toBeGreaterThanOrEqual(0);
    // The title is bottom-anchored above the lens: two subtitle lines still fit on screen, inside the map area,
    // and on phones clear of the zoom buttons (top-right, 60 px).
    expect(L.titleBottom - TITLE_H[L.mode] * L.ui).toBeGreaterThanOrEqual(0);
    expect(L.titleBottom).toBeLessThanOrEqual(L.cy - L.r);
    expect(L.cx - L.titleW / 2).toBeGreaterThanOrEqual(0);
    expect(L.cx + L.titleW / 2).toBeLessThanOrEqual(L.mode === "narrow" ? w - 60 : lensRight);
    expect(L.bSlot[0] + L.bR).toBeLessThanOrEqual(lensRight);
    expect(Math.hypot(L.bSlot[0] - L.cx, L.bSlot[1] - L.cy)).toBeGreaterThanOrEqual(L.r + L.bR);
    if (L.mode !== "wide") expect(L.bSlot[1] + L.bR + 16).toBeLessThanOrEqual(h); // B lens and its caption stay on screen
    // The zoom buttons (style.css: 48 × 144 px) never cover a lens: side = bottom-left 12 px, narrow = top-right 8 px.
    const zoom = L.mode === "side" ? [12, h - 156, 60, h - 12] : L.mode === "narrow" ? [w - 56, 8, w - 8, 152] : null;
    const clear = ([x, y]: [number, number], r: number) => !zoom || x + r <= zoom[0] || x - r >= zoom[2] || y + r <= zoom[1] || y - r >= zoom[3];
    expect(clear([L.cx, L.cy], L.r)).toBe(true);
    expect(clear(L.bSlot, L.bR)).toBe(true);
    if (L.mode === "wide") {
      expect(L.record.left).toBeGreaterThanOrEqual(columnRight(L.ui) + 8);   // never under the column
      expect(L.support.left + L.aw).toBeLessThanOrEqual(w - 8);              // never off the right edge
      expect(L.bar!.width - (PLAY + READOUT + GAPS + PAD) * L.ui).toBeGreaterThanOrEqual(240);
      expect(L.read.top + 130 * L.ui).toBeLessThanOrEqual(h - 100 * L.ui); // read arm clears the clock bar
      // clear of the top-right panel: 196 px tall with Compare on (measured at 1280×800), scaled with the stage
      expect(L.record.top).toBeGreaterThanOrEqual(196 * L.ui);
    } else {
      const sheet = L.mode === "side" ? L.sheet!.width : w;
      expect(sheet - PAD - PLAY - 12).toBeGreaterThanOrEqual(240);
    }
  });
});

describe("large screens and centred arms", () => {
  it("scale the stage gently from 1440 to 1920 wide (and only as far as the height allows)", () => {
    expect(layoutFor(1440, 900).ui).toBe(1);
    expect(layoutFor(1920, 1080).ui).toBeCloseTo(1.25);
    expect(layoutFor(2560, 1440).ui).toBe(1.25);
    expect(layoutFor(1920, 900).ui).toBe(1);
    expect(layoutFor(1920, 1080).r).toBeCloseTo(135);
    expect(layoutFor(390, 844).ui).toBe(1);
  });
  it("centre a side arm on the lens, kept between the top panel and the clock bar", () => {
    expect(centreArm(360, 130, 200, 780)).toBe(295);        // fits: centred on the lens
    expect(centreArm(360, 400, 200, 780)).toBe(200);        // would cross the top panel: starts below it
    expect(centreArm(600, 400, 200, 780)).toBe(380);        // would cross the clock bar: ends above it
    expect(centreArm(360, 700, 200, 780)).toBe(200);        // taller than the band: starts at the top (it scrolls)
  });
});
