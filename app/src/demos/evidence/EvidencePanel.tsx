import { useEffect, useId, useMemo, useRef, useState } from "react";
import { selectWindow } from "../chart";
import { safeSourceUrl } from "../loader";
import type { CoverageSpan, EvidenceProps, Support } from "../types";
import { evidencePage, EVIDENCE_PAGE_SIZE } from "./paging";
import "./style.css";

type Detail = readonly [string, string | number | null];

function Metadata({ entries }: { entries: readonly Detail[] }) {
  return <dl className="evidence__metadata">{entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "unknown"}</dd></div>)}</dl>;
}

function PageControls({ page, pageCount, start, end, count, onPage, label }: { page: number; pageCount: number; start: number; end: number; count: number; onPage: (page: number) => void; label: string }) {
  const id = useId();
  const [draft, setDraft] = useState(String(page));
  useEffect(() => setDraft(String(page)), [page]);
  return <form className="evidence__paging" aria-label={`${label} paging`} onSubmit={event => { event.preventDefault(); onPage(Number(draft)); setDraft(String(Math.max(1, Math.min(pageCount, Math.trunc(Number(draft)) || 1)))); }}>
    <p role="status">{count ? `Rows ${start + 1}–${end} of ${count}` : "0 source rows"} · {EVIDENCE_PAGE_SIZE} per page</p>
    <div><span className="evidence__step"><button type="button" disabled={page === 1} onClick={() => onPage(page - 1)}>Previous</button>
      <button type="button" disabled={page === pageCount} onClick={() => onPage(page + 1)}>Next</button></span>
      <label htmlFor={id}>Page <input id={id} type="number" min="1" max={pageCount} step="1" value={draft} onChange={event => setDraft(event.currentTarget.value)} /></label>
      <span>of {pageCount}</span><button type="submit">Go</button></div>
  </form>;
}

function SpanTable({ spans, label, identity }: { spans: CoverageSpan[]; label: string; identity: string }) {
  const [position, setPosition] = useState({ identity, page: 1 });
  const page = evidencePage(spans, position.page, position.identity, identity);
  useEffect(() => setPosition({ identity, page: 1 }), [identity]);
  return <details className="evidence__spans"><summary>{label} ({spans.length})</summary>
    {spans.length === 0 ? <p>No reviewed {label.toLowerCase()} supplied; no missingness or outage cause is inferred.</p> : <>
      <PageControls {...page} count={spans.length} label={label} onPage={next => setPosition({ identity, page: next })} />
      <p>Scroll sideways to inspect all columns.</p>
      <div className="evidence__table-region" role="region" aria-label={`${label} — horizontally scrollable`} tabIndex={0}>
        <table><caption>{label}: original reviewed fields; UTC intervals are half-open.</caption>
          <thead><tr>{["Start UTC", "End UTC (exclusive)", "Status", "Absent", "Source blank", "Affected positions", "Classification", "Classification semantics", "Endpoint semantics", "Left observed UTC", "Right observed UTC", "Within-block raw-valid"].map(text => <th scope="col" key={text}>{text}</th>)}</tr></thead>
          <tbody>{page.rows.map((span, i) => <tr key={`${span.start_utc}-${i}`}><td>{span.start_utc}</td><td>{span.end_utc_exclusive}</td><td>{span.status}</td><td>{span.absent_n}</td><td>{span.source_blank_n}</td><td>{span.affected_position_n}</td><td>{span.classification}</td><td>{span.classification_semantics}</td><td>{span.endpoint_semantics}</td><td>{span.left_observed_utc}</td><td>{span.right_observed_utc}</td><td>{span.within_block_valid_raw_n}</td></tr>)}</tbody>
        </table>
      </div>
    </>}
  </details>;
}

function SupportDetails({ support, productKey }: { support: Support; productKey: EvidenceProps["productKey"] }) {
  return <>
    <p>{`${support.product_valid_n[productKey]} non-null selected-product values / ${support.accepted_sample_n} source rows`}. Raw-valid count: {support.valid_sample_n}; source blanks: {support.source_blank_n}.</p>
    {support.support_kind === "coastal_exact_grid" ? <>
      <p>Strict exact-grid coverage: {support.strict_percent === null ? "Not applicable" : `${support.strict_percent}% (${support.strict_numerator_n}/${support.strict_denominator_n})`}.</p>
      <p>Sample density, separately: {support.sample_density_percent === null ? "Not applicable" : `${support.sample_density_percent}% (${support.sample_density_numerator_n}/${support.sample_density_denominator_n})`}.</p>
      <p>Absent exact-grid positions: {support.absent_n ?? "unknown"}; off-grid rows retained: {support.off_grid_n ?? "unknown"} ({support.off_grid_valid_n ?? "unknown"} raw-valid). Off-grid samples do not fill exact-grid gaps.</p>
      <details><summary>Reviewed coastal-grid context</summary><Metadata entries={[
        ["Expected grid positions", support.expected_n], ["Exact raw-valid", support.exact_valid_n], ["Cadence (seconds)", support.cadence_seconds], ["Source grid anchor UTC", support.source_grid_anchor_utc],
        ["Supported start UTC", support.supported_start_utc], ["Supported end UTC (exclusive)", support.supported_end_utc_exclusive], ["First grid UTC", support.first_grid_utc], ["Last grid UTC", support.last_grid_utc], ["First raw-valid UTC", support.first_valid_raw_utc], ["Last raw-valid UTC", support.last_valid_raw_utc],
      ]} /></details>
    </> : <>
      <p>Strict coastal-grid coverage: Not applicable. {support.accepted_sample_n} actual timestamps; no expected coastal grid is assigned.</p>
      <p>Actual successive deltas: {support.cadence_seconds_counts.map(delta => `${delta.seconds}s × ${delta.count}`).join("; ") || "none supplied"}. These do not establish expected completeness or outage causes.</p>
    </>}
  </>;
}

export function EvidencePanel({ manifest, station, records, windowId, productKey, onClose }: EvidenceProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const titleId = useId(), descriptionId = useId();
  const identity = `${station.station_id}|${windowId}|${productKey}`;
  const [position, setPosition] = useState({ identity, page: 1 });
  const { rows, support, coverageSpans, gapBlocks } = useMemo(() => selectWindow(records, windowId), [records, windowId]);
  const page = evidencePage(rows, position.page, position.identity, identity);
  const product = station.products.find(item => item.key === productKey);
  const productLabel = `${product?.label ?? productKey} (${product?.units ?? "unknown"})`;
  const publisherUrl = safeSourceUrl(station.source.url);
  useEffect(() => setPosition({ identity, page: 1 }), [identity]);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    // Native modal supplies inert background, focus containment and Escape/cancel.
    element.showModal();
    close.current?.focus({ preventScroll: true });
    return () => { if (element.open) element.close(); };
  }, []);

  return <dialog ref={dialog} className="evidence-panel" aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="evidence__header"><h2 id={titleId}>Rows &amp; sources · {station.name} <span>({station.station_id})</span></h2><button ref={close} type="button" onClick={onClose}>Close</button></header>
    <div className="evidence__body">
      <p id={descriptionId}>Descriptive records, not validated arrivals or warning time.</p>
      <section aria-label="Selected evidence interval" className="evidence__section">
        <h3>{windowId === "source_full" ? "Full source record — station-specific bounds" : manifest.windows.find(window => window.id === windowId)?.label ?? windowId}</h3>
        <p className="evidence__bounds">[{support.start_utc}, {support.end_utc_exclusive})</p>
        {windowId === "source_full" && <p>Not a common comparison period. Bounds belong to this station; a DART last+1µs endpoint is a containing interval, not expected coverage.</p>}
        <p>{productLabel} · {product?.available ? "Source product available; interval count below" : "Unavailable for this station — no substitute product"}.</p>
      </section>
      <section aria-label="Exact observation inputs" className="evidence__section">
        <h3>Exact observation inputs</h3>
        <p>All selected-window source rows, including nulls and off-grid observations. Values are unrounded. Zero is a value; null is not zero. Absent timestamps are not fabricated rows. Source QC is retained, not filtered; empty flags do not certify a QC pass.</p>
        <PageControls {...page} count={rows.length} label="Observation rows" onPage={next => setPosition({ identity, page: next })} />
        <p>Scroll sideways to inspect all columns.</p>
        <div className="evidence__table-region" role="region" aria-label="Exact observation rows — horizontally scrollable" tabIndex={0}>
          <table><caption>{station.name} · {productLabel} · source inputs, page {page.page}</caption>
            <thead><tr>{["Observation ID", productLabel, "Observed at UTC", "Source time (original)", "Raw status", "Residual status", "Grid status", "Source QC status", "Publisher QC flags (verbatim)", "Row units", "Row vertical reference", "Source ID", "Station ID"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
            <tbody>{page.rows.map(row => <tr key={row.observation_id}><th scope="row">{row.observation_id}</th><td>{row[productKey] === null ? "null" : String(row[productKey])}</td><td>{row.observed_at_utc}</td><td>{row.source_time}</td><td>{row.raw_status}</td><td>{row.residual_status}</td><td>{row.grid_status}</td><td>{row.source_qc_status}</td><td><code>{JSON.stringify(row.qc_flags)}</code></td><td>{row.units}</td><td>{row.vertical_reference}</td><td>{row.source_id}</td><td>{row.station_id}</td></tr>)}</tbody>
          </table>
        </div>
        {rows.length === 0 && <p>No source observation rows in this reviewed window.</p>}
      </section>
      <section aria-label="Reviewed source support" className="evidence__section"><h3>Reviewed source support</h3>
        <SupportDetails support={support} productKey={productKey} />
        <SpanTable spans={coverageSpans} label="Coverage spans" identity={identity} />
        <SpanTable spans={gapBlocks} label="Gap blocks" identity={identity} />
      </section>
      <section aria-label="Source provenance" className="evidence__section"><h3>Source &amp; provenance</h3>
        <Metadata entries={[
          ["Publisher", station.source.publisher], ["Source product", station.source.title], ["Source ID", station.source.source_id], ["Retrieved on", station.source.accessed_on], ["Version or date", station.source.version_or_date], ["Terms", station.source.license_or_terms], ["Processing level", station.source.processing_level], ["Current product", productLabel], ["Source units", station.units], ["Source time basis", station.time_basis], ["Normalized observation time", "UTC"], ["Vertical reference", station.vertical_reference], ["Horizontal datum", station.horizontal_datum], ["Coordinate order", station.coordinate_order], ["Source SHA256", station.source.sha256], ["Bundle", manifest.bundle_id], ["Evidence state", manifest.evidence_state],
        ]} />
        <p>{publisherUrl ? <a href={publisherUrl} target="_blank" rel="noopener noreferrer">Open publisher source (new tab)</a> : "Publisher link unavailable"}.</p>
        <p>The source hash is a provenance fingerprint, not proof of scientific validity. Bundle integrity is relative to its local manifest, not a signature against whole-manifest replacement.</p>
      </section>
    </div>
  </dialog>;
}
