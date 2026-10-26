import { B_LENS_RADIUS, LENS_RADIUS, slot } from "./story/lensMath";
export function plotDateContext(startUtc:string,endUtc:string):string {
  const start=startUtc.slice(0,10),end=endUtc.slice(0,10);
  return `${start}${end!==start?` → ${end}`:""} UTC`;
}


/** Right edge of the story's editorial column (left 16 + width 282, scaled with the stage). */
export const columnRight = (ui: number) => 16 + 282 * ui;
/** Top of a side arm centred on the lens (cy), kept between the top panel and the clock bar; a taller arm starts at the top. */
export const centreArm = (cy: number, h: number, minTop: number, maxBottom: number) =>
  h >= maxBottom - minTop ? minTop : Math.max(minTop, Math.min(cy - h / 2, maxBottom - h));
const COLUMN = 300, GAP = 44, TOP_PANEL_BOTTOM = 200, READ_ARM = 130, CLOCK_BAR = 100;
type Box = { left: number; top: number; width: number };
export type StoryMode = "wide" | "side" | "narrow";
export type StoryLayout = {
  mode: StoryMode; cx: number; cy: number; r: number; aw: number; record: Box; support: Box; read: Box & { maxHeight?: number };
  /** Stage scale: 1 up to 1440 × 900, growing to 1.25 at 1920 × 1080 (wide only). Panels, lens and type scale with it. */
  ui: number;
  /** Lowest a side arm may reach (wide): above the clock bar, and above the zoom buttons when the right arm reaches over them. */
  armBottom: number;
  /** Lens title: bottom edge (it grows upward when the subtitle wraps) and maximum width. */
  titleBottom: number; titleW: number;
  bSlot: [number, number]; bR: number; bar: { left: number; width: number } | null; sheet: { width: number } | null;
};
/**
 * Story view tiers. wide (≥ 1280 × ≥ 700): lens centred right of the column with three arms; narrow (< 768 portrait):
 * lens in the upper third, bottom sheet; side (tablets, small laptops, landscape phones): lens left, side sheet.
 * armMax caps the side arms when wide (Station lens passes more, for its full cards).
 */
export function layoutFor(w: number, h: number, armMax = 330): StoryLayout {
  const mode: StoryMode = w >= 1280 && h >= 700 ? "wide" : w < 768 && h > 450 ? "narrow" : "side";
  const none: Box = { left: 0, top: 0, width: 0 };
  if (mode === "narrow") {
    // Room above the lens for a three-line title (the epicentre subtitle wraps on 360 px phones).
    const r = Math.min(82, w * 0.21), cx = w / 2, cy = Math.max(r + 96, h * 0.25);
    // The title stays clear of the top-right zoom buttons (54 px wide, 8 px from the edge) on both sides.
    return { mode, cx, cy, r, aw: 0, record: none, support: none, read: none, ui: 1, armBottom: h, titleBottom: cy - r - 14,
      titleW: w - 132,
      bSlot: [Math.min(w - 44, cx + r + 48), cy + r - 6], bR: 38, bar: null, sheet: null };
  }
  if (mode === "side") {
    const sheet = Math.round(Math.min(w * 0.6, Math.max(320, w * 0.44))), area = w - sheet - 8;
    // The lens's left edge clears the bottom-left zoom buttons (12 + 48 + 8 px).
    const r = Math.min(LENS_RADIUS, area * 0.3, h * 0.27, area / 2 - 68), cx = area / 2, cy = Math.max(r + 92, h * 0.5);
    return { mode, cx, cy, r, aw: 0, record: none, support: none, read: none, ui: 1, armBottom: h, titleBottom: cy - r - 14,
      titleW: area - 24,
      bSlot: [Math.min(area - 44, cx + r + 50), cy + r + 10], bR: 38, bar: null, sheet: { width: sheet } };
  }
  const ui = Math.max(1, Math.min(1.25, 1 + (w - 1440) / 1920, 1 + (h - 900) / 720));
  const col = COLUMN * ui, gap = GAP * ui, top = TOP_PANEL_BOTTOM * ui, bar = CLOCK_BAR * ui;
  const r = LENS_RADIUS * ui, cx = col + (w - col) / 2;
  // Arms start below the top-right panel; the read arm ends above the clock bar.
  const cy = Math.min(Math.max(h * 0.4, top + 30 + r), h - bar - READ_ARM * ui - 30 - r);
  const aw = Math.min(armMax * ui, (w - col) / 2 - r - gap - 16);
  // The zoom buttons (style.css: 54 × 144 px, 16 px from the bottom-right corner) sit under the right arm's reach on narrower screens.
  const armBottom = cx + r + gap + aw > w - 16 - 54 ? Math.min(h - bar - 16, h - 16 - 144 - 8) : h - bar - 16;
  return { mode, cx, cy, r, aw, ui, armBottom,
    record: { left: cx - r - gap - aw, top: cy - r - 30, width: aw },
    support: { left: cx + r + gap, top: cy - r - 30, width: aw },
    // The read arm stops above the clock bar and scrolls past that (short wide screens, 700–760 px).
    read: { left: cx - r - gap + 12, top: cy + r + 30, width: 2 * (r + gap) - 24, maxHeight: h - bar - (cy + r + 30) },
    titleBottom: cy - r - 30, titleW: Math.min(400 * ui, w - col - 32), bSlot: slot(cx, cy, r, gap, aw, h, ui), bR: B_LENS_RADIUS * ui,
    bar: { left: cx, width: Math.min(720 * ui, w - col - 32) }, sheet: null };
}
