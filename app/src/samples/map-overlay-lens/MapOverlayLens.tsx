import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function MapOverlayLens() {
  const [stationA, stationB] = stationFixtures;
  return <main className="map-overlay-lens">
    <header className="map-overlay-lens__intro">
      <div><p className="map-overlay-lens__eyebrow">07 / A LENS IN PLACE</p><h1>A broad view.<br />A close reading.</h1></div>
      <div><p>Two upright chart arms stay connected to fictional Station A, without turning time into a circle.</p><p className="map-overlay-lens__notice">{fixtureNotice}. Fictional positions and values. Not a warning tool.</p></div>
    </header>
    <section className="map-overlay-lens__atlas" aria-label="Static chart-bearing lens anchored to Station A">
      <div className="map-overlay-lens__status"><strong>Station A · fixed focus</strong><span>Static appearance study · not draggable</span></div>
      <div className="map-overlay-lens__canvas">
        <StationMap stations={stationFixtures} highlightedId={stationA.id} />
        <div className="map-overlay-lens__anchor" aria-hidden="true"><i /><i /></div>
        <article className="map-overlay-lens__arm map-overlay-lens__arm--trace" aria-label="Station A water-level trace">
          <header><span>01 / STATION A</span><h2>Water-level trace</h2></header>
          <TraceChart station={stationA} />
        </article>
        <article className="map-overlay-lens__arm map-overlay-lens__arm--coverage" aria-label="Station A observation coverage">
          <header><span>02 / STATION A</span><h2>Observation coverage</h2></header>
          <CoverageChart station={stationA} />
        </article>
      </div>
      <p className="map-overlay-lens__reading">Below the map on small screens, the same arms become a detail stack. The connector means station ownership, not a route or an arrival field.</p>
    </section>
    <aside className="map-overlay-lens__reference" aria-label="Station B reference trace">
      <div><p className="map-overlay-lens__eyebrow">OUTSIDE THE LENS / FICTIONAL REFERENCE</p><h2>Station B</h2><p>A quiet reference on the same scales. Missing observations remain gaps, never zero.</p></div>
      <TraceChart station={stationB} />
    </aside>
  </main>;
}
