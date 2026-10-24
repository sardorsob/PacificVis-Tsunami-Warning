import { fixtureNotice, stationFixtures } from "../fixtures";
import { CoverageChart, StationMap, TraceChart } from "../primitives";
import "./style.css";

export function EditorialStory() {
  const [stationA, stationB] = stationFixtures;
  return <main className="editorial-story">
    <article className="editorial-story__essay" aria-labelledby="editorial-story-title">
      <header className="editorial-story__masthead">
        <p className="editorial-story__eyebrow">05 / A RECORD READER · APPEARANCE STUDY</p>
        <h1 id="editorial-story-title">What a record leaves unsaid.</h1>
        <p className="editorial-story__standfirst">A line can show a pattern. Its breaks tell us where to stop reading.</p>
        <p className="editorial-story__notice">{fixtureNotice}. Fictional stations, positions and values. Not a warning tool.</p>
      </header>

      <section className="editorial-story__place" aria-labelledby="editorial-story-place">
        <div className="editorial-story__prose"><p className="editorial-story__eyebrow">01 / LOCATE</p><h2 id="editorial-story-place">First, a place to look.</h2><p>Imagine two stations in a schematic Pacific. The map offers a way into the page, not a claim about the ocean.</p><p>We call them Station A and Station B. Neither is a real observing site. Their positions cannot establish an arrival time or explain a water-level change.</p></div>
        <StationMap stations={stationFixtures} />
      </section>

      <section className="editorial-story__passage" aria-labelledby="editorial-story-read">
        <div className="editorial-story__prose"><p className="editorial-story__eyebrow">02 / READ</p><h2 id="editorial-story-read">Follow the line.<br />Respect the break.</h2><p>At fictional Station A, the example runs from minute 0 to minute 60. The vertical scale is water level in centimetres; the horizontal scale is elapsed example time.</p><p>Some values are unavailable. The trace stops there. Drawing through the empty interval would imply evidence that this example does not have.</p></div>
        <div className="editorial-story__evidence" aria-label="Station A evidence"><header><h3>{stationA.name} <span>Fictional · {stationA.setting}</span></h3></header><h4>Water-level trace</h4><TraceChart station={stationA} /><h4>Observation coverage</h4><CoverageChart station={stationA} /></div>
      </section>

      <aside className="editorial-story__pullquote"><p>“Unavailable” is not another way to say “zero.”</p><span>A reading principle, not a result from these invented examples.</span></aside>

      <section className="editorial-story__passage editorial-story__passage--second" aria-labelledby="editorial-story-compare">
        <div className="editorial-story__prose"><p className="editorial-story__eyebrow">03 / COMPARE</p><h2 id="editorial-story-compare">Another record.<br />The same restraint.</h2><p>Station B uses the same scales and a different invented trace. Read its coverage alongside its line, just as with Station A.</p><p>The different shapes are a layout demonstration, not a scientific comparison. No modeled arrivals, measured first deviations or alert timestamps are provided here.</p></div>
        <div className="editorial-story__evidence" aria-label="Station B evidence"><header><h3>{stationB.name} <span>Fictional · {stationB.setting}</span></h3></header><h4>Water-level trace</h4><TraceChart station={stationB} /><h4>Observation coverage</h4><CoverageChart station={stationB} /></div>
      </section>

      <footer className="editorial-story__colophon"><p className="editorial-story__eyebrow">THE LIMIT OF THIS PAGE</p><h2>An illustration, not an inference.</h2><p>{fixtureNotice}. All evidence on this page is a deterministic appearance fixture. It supports judging the page’s hierarchy and reading order, not estimating warning time. No operational or evacuation guidance is shown.</p></footer>
    </article>
  </main>;
}
