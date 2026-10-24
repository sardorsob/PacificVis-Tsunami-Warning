import { fixtureNotice, stationFixtures } from "../fixtures";
import { StationMap, TraceChart } from "../primitives";
import "./style.css";

export function EvidenceLedger() {
  const [stationA, stationB] = stationFixtures;
  return <main className="evidence-ledger">
    <header className="evidence-ledger__intro">
      <p className="evidence-ledger__eyebrow">08 / THE EVIDENCE DESK</p>
      <h1>The line, then every value.</h1>
      <p className="evidence-ledger__lead">An open ledger for two fictional records. Read their shapes, then inspect the exact example inputs.</p>
      <p className="evidence-ledger__notice">{fixtureNotice}. Fictional stations, positions and values. Not a warning tool.</p>
    </header>
    <section className="evidence-ledger__traces" aria-label="Aligned station traces">
      {stationFixtures.map((station) => <article key={station.id} aria-label={`${station.name} water-level trace`}>
        <header><h2>{station.name}</h2><p>Fictional · {station.setting}</p></header>
        <TraceChart station={station} />
      </article>)}
    </section>
    <div className="evidence-ledger__desk">
      <section className="evidence-ledger__values" aria-label="Raw fixture values">
        <table>
          <caption>Raw fixture ledger · {fixtureNotice}. Values in cm; elapsed example time in minutes.</caption>
          <thead><tr><th scope="col">Elapsed example time (minutes)</th><th scope="col">Station A (cm)</th><th scope="col">Station B (cm)</th></tr></thead>
          <tbody>{stationA.points.map((point, index) => <tr key={point.minute}><th scope="row">{point.minute}</th><td>{point.value ?? "Unavailable"}</td><td>{stationB.points[index].value ?? "Unavailable"}</td></tr>)}</tbody>
        </table>
      </section>
      <aside className="evidence-ledger__margin">
        <p className="evidence-ledger__eyebrow">READING NOTE / 01</p>
        <h2>Missing is a value<br />we do not have.</h2>
        <p>Unavailable marks an absent fixture observation. It is not zero and the line does not bridge it.</p>
        <p>Both traces use the same water-level and linear time scales. The table lists the original 5-minute example samples, without interpolation.</p>
        <div className="evidence-ledger__locator"><h3>Orientation only</h3><StationMap stations={stationFixtures} /></div>
        <p className="evidence-ledger__limit">This desk exposes invented layout inputs, not source evidence, measured arrivals or scientific results.</p>
      </aside>
    </div>
  </main>;
}
