/** The six guided steps, as data. Copy is subject to the G3 review. */
export type StepId = 1 | 2 | 3 | 4 | 5 | 6;
type LensTarget = { station: string } | { point: "epicentre" } | { point: "between-10-11" };
/** Station A is the lens station (when the lens targets one); B is pinned only for Compare steps. */
export type StoryStep = {
  id: StepId; title: string; body: string;
  t: number; play: [number, number] | null; lens: LensTarget;
  compare: boolean; b: string | null;
};

export const STEPS: readonly StoryStep[] = [
  { id: 1, title: "05:46 UTC, 11 March 2011", t: 0, play: null, lens: { point: "epicentre" }, compare: false, b: null,
    body: "A magnitude 9.1 earthquake ruptures the seafloor off Tōhoku, Japan (USGS). Every time in this story counts from this moment." },
  { id: 2, title: "The published clock", t: 8, play: [0, 8], lens: { point: "epicentre" }, compare: false, b: null,
    body: "NOAA/NCEI's travel-time map draws one line for each hour after the earthquake, calculated from ocean depth. It is a published model estimate: first arrival only, no wave height." },
  { id: 3, title: "A deep-ocean record", t: 1, play: null, lens: { station: "21418" }, compare: false, b: null,
    body: "DART 21418 sits on the deep seafloor east of Japan and records the water column above it. Its record is shown as measured, point by point. No arrival is picked here." },
  { id: 4, title: "Hilo, seven and a half hours on", t: 7.5, play: null, lens: { station: "1617760" }, compare: false, b: null,
    body: "Hilo's tide gauge records raw water level, tide included, on its own vertical scale. The white line marks the story clock on its record: a time, not an arrival." },
  { id: 5, title: "When the record goes quiet", t: 7.5, play: null, lens: { station: "1617760" }, compare: true, b: "saip",
    body: "Saipan's record has gaps, stretches with no samples at all. A gap is a missing sample, not a zero. Hilo and Saipan use different instruments and datums, so their heights are not compared." },
  { id: 6, title: "A contour is not an arrival", t: 12, play: null, lens: { point: "between-10-11" }, compare: false, b: null,
    body: "Three clocks are easy to mix up: the published travel time on this map, the moment a wave is actually observed, and the time people were warned. This story shows the first and the records; it does not yet validate the other two." },
];

export function validateSteps(stationIds: readonly string[]): void {
  for (const step of STEPS) {
    const named = [step.b, "station" in step.lens ? step.lens.station : null].filter((v): v is string => v !== null);
    for (const id of named) if (!stationIds.includes(id)) throw new Error(`Story step ${step.id} names unknown station ${id}.`);
  }
}
