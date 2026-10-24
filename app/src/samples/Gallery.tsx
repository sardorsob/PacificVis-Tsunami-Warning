import { resolveSample, sampleDefinitions } from "./registry";
import "./gallery.css";

export function Gallery({ search = typeof window === "undefined" ? "" : window.location.search }: { search?: string }) {
  const sample = resolveSample(search);
  const Component = sample.Component;
  return <div className="sample-gallery">
    <header className="sample-gallery__chrome">
      <a className="sample-gallery__identity" href="/samples.html">PACIFIC / APPEARANCE LAB</a>
      <nav aria-label="Appearance samples">
        {sampleDefinitions.map((definition, index) => <a key={definition.id} href={`?sample=${definition.id}`} aria-current={definition.id === sample.id ? "page" : undefined}><span>{String(index + 1).padStart(2, "0")}</span> {definition.name}</a>)}
      </nav>
      <span className="sample-gallery__badge">UI study · illustrative only</span>
    </header>
    <Component />
    <footer className="sample-gallery__footer">Appearance prototype · {sample.question} No operational or scientific interpretation.</footer>
  </div>;
}
