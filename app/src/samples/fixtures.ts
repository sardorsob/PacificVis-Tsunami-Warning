export type TracePoint = Readonly<{ minute: number; value: number | null }>;
export type StationFixture = Readonly<{
  id: string;
  name: string;
  setting: string;
  mapPosition: readonly [number, number];
  points: readonly TracePoint[];
}>;

const station = (id: string, name: string, setting: string, mapPosition: readonly [number, number], values: readonly (number | null)[]): StationFixture =>
  Object.freeze({ id, name, setting, mapPosition: Object.freeze(mapPosition), points: Object.freeze(values.map((value, index) => Object.freeze({ minute: index * 5, value }))) });

// Deliberately fictional: layout inputs only, never a scientific source.
export const stationFixtures: readonly StationFixture[] = Object.freeze([
  station("station-a", "Station A", "Open-ocean example", [0.38, 0.44], [0, 1, -1, 3, 8, null, null, -5, -9, -3, 5, 3, 1]),
  station("station-b", "Station B", "Island-side example", [0.68, 0.62], [0, -1, null, null, 2, 5, 9, 4, -4, -7, -2, 3, 0]),
]);

export const fixtureNotice = "Invented examples · not scientific results";
