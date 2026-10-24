import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function TimelineMap() {
  return <main className="timeline-map">
    <header className="timeline-map__intro">
      <p className="timeline-map__eyebrow">04 / TIMELINE MAP · APPEARANCE STUDY</p>
      <h1>Two records. One shared timeline.</h1>
      <p className="timeline-map__dek">Read from left to right. Keep the missing moments in view.</p>
      <p className="timeline-map__notice">{fixtureNotice}. Fictional stations and values; not a warning tool.</p>
    </header>

    <section className="timeline-map__rail" aria-label="Shared elapsed example time">
      <div className="timeline-map__rail-heading"><h2>0–60 minutes</h2><p>Elapsed example time →<br /><span>Linear, not an arrival prediction</span></p></div>
      <div className="timeline-map__ticks" aria-hidden="true"><span>MINUTES</span><div>{[0, 20, 40, 60].map((minute) => <span key={minute} style={{ gridColumn: minute / 5 + 1 }}>{minute}</span>)}</div></div>
      {stationFixtures.map((station) => <div className="timeline-map__track" key={station.id}>
        <h3>{station.name}</h3>
        <div className="timeline-map__samples" aria-label={`${station.name} observation overview`}>
          {station.points.map((point) => <span key={point.minute} className={point.value === null ? "timeline-map__point timeline-map__point--missing" : "timeline-map__point"} role="img" aria-label={`Minute ${point.minute}: ${point.value === null ? "Unavailable" : "Available"}`} />)}
        </div>
      </div>)}
      <div className="timeline-map__rail-foot"><p><i /> Available <i className="timeline-map__legend-missing" /> Unavailable</p><p>Each mark is one 5-minute example sample, including minute 60.</p></div>
      <p className="timeline-map__rail-source">{fixtureNotice}. This rail shows coverage only, not water level.</p>
    </section>

    <div className="timeline-map__evidence">
      <aside className="timeline-map__place" aria-labelledby="timeline-map-place">
        <p className="timeline-map__eyebrow">WHERE THE EXAMPLES SIT</p><h2 id="timeline-map-place">A spatial footnote.</h2>
        <StationMap stations={stationFixtures} />
        <p>The map locates two fictional examples. It cannot explain a trace or establish an arrival time.</p>
      </aside>
      <section className="timeline-map__records" aria-label="Station evidence behind the shared timeline">
        {stationFixtures.map((station) => <article className="timeline-map__record" key={station.id} aria-label={`${station.name} evidence`}>
          <header><h2>{station.name}</h2><p>Fictional · {station.setting}</p></header>
          <div className="timeline-map__record-charts"><section><h3>Water-level trace</h3><TraceChart station={station} /></section><section><h3>Observation coverage</h3><CoverageChart station={station} /></section></div>
        </article>)}
      </section>
    </div>
    <footer className="timeline-map__closing"><strong>Same time axis. Separate evidence.</strong><p>Unavailable is not zero. These invented examples contain no measured arrivals, alert timestamps or evacuation guidance.</p></footer>
  </main>;
}
