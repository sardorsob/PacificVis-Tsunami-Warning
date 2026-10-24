import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function PairedAtlas() {
  return <main className="paired-atlas">
    <section className="paired-atlas__intro" aria-labelledby="paired-atlas-title">
      <div><p className="paired-atlas__eyebrow">01 / PAIRED ATLAS</p><h1 id="paired-atlas-title">One ocean.<br /><em>Two perspectives.</em></h1></div>
      <div className="paired-atlas__lead"><p>A shared geography, with room to read each record.</p><p>Compare the shape of two fictional station traces on the same time and water-level scales.</p><span className="paired-atlas__notice">{fixtureNotice}. Not a warning tool.</span></div>
    </section>

    <section className="paired-atlas__geography" aria-labelledby="paired-map-title">
      <div className="paired-atlas__map-copy"><p className="paired-atlas__eyebrow">THE SPATIAL VIEW</p><h2 id="paired-map-title">Start with<br /> a sense of place.</h2><p>Two markers locate the examples. The records below remain separate: a map position is not an arrival estimate.</p><div className="paired-atlas__map-key"><span><i /> Fictional station</span><span>Illustrative layout · no physical arrival field</span></div></div>
      <StationMap stations={stationFixtures} highlightedId="station-a" />
    </section>

    <section className="paired-atlas__records" aria-label="Aligned fictional station records">
      <div className="paired-atlas__section-title"><p className="paired-atlas__eyebrow">THE RECORD VIEW</p><p>Same scales. Missing stays missing.</p></div>
      <div className="paired-atlas__pair">
        {stationFixtures.map((station, index) => <article className="paired-atlas__record" key={station.id}>
          <header><span className="paired-atlas__station-index">{index === 0 ? "A" : "B"}</span><div><h2>{station.name}</h2><p>{station.setting}</p></div><span className="paired-atlas__record-tag">Fictional</span></header>
          <h3>Water-level trace</h3><TraceChart station={station} />
          <div className="paired-atlas__coverage"><h3>Observation coverage</h3><CoverageChart station={station} /></div>
        </article>)}
      </div>
    </section>
    <aside className="paired-atlas__closing"><span>READING THE EXAMPLES</span><p>A gap in a record is a gap in knowledge.<br />It does not mean the water level was zero.</p><p>{fixtureNotice}. All stations, positions and values are fictional. No measured arrivals, alert timestamps or evacuation guidance are shown.</p></aside>
  </main>;
}
