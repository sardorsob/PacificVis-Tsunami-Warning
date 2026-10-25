import type { DemoState } from "../types";

const LABEL: Record<DemoState["view"], string> = { story: "Story", paired: "Paired", radial: "Station lens" };
/** The three views; the current one is pressed and inert. */
export function ViewSwitch({ view, onView }: { view: DemoState["view"]; onView: (view: DemoState["view"]) => void }) {
  return <nav className="story-views" aria-label="Views">
    {(Object.keys(LABEL) as DemoState["view"][]).map(v =>
      <button key={v} type="button" aria-pressed={view === v} onClick={() => { if (v !== view) onView(v); }}>{LABEL[v]}</button>)}
  </nav>;
}
