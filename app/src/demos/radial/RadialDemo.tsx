import { RecordChart } from "../RecordChart";
import { SupportView } from "../SupportView";
import { StationMap } from "../StationMap";
import { safeSourceUrl } from "../loader";
import type { RadialProps, StationSelection } from "../types";
import "./style.css";

export function RadialDemo(props: RadialProps) {
  const {manifest, state, selected, pinned} = props;
  const targetIndex = manifest.stations.findIndex(station => station.station_id === state.selectedStationId);
  const previous = manifest.stations[targetIndex - 1];
  const next = manifest.stations[targetIndex + 1];

  function recordArm(selection: StationSelection, role: "selected" | "pinned") {
    const {station, records, status, error} = selection;
    const ready = status === "ready" && records !== null;
    const url = safeSourceUrl(station.source.url);
    return <article className={`station-card station-card--${role} radial-demo__trace radial-demo__trace--${role}`} aria-label={`${role === "selected" ? "Selected" : "Pinned reference"}: ${station.name}`}>
      <header><span className="role-badge">{role === "selected" ? "○ Selected" : "◇ Pinned reference"}</span><h2>{station.name} <span>{station.station_id}</span></h2><p>{station.station_type === "dart" ? "DART water column" : "Coastal water level"}</p></header>
      {ready ? <RecordChart station={station} records={records} windowId={state.windowId} productKey={state.productKey} role={role}/> : status === "error" ? <div className="data-error" role="alert"><p>{station.name}: {error}</p><button type="button" aria-label={`Retry ${station.name}`} onClick={() => props.onRetryStation(station.station_id)}>Retry {station.name}</button></div> : <p className="loading-record" role="status">Loading and verifying {station.name} records…</p>}
      <footer className="source-strip">
        <p>Source: {station.source.publisher} · {station.source.title}</p>
        <p>Source time basis: {station.time_basis}; verified observations plotted in UTC. Vertical datum: {station.vertical_reference}; horizontal datum: {station.horizontal_datum}. Source QC retained; empty flags do not certify QC pass.</p>
        <div>{url ? <a href={url} target="_blank" rel="noopener noreferrer">Publisher record ↗</a> : <span>Source link unavailable; provenance retained.</span>}<button type="button" aria-label={`Rows & sources: ${station.name}`} disabled={!ready} onClick={() => props.onOpenEvidence(station.station_id)}>Rows &amp; sources</button></div>
      </footer>
    </article>;
  }

  function support(selection: StationSelection, role: "Selected" | "Pinned reference") {
    return <section className="radial-demo__station-support" aria-label={`${role} support: ${selection.station.name}`}>
      <h3>{role}: {selection.station.name} · {selection.station.station_id}</h3>
      {selection.status === "ready" && selection.records ? <SupportView station={selection.station} records={selection.records} windowId={state.windowId} productKey={state.productKey}/> : <p>{selection.status === "error" ? "Support unavailable until the station record is verified; retry from its record arm." : "Source support is loading with this station’s record."}</p>}
    </section>;
  }

  return <section className="radial-demo" aria-label="Station-linked radial evidence lens">
    {recordArm(selected, "selected")}
    <article className="radial-demo__support" aria-label="Separate station temporal support">
      <header><span className="role-badge">02 / Source support</span><h2>A record and its gaps</h2><p>Separate denominators, not a pooled coverage score. Zero is not missing.</p></header>
      {state.windowId === "source_full" && <p>Full source record — station-specific bounds; not a common comparison period. Each record retains its own exact interval.</p>}
      {support(selected, "Selected")}
      {pinned && support(pinned, "Pinned reference")}
    </article>
    {pinned ? recordArm(pinned, "pinned") : <article className="station-card station-card--empty radial-demo__trace radial-demo__trace--pinned"><h2>No reference pinned</h2><p>Use “Pin selected as reference” in More controls to retain a separate station identity.</p></article>}
    <section className="radial-demo__focus" aria-label="Station geography and bounded focus targets">
      <div className="radial-demo__anchor"><span className="role-badge">Station focus</span><h2>{selected.station.name}</h2><p>{manifest.windows.find(window => window.id === state.windowId)?.label}</p></div>
      {props.geometry ? <StationMap geometry={props.geometry} stations={manifest.stations} selectedStationId={state.selectedStationId} pinnedStationId={state.pinnedStationId} onSelectStation={props.onSelectStation}/> : props.geometryError ? <div className="data-error" role="alert"><p>Locator unavailable: {props.geometryError}</p><button type="button" aria-label="Retry locator" onClick={props.onRetryGeometry}>Retry locator</button><p>The shared station selector remains available.</p></div> : <p role="status">Loading reviewed Pacific locator…</p>}
      <details className="radial-demo__targets"><summary>Move focus between station targets</summary><p>Known stations only, in source-list order. Moving focus does not move the pinned reference.</p><div>
        <button type="button" aria-label="Previous station target" aria-describedby="radial-previous-target" disabled={!previous} onClick={() => {if (previous) props.onSelectStation(previous.station_id);}}>← Previous<span id="radial-previous-target">{previous ? previous.name : "Start of station list"}</span></button>
        <button type="button" aria-label="Next station target" aria-describedby="radial-next-target" disabled={!next} onClick={() => {if (next) props.onSelectStation(next.station_id);}}>Next →<span id="radial-next-target">{next ? next.name : "End of station list"}</span></button>
      </div></details>
      {pinned?.station.station_id === selected.station.station_id && <p className="radial-demo__same">Selected and pinned are the same station — not independent comparison evidence.</p>}
      <p className="radial-demo__note">Location and connector lengths carry no quantity. Empty ocean supplies no value. Descriptive records, not validated arrivals or warning time.</p>
    </section>
  </section>;
}
