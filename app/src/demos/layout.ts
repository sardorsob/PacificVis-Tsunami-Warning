import { B_LENS_RADIUS, LENS_RADIUS, slot } from "./story/lensMath";
export function isShortLandscape(width:number,height:number):boolean {
  return width>=600&&height<=450;
}
export function plotDateContext(startUtc:string,endUtc:string):string {
  const start=startUtc.slice(0,10),end=endUtc.slice(0,10);
  return `${start}${end!==start?` → ${end}`:""} UTC`;
}


/** Right edge of the story's editorial column (left 16 + width 282). */
export const COLUMN_RIGHT = 298;
const COLUMN = 300, GAP = 44, TOP_PANEL_BOTTOM = 190, READ_ARM = 130, CLOCK_BAR = 100;
type Box = { left: number; top: number; width: number };
export type StoryMode = "wide" | "side" | "narrow";
export type StoryLayout = {
  mode: StoryMode; cx: number; cy: number; r: number; aw: number; record: Box; support: Box; read: Box; titleTop: number;
  bSlot: [number, number]; bR: number; bar: { left: number; width: number } | null; sheet: { width: number } | null;
};
/**
 * Story view tiers. wide (≥ 1280 × ≥ 700): lens centred right of the column with three arms; narrow (< 768 portrait):
 * lens in the upper third, bottom sheet; side (tablets, small laptops, landscape phones): lens left, side sheet.
 */
export function layoutFor(w: number, h: number): StoryLayout {
  const mode: StoryMode = w >= 1280 && h >= 700 ? "wide" : w < 768 && h > 450 ? "narrow" : "side";
  const none: Box = { left: 0, top: 0, width: 0 };
  if (mode === "narrow") {
    const r = Math.min(82, w * 0.21), cx = w / 2, cy = Math.max(r + 64, h * 0.25);
    return { mode, cx, cy, r, aw: 0, record: none, support: none, read: none, titleTop: cy - r - 54,
      bSlot: [Math.min(w - 44, cx + r + 48), cy + r - 6], bR: 38, bar: null, sheet: null };
  }
  if (mode === "side") {
    const sheet = Math.round(Math.min(w * 0.6, Math.max(320, w * 0.44))), area = w - sheet - 8;
    const r = Math.min(LENS_RADIUS, area * 0.3, h * 0.27), cx = area / 2, cy = Math.max(r + 60, h * 0.5);
    return { mode, cx, cy, r, aw: 0, record: none, support: none, read: none, titleTop: cy - r - 54,
      bSlot: [Math.min(area - 44, cx + r + 50), cy + r - 6], bR: 38, bar: null, sheet: { width: sheet } };
  }
  const r = LENS_RADIUS, cx = COLUMN + (w - COLUMN) / 2;
  // Arms start below the top-right panel; the read arm ends above the clock bar.
  const cy = Math.min(Math.max(h * 0.4, TOP_PANEL_BOTTOM + 30 + r), h - CLOCK_BAR - READ_ARM - 30 - r);
  const aw = Math.min(330, (w - COLUMN) / 2 - r - GAP - 16);
  return { mode, cx, cy, r, aw,
    record: { left: cx - r - GAP - aw, top: cy - r - 30, width: aw },
    support: { left: cx + r + GAP, top: cy - r - 30, width: aw },
    read: { left: cx - 150, top: cy + r + 30, width: 300 },
    titleTop: cy - r - 76, bSlot: slot(cx, cy, r, GAP, aw, h), bR: B_LENS_RADIUS,
    bar: { left: cx, width: Math.min(720, w - COLUMN - 32) }, sheet: null };
}
