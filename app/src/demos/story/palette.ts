/** Night palette: sequential ramp by published hour (1–24 h full range; later hours reuse the end). */
const STOPS = ["#9ff3ff", "#55b8ff", "#6a72ff", "#b066ff"];
const rgb = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
export function contourColour(hour: number): string {
  const t = Math.max(0, Math.min(1, (hour - 1) / 23)), seg = (STOPS.length - 1) * t;
  const i = Math.min(STOPS.length - 2, Math.floor(seg)), f = seg - i, a = rgb(STOPS[i]), b = rgb(STOPS[i + 1]);
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
}
export const rampGradient = () => `linear-gradient(90deg, ${Array.from({ length: 11 }, (_, i) => contourColour(1 + i * 2.9)).join(",")})`;
