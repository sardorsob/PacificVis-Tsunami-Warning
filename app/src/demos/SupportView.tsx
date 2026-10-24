import { useMemo } from "react";
import { selectWindow, formatUtc } from "./chart";
import type { ProductKey, StationMetadata, StationRecords } from "./types";

export type SupportViewProps={station:StationMetadata;records:StationRecords;windowId:string;productKey:ProductKey;cursorMs?:number;compact?:boolean};
/** compact: the strip and one counts line for the story arm. cursorMs: the story clock, a time not an arrival. */
export function SupportView({station,records,windowId,productKey,cursorMs,compact=false}:SupportViewProps) {
  const {support,rows,coverageSpans,gapBlocks}=useMemo(()=>selectWindow(records,windowId),[records,windowId]);
  const start=Date.parse(support.start_utc),end=Date.parse(support.end_utc_exclusive);
  const fraction=(time:string)=>(Date.parse(time)-start)/Math.max(1,end-start)*100;
  const cursor=cursorMs!==undefined&&cursorMs>=start&&cursorMs<end?(cursorMs-start)/Math.max(1,end-start)*100:null;
  const strip=support.support_kind==="coastal_exact_grid"
    ?<div className="support-strip" aria-label="Reviewed exact-grid spans: observed, source blank, or absent timestamp">
      {coverageSpans.map((span,i)=><span key={i} className={`support-span support-span--${span.status}`} style={{left:`${Math.max(0,fraction(span.start_utc))}%`,width:`${Math.max(0,Math.min(100,fraction(span.end_utc_exclusive))-Math.max(0,fraction(span.start_utc)))}%`}}/>)}
      {cursor!==null&&<span className="clock-cursor" style={{left:`${cursor}%`}}/>}
    </div>
    :<svg className="dart-support" width="100%" height="24" preserveAspectRatio="none" viewBox="0 0 100 24" role="img" aria-label={`${support.accepted_sample_n} actual DART timestamps; no expected cadence inferred`}><path d={rows.map(r=>`M${fraction(r.observed_at_utc).toFixed(4)},7v10`).join("")} stroke="currentColor" strokeWidth="0.12"/>{cursor!==null&&<line className="clock-cursor" x1={cursor} x2={cursor} y1={0} y2={24} vectorEffect="non-scaling-stroke"/>}</svg>;
  if(compact)return <section className="support-view support-view--compact" aria-label={`${station.name} source support`}>
    {strip}
    <p>{support.support_kind==="coastal_exact_grid"
      ?`${support.valid_sample_n.toLocaleString("en-US")} raw values · ${support.absent_n??"unknown"} absent positions · ${support.source_blank_n} source blanks · ${support.off_grid_n??"unknown"} off-grid kept`
      :`${support.accepted_sample_n.toLocaleString("en-US")} actual timestamps · ${support.source_blank_n} source blanks · coastal-grid coverage not applicable`}</p>
    <p>Gaps are missing samples, not zeros. Nothing is interpolated.</p>
  </section>;
  return <section className="support-view" aria-label={`${station.name} source support`}>
    <h3>What supports this record</h3>
    {support.support_kind==="coastal_exact_grid"?<>
      {strip}
      <p className="support-key">Solid: observed exact-grid · hatched: source blank · outlined: absent timestamp</p>
      <p><strong>{support.strict_percent??"Not applicable"}{support.strict_percent!==null?"%":""}</strong> strict exact-grid coverage ({support.strict_numerator_n??"unknown"}/{support.strict_denominator_n??"unknown"})</p>
      <p>Sample density, separately: {support.sample_density_percent??"Not applicable"}{support.sample_density_percent!==null?"%":""} ({support.sample_density_numerator_n??"unknown"}/{support.sample_density_denominator_n??"unknown"})</p>
      <p>{support.absent_n??"unknown"} absent positions · {support.source_blank_n} source blanks · {support.off_grid_n??"unknown"} off-grid rows retained ({support.off_grid_valid_n??"unknown"} raw-valid). Off-grid samples do not fill exact-grid gaps.</p>
      <details><summary>Reviewed grid and gap context</summary><p>Cadence: {support.cadence_seconds??"unknown"} seconds; source grid anchor: {formatUtc(support.source_grid_anchor_utc)}. Expected positions: {support.expected_n??"unknown"}; exact raw-valid: {support.exact_valid_n??"unknown"}.</p><p>Supported source interval: [{formatUtc(support.supported_start_utc)}, {formatUtc(support.supported_end_utc_exclusive)}). First/last grid: {formatUtc(support.first_grid_utc)} / {formatUtc(support.last_grid_utc)}. First/last raw-valid: {formatUtc(support.first_valid_raw_utc)} / {formatUtc(support.last_valid_raw_utc)}.</p><p>{gapBlocks.length} reviewed gap blocks; classifications describe source support, not causes. Exact span and row inspection is reserved for the evidence panel.</p></details>
    </>:<>
      {strip}
      <p>Strict coastal-grid coverage: <strong>Not applicable</strong>. {support.accepted_sample_n} actual timestamps, {support.valid_sample_n} raw-valid, {support.source_blank_n} source blanks.</p>
      <p>Actual successive deltas: {support.cadence_seconds_counts.map(c=>`${c.seconds}s × ${c.count}`).join("; ")}. These do not establish expected completeness or outage causes.</p>
    </>}
    <p>{support.product_valid_n[productKey]} non-null selected-product values / {support.accepted_sample_n} source rows. Zero is a value; blanks and absent timestamps are not zero. Source QC is retained, not filtered.</p>
  </section>;
}
