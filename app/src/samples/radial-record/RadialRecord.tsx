import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function RadialRecord() {
  const [stationA, stationB] = stationFixtures;
  return <main className="radial-record">
    <header className="radial-record__intro">
      <div><p className="radial-record__eyebrow">02 / THE STATION LENS</p><h1>One focus.<br /><em>Three ways to read it.</em></h1></div>
      <div className="radial-record__lead"><p>A record, its gaps, and a second perspective—held around one fictional station.</p><p>{fixtureNotice}. A flat layout study, not a warning tool.</p></div>
    </header>

    <section className="radial-record__lens" aria-label="Three chart-bearing arms around Station A">
      <div className="radial-record__connections" aria-hidden="true"><i /><i /><i /></div>
      <div className="radial-record__focus">
        <p className="radial-record__eyebrow">FOCUS / FICTIONAL</p><h2>Station A</h2>
        <StationMap stations={stationFixtures} highlightedId={stationA.id} />
        <p className="radial-record__focus-note">A place to anchor the reading.<br />Not an arrival estimate.</p>
      </div>

      <article className="radial-record__arm radial-record__arm--trace" aria-label="Station A water-level trace">
        <header><span className="radial-record__number">01</span><div><p className="radial-record__eyebrow">THE RECORD / STATION A</p><h2>Water-level trace</h2></div></header>
        <p className="radial-record__description">Follow the line from left to right. Time never wraps around the lens.</p>
        <TraceChart station={stationA} />
      </article>

      <article className="radial-record__arm radial-record__arm--comparison" aria-label="Station B comparison trace">
        <header><span className="radial-record__number">03</span><div><p className="radial-record__eyebrow">THE COMPARISON / STATION B</p><h2>A second perspective</h2></div></header>
        <p className="radial-record__description">Fictional Station B. Same scales as A; a separate example record.</p>
        <TraceChart station={stationB} />
      </article>

      <article className="radial-record__arm radial-record__arm--coverage" aria-label="Station A observation coverage">
        <header><span className="radial-record__number">02</span><div><p className="radial-record__eyebrow">THE GAPS / STATION A</p><h2>Observation coverage</h2></div></header>
        <CoverageChart station={stationA} />
      </article>
    </section>
    <aside className="radial-record__closing"><p>Different questions.<br /><em>Separate views.</em></p><p>The arms organize the reading, not the quantities. There is no radial score, circular time scale or physical arrival field. All stations, positions and values are fictional.</p></aside>
  </main>;
}
