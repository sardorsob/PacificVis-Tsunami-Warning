import { describe, expect, it } from "vitest";
import { COLUMN_RIGHT, layoutFor } from "../layout";

// Slider width left inside the clock control after the play button, readout, gaps and padding.
// Lens title worst cases: phones and side sheets wrap the epicentre subtitle to 3 lines under a 20 px name
// (22 + 3 × 18.2); wide wraps it to 2 lines under a 26 px name (28.6 + 2 × 18.2).
const PLAY = 42, READOUT = 170, GAPS = 24, PAD = 24, TITLE_H = { narrow: 77, side: 77, wide: 65 };
const VIEWPORTS: [number, number, "wide" | "side" | "narrow"][] = [
  [360, 640, "narrow"], [390, 844, "narrow"], [568, 320, "side"], [667, 375, "side"], [768, 1024, "side"], [1024, 768, "side"],
  [1280, 800, "wide"], [1440, 900, "wide"],
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
    expect(L.titleBottom - TITLE_H[L.mode]).toBeGreaterThanOrEqual(0);
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
      expect(L.record.left).toBeGreaterThanOrEqual(COLUMN_RIGHT + 8);        // never under the column
      expect(L.support.left + L.aw).toBeLessThanOrEqual(w - 8);              // never off the right edge
      expect(L.bar!.width - PLAY - READOUT - GAPS - PAD).toBeGreaterThanOrEqual(240);
      expect(L.read.top + 130).toBeLessThanOrEqual(h - 100);                // read arm clears the clock bar
      expect(L.record.top).toBeGreaterThanOrEqual(194); // clear of the top-right panel: 192 px tall with Compare on (measured, 1280×800)
    } else {
      const sheet = L.mode === "side" ? L.sheet!.width : w;
      expect(sheet - PAD - PLAY - 12).toBeGreaterThanOrEqual(240);
    }
  });
});
