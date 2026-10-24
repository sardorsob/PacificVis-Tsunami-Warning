import { useEffect, useState } from "react";
import { LatestRequest } from "../loader";
import { loadLayers, type StoryLayers } from "./layers";
import { StoryView, type StoryViewProps } from "./StoryView";

export type StoryRouteProps = Omit<StoryViewProps, "layers" | "layersError" | "onRetryLayers">;
/** Loads the hash-verified map layers; the view still shows records and the v2 coastline if they fail. */
export function StoryRoute(props: StoryRouteProps) {
  const [layers, setLayers] = useState<StoryLayers | null>(null), [error, setError] = useState<string | null>(null), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const request = new LatestRequest<StoryLayers>(); setError(null);
    void request.run(loadLayers).then(l => { if (l) setLayers(l); }).catch((e: unknown) => setError(e instanceof Error ? e.message : "Unexpected map-layer failure."));
    return () => request.cancel();
  }, [attempt]);
  return <StoryView {...props} layers={layers} layersError={error} onRetryLayers={() => setAttempt(a => a + 1)}/>;
}
