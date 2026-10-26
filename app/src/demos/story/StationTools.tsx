import type { DemoManifest, ProductKey, StationMetadata } from "../types";

export type StationToolsProps = {
  stations: StationMetadata[]; windows: DemoManifest["windows"];
  selectedStationId: string; pinnedStationId: string | null; windowId: string; productKey: ProductKey;
  onSelect: (id: string) => void; onPin: (id: string | null) => void; onWindow: (id: string) => void; onProduct: (key: ProductKey) => void;
};
/** Station A (with named neighbours in source order), B (never A), UTC window and product. Hook-free, so tests can walk it. */
export function StationTools(p: StationToolsProps) {
  const i = p.stations.findIndex(s => s.station_id === p.selectedStationId), prev = p.stations[i - 1], next = p.stations[i + 1];
  const products = p.stations[i]?.products ?? [];
  return <section className="story-tools" aria-label="Stations and record controls">
    <label>Station A<select value={p.selectedStationId} onChange={e => p.onSelect(e.target.value)}>
      {p.stations.map(s => <option key={s.station_id} value={s.station_id}>{s.name} · {s.station_id}</option>)}</select></label>
    <div className="story-tools__targets">
      <button type="button" aria-label={`Previous station target: ${prev ? prev.name : "Start of station list"}`}
        disabled={!prev} onClick={() => prev && p.onSelect(prev.station_id)}>
        <small>← Previous</small><span>{prev ? prev.name : "Start of station list"}</span></button>
      <button type="button" aria-label={`Next station target: ${next ? next.name : "End of station list"}`}
        disabled={!next} onClick={() => next && p.onSelect(next.station_id)}>
        <small>Next →</small><span>{next ? next.name : "End of station list"}</span></button>
    </div>
    <label>Pinned reference B<select aria-label="Pinned reference B" value={p.pinnedStationId ?? ""} onChange={e => p.onPin(e.target.value || null)}>
      <option value="">No reference pinned</option>
      {p.stations.filter(s => s.station_id !== p.selectedStationId)
        .map(s => <option key={s.station_id} value={s.station_id}>{s.name} · {s.station_id}</option>)}
    </select></label>
    <label>UTC window<select value={p.windowId} onChange={e => p.onWindow(e.target.value)}>
      {p.windows.map(w => <option key={w.id} value={w.id}>{w.label}</option>)}</select></label>
    {p.windowId === "source_full" && <p className="story-small">Full source record — station-specific bounds; not a common comparison period.
      Each record retains its own exact interval.</p>}
    <label>Product<select value={p.productKey} onChange={e => p.onProduct(e.target.value as ProductKey)}>
      {products.map(x => <option key={x.key} value={x.key}>{x.label}{x.available ? "" : " · unavailable at this station"}</option>)}</select></label>
    <p className="story-small">Each station keeps its own y-scale, product, units and datum; an unavailable product is never substituted.</p>
  </section>;
}
