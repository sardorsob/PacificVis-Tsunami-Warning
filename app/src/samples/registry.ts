import type { ReactElement } from "react";
import { PairedAtlas } from "./paired-atlas/PairedAtlas";

export type SampleDefinition = { id: string; name: string; question: string; Component: () => ReactElement };
export type SampleId = SampleDefinition["id"];

export const sampleDefinitions: readonly SampleDefinition[] = [
  { id: "paired-atlas", name: "Paired atlas", question: "Can a shared map make two station records easier to compare?", Component: PairedAtlas },
];

export function resolveSample(search: string): SampleDefinition {
  const id = new URLSearchParams(search).get("sample");
  return sampleDefinitions.find((sample) => sample.id === id) ?? sampleDefinitions[0];
}
