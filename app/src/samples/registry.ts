import type { ReactElement } from "react";
import { PairedAtlas } from "./paired-atlas/PairedAtlas";
import { RadialRecord } from "./radial-record/RadialRecord";
import { RadialComparison } from "./radial-comparison/RadialComparison";

export type SampleDefinition = { id: string; name: string; question: string; Component: () => ReactElement };
export type SampleId = SampleDefinition["id"];

export const sampleDefinitions: readonly SampleDefinition[] = [
  { id: "paired-atlas", name: "Paired atlas", question: "Can a shared map make two station records easier to compare?", Component: PairedAtlas },
  { id: "radial-record", name: "Radial record", question: "Can three chart-bearing arms keep a station, its record and its gaps together?", Component: RadialRecord },
  { id: "radial-comparison", name: "Radial comparison", question: "Can an asymmetric orbit preserve a pinned reference while another record is compared?", Component: RadialComparison },
];

export function resolveSample(search: string): SampleDefinition {
  const id = new URLSearchParams(search).get("sample");
  return sampleDefinitions.find((sample) => sample.id === id) ?? sampleDefinitions[0];
}
