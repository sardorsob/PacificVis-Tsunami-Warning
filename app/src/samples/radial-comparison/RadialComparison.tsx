import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function RadialComparison() {
  const [stationA, stationB] = stationFixtures;
  return <main className="radial-comparison">
    <header className="radial-comparison__intro"><div><p className="radial-comparison__eyebrow">03 / THE COMPARISON ORBIT</p><h1>Keep one.<br /><em>Look at another.</em></h1></div><div className="radial-comparison__intro-note"><p>Two records orbit a shared focus.<br />Neither loses its identity.</p><p>{fixtureNotice}. Not a warning tool.</p></div></header>

    <section className="radial-comparison__orbit" aria-label="Pinned A and selected B comparison lens">
      <div className="radial-comparison__orbital-line" aria-hidden="true" />
      <div className="radial-comparison__focus"><p className="radial-comparison__eyebrow">THE SHARED FOCUS</p><h2>A ↔ B</h2><StationMap stations={stationFixtures} highlightedId={stationB.id} /><p className="radial-comparison__static">Static selection · fictional stations</p></div>

      <article className="radial-comparison__record radial-comparison__record--pinned" aria-label="Pinned Station A record">
        <header><span className="radial-comparison__letter">A</span><div><p className="radial-comparison__eyebrow">Pinned A</p><h2>{stationA.name}</h2><p>{stationA.setting} · Fictional</p></div><span className="radial-comparison__status">REFERENCE</span></header>
        <h3>Water-level trace</h3><TraceChart station={stationA} />
        <div className="radial-comparison__coverage"><h3>Observation coverage · A</h3><CoverageChart station={stationA} /></div>
      </article>

      <aside className="radial-comparison__reading"><span>01 / HOLD THE FRAME</span><p>Same time window.<br />Same water-level scale.</p><p>Compare shapes without blending the two records into one.</p></aside>

      <article className="radial-comparison__record radial-comparison__record--selected" aria-label="Selected Station B record">
        <header><span className="radial-comparison__letter">B</span><div><p className="radial-comparison__eyebrow">Selected B</p><h2>{stationB.name}</h2><p>{stationB.setting} · Fictional</p></div><span className="radial-comparison__status">COMPARISON</span></header>
        <h3>Water-level trace</h3><TraceChart station={stationB} />
        <div className="radial-comparison__coverage"><h3>Observation coverage · B</h3><CoverageChart station={stationB} /></div>
      </article>

      <aside className="radial-comparison__missing"><span>02 / KEEP THE GAPS</span><p>A missing segment is not a flat sea.</p><p>Outlined cells are unavailable samples, not zero measurements.</p></aside>
    </section>
    <footer className="radial-comparison__closing"><span>AN ORBIT FOR READING, NOT A SCALE</span><p>Linear charts, separate owners, schematic geography. No hazard score, arrival field or measured warning window. All positions and values are invented.</p></footer>
  </main>;
}
