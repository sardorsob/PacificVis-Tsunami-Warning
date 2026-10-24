import { useState } from "react";
import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function MobileInspector() {
  const [selectedId, setSelectedId] = useState(stationFixtures[0].id);
  const station = stationFixtures.find((item) => item.id === selectedId) ?? stationFixtures[0];

  return <main className="mobile-inspector">
    <section className="mobile-inspector__atlas" aria-labelledby="mobile-inspector-title">
      <header className="mobile-inspector__intro">
        <p className="mobile-inspector__eyebrow">06 / MAP FIRST · APPEARANCE STUDY</p>
        <h1 id="mobile-inspector-title">A place above.<br />A record below.</h1>
        <p className="mobile-inspector__notice">{fixtureNotice}. Fictional stations, positions and values. Not a warning tool.</p>
      </header>
      <div className="mobile-inspector__map">
        <StationMap stations={stationFixtures} highlightedId={station.id} />
        <p className="mobile-inspector__lens"><span aria-hidden="true" />Selected · {station.name}</p>
      </div>
      <p className="mobile-inspector__map-note">The warm ring locates the selected example. It encodes no ocean value.</p>
    </section>

    <section className="mobile-inspector__sheet" aria-label={`${station.name} inspector`}>
      <div className="mobile-inspector__handle" aria-hidden="true" />
      <div className="mobile-inspector__selector">
        <label htmlFor="mobile-inspector-station">Inspect station</label>
        <select id="mobile-inspector-station" value={station.id} onChange={(event) => setSelectedId(event.target.value)} aria-describedby="mobile-inspector-help">
          {stationFixtures.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </div>
      <p id="mobile-inspector-help" className="mobile-inspector__help">Choose A or B to update the map and both charts.</p>
      <header className="mobile-inspector__identity" aria-live="polite" aria-atomic="true">
        <span className="mobile-inspector__index" aria-hidden="true">{station.name.slice(-1)}</span>
        <div><p className="mobile-inspector__eyebrow">FICTIONAL STATION</p><h2>{station.name}</h2><p>Fictional · {station.setting}</p></div>
      </header>
      <section className="mobile-inspector__record" aria-label={`${station.name} water-level trace`}>
        <div className="mobile-inspector__chart-heading"><h3>Water-level trace</h3><span>01 / RECORD</span></div>
        <TraceChart station={station} />
      </section>
      <section className="mobile-inspector__coverage" aria-label={`${station.name} observation coverage`}>
        <div className="mobile-inspector__chart-heading"><h3>Observation coverage</h3><span>02 / GAPS</span></div>
        <CoverageChart station={station} />
      </section>
      <aside className="mobile-inspector__limit"><h3>A gap is not zero.</h3><p>Read the line and its coverage together. These invented records are for judging this layout, not estimating arrivals or warning time.</p></aside>
    </section>
  </main>;
}
