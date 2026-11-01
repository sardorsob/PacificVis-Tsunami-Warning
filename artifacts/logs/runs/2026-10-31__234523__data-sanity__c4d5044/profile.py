"""Quick read-only quality profile using checksum-verified, previously row-audited sources.

Run from project root. Frozen data packages are never modified.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, UTC
import csv, gzip, hashlib, json, os, shutil, subprocess, sys

root=Path.cwd(); wave=root/'data/processed/arrival-waveforms/foundation-v4'
manifest=json.loads((wave/'manifest.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads((root/p).read_text())
selection=read('artifacts/generated/ntwc-batch/screen-v1/selection-v2.json')
events={r['event_id']:r for r in selection['events']}
prior=read('artifacts/generated/ntwc-batch/waveform-v4-root-review.json')
assert sha(wave/'manifest.json')==prior['manifest_sha256']
normalized=[s for s in manifest['sources'] if s.get('output_path')]
assert len(normalized)==1768 and len({s['source_id'] for s in manifest['sources']})==1902
valid_states={'reported_utc','epoch_calendar_agree','epoch_calendar_minute_agree','header_day_end_boundary'}
source_rows=[]; hashed=0
for s in manifest['sources']:
    if s.get('output_path'):
        path=wave/s['output_path'];assert sha(path)==s['output_sha256'],path;hashed+=1
    n=s.get('source_rows',0)
    source_rows.append(dict(source_id=s['source_id'],event_id=s.get('event_id','unknown'),provider=s.get('provider','unknown'),purpose=s.get('purpose','unknown'),status=s['processing_status'],rows=n,blank=s.get('value_states',{}).get('blank',0),finite=s.get('value_states',{}).get('finite_numeric',0),invalid_timestamp=n-sum(v for k,v in s.get('timestamp_states',{}).items() if k in valid_states),qc_not_provided=s.get('qc_states',{}).get('not_provided',0),duplicate_excess=s.get('duplicate_timestamp_excess',0),duplicate_affected_rows=s.get('duplicate_timestamp_rows',0),units=s.get('units','unknown'),datum=s.get('vertical_datum','unknown'),cadence_seconds=s.get('declared_cadence_seconds','unknown'),missing_grid_timestamps=s.get('missing_grid_timestamps','unknown')))
rows=[s for s in source_rows if s['status']=='normalized_source_samples']
def group(data,key):
    output=[]
    for value in sorted({str(r[key]) for r in data}):
        members=[r for r in data if str(r[key])==value];n=sum(r['rows'] for r in members)
        x={key:value,'files':len(members),'rows':n}
        for field in ['blank','finite','invalid_timestamp','qc_not_provided','duplicate_excess','duplicate_affected_rows']:x[field]=sum(r[field] for r in members)
        x['blank_pct']=100*x['blank']/n if n else None
        output.append(x)
    return output
counts={k:sum(r[k] for r in rows) for k in ['rows','blank','finite','invalid_timestamp','qc_not_provided','duplicate_excess','duplicate_affected_rows']}
assert counts['rows']==manifest['source_rows']==3688140
assert counts['blank']==prior['value_states']['blank'] and counts['finite']==prior['value_states']['finite_numeric']
by_provider=group(rows,'provider');by_event=group(rows,'event_id')
coops=[s for s in normalized if s['provider']=='CO-OPS'];grid_expected=grid_absent=grid_blank=0
for s in coops:
    start=datetime.fromisoformat(s['window_start_utc']);stop=datetime.fromisoformat(s['window_stop_utc'])
    expected=int((stop-start).total_seconds()/float(s['declared_cadence_seconds']))
    assert s['source_rows']+s['missing_grid_timestamps']==expected
    assert s['duplicate_timestamp_excess']==0
    grid_expected+=expected;grid_absent+=s['missing_grid_timestamps'];grid_blank+=s['value_states'].get('blank',0)
reports=[];pairs=[]
corpus=root/'data/processed/arrival-corpus/foundation-v4';summary=json.loads((corpus/'summary.json').read_text())
for rel,digest in summary['output_sha256'].items():assert sha(corpus/rel)==digest
for p in sorted(corpus.glob('*/arrival_report.csv.gz')):
    with gzip.open(p,'rt',newline='') as f:reports.extend(csv.DictReader(f))
for p in sorted(corpus.glob('*/pair.csv.gz')):
    with gzip.open(p,'rt',newline='') as f:pairs.extend(csv.DictReader(f))
assert len(reports)==len({r['report_id'] for r in reports})==1177
assert len(pairs)==len({r['report_id'] for r in pairs})==314
assert set(r['report_id'] for r in pairs)<=set(r['report_id'] for r in reports)
assert all(events[r['event_id']]['role']=='development' for r in reports)
modern=[r for r in reports if r['header_family'] in {'estimated_observed_utc_jday','computed_observed_utc','estimated_observed_gmt_jday'} and r['structural_status']=='accepted_source_row']
report_stats={'reports':len(reports),'parseable_pairs':len(pairs),'unresolved_or_rejected':len(reports)-len(pairs),'reviewed_identity_pairs':sum(r['event_site_identity_verified']=='True' for r in pairs),'events_with_parseable_pairs':len({r['event_id'] for r in pairs}),'estimate_states':dict(Counter(r['estimate_state'] for r in reports)),'observed_states':dict(Counter(r['observed_state'] for r in reports)),'modern_accepted_report_rows':len(modern),'modern_estimate_blank_or_missing_token':sum(r['estimate_state'] in {'blank','source_missing_token'} for r in modern),'modern_observed_blank_or_missing_token':sum(r['observed_state'] in {'blank','source_missing_token'} for r in modern),'header_families':dict(Counter(r['header_family'] for r in reports)),'structural_statuses':dict(Counter(r['structural_status'] for r in reports))}
by_magnitude=[]
for label,low,high in [('7.0–7.49',7,7.5),('7.5–7.99',7.5,8),('8.0+',8,20)]:
    ids={eid for eid,e in events.items() if e['role']=='development' and low<=float(e['usgs_mag'])<high}
    rr=[r for r in reports if r['event_id'] in ids];pp=[r for r in pairs if r['event_id'] in ids]
    by_magnitude.append(dict(magnitude=label,development_events=len(ids),events_with_normalized_waveforms=len(ids&{s['event_id'] for s in normalized}),reports=len(rr),parseable_pairs=len(pp),parseable_pair_pct=100*len(pp)/len(rr) if rr else None))
coverage=manifest['series_coverage']; coverage_summary=dict(rows=len(coverage),unknown_fraction=sum(not isinstance(c.get('coverage_fraction'),(float,int)) for c in coverage),display_eligible=sum(c.get('display_eligible') is True for c in coverage))
coverage_summary['known_fraction_quantiles']={}
known=sorted(c['coverage_fraction'] for c in coverage if isinstance(c.get('coverage_fraction'),(float,int)))
for label,p in [('min',0),('p25',.25),('median',.5),('p75',.75),('max',1)]:
    v=(len(known)-1)*p;i=int(v);coverage_summary['known_fraction_quantiles'][label]=known[i]+(known[min(i+1,len(known)-1)]-known[i])*(v-i)
observation_sources=[s for s in manifest['sources'] if s.get('purpose') in {'event_window','quiet_control'}]
unknown_datum={'unknown','none','unkown',''}
result={'scope':'Quick descriptive profile; all sources retained, controls separately identifiable; reserved labels excluded. Fresh checksums bind metrics to previously raw-row-audited waveforms; no new physical QC or onset validation.','counts':counts,'waveform_value_blank_pct':100*counts['blank']/counts['rows'],'waveform_unreleased_timestamp_pct':100*counts['invalid_timestamp']/counts['rows'],'waveform_qc_not_provided_pct':100*counts['qc_not_provided']/counts['rows'],'normalization_sources':dict(Counter(s['processing_status'] for s in manifest['sources'])),'observation_source_contracts':len(observation_sources),'observation_sources_without_normalized_table':sum(s['processing_status']!='normalized_source_samples' for s in observation_sources),'normalized_events':len({s['event_id'] for s in normalized}),'by_provider':by_provider,'by_event':by_event,'by_purpose':group(rows,'purpose'),'cadence_files':dict(Counter(str(float(s['declared_cadence_seconds'])) for s in normalized)),'units_files':dict(Counter(s['units'] for s in normalized)),'datum_files':dict(Counter(s['vertical_datum'] for s in normalized)),'unknown_or_unspecified_datum_files':sum(str(s['vertical_datum']).lower() in unknown_datum for s in normalized),'coops_requested_grid':{'files':len(coops),'expected_timestamps_across_source_snapshots':grid_expected,'absent_timestamps':grid_absent,'blank_values_in_returned_rows':grid_blank,'absent_timestamp_pct':100*grid_absent/grid_expected,'absent_or_blank_pct':100*(grid_absent+grid_blank)/grid_expected,'note':'Request/snapshot-weighted, includes repeated products/acquisitions. Only CO-OPS has verified complete requested-grid accounting; not an all-provider denominator.'},'reports':report_stats,'by_magnitude':by_magnitude,'coverage':coverage_summary,'checks':{'waveform_files_rehashed':hashed,'corpus_files_rehashed':len(summary['output_sha256']),'report_primary_keys_unique':True,'pair_primary_keys_unique':True,'pair_report_foreign_keys_valid':True,'reserved_report_rows':0,'waveform_counts_match_previous_raw_row_audit':True},'missingness_interpretation':{'mcar':'Poor general working assumption: report parseability and acquisition support vary across observed event/magnitude/provider/format characteristics. No formal MCAR hypothesis test performed.','mar':'Potential working assumption conditional on relevant observed covariates; not established by this profile.','mnar':'Plausible for arrival reporting if weak/ambiguous tsunami signals are less likely to yield labels, or extreme conditions affect instruments; hypothesis, not demonstrated from observed data.','by_design':'Reserved events, source headers, controls and excluded metadata records have intentional roles; do not count these as accidental missing values.','reference':'https://pmc.ncbi.nlm.nih.gov/articles/PMC7615108/'}}
sha_git=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();now=datetime.now(UTC)
out=root/'artifacts/logs/runs'/(now.strftime('%Y-%m-%d__%H%M%S')+'__data-sanity__'+sha_git[:7]);out.mkdir()
shutil.copyfile(__file__,out/'profile.py')
inputs=['data/processed/arrival-waveforms/foundation-v4/manifest.json','data/processed/arrival-corpus/foundation-v4/summary.json','artifacts/generated/ntwc-batch/screen-v1/selection-v2.json','artifacts/generated/ntwc-batch/waveform-v4-root-review.json','data/processed/multi-event/foundation-v1/manifest.json']
(out/'inputs.json').write_text(json.dumps({p:sha(root/p) for p in inputs},indent=2)+'\n')
(out/'summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
for name,data in [('sources',source_rows),('providers',by_provider),('events',by_event),('magnitude',by_magnitude)]:
    with (out/(name+'.csv')).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
meta={'run_id':out.name,'timestamp_utc':now.isoformat(),'git_sha':sha_git,'lane':'paper-data-quality','status':'descriptive_sanity_check','command':[sys.executable,*sys.argv]}
(out/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
metrics={k:v for k,v in counts.items()};metrics.update(value_blank_pct=result['waveform_value_blank_pct'],unreleased_timestamp_pct=result['waveform_unreleased_timestamp_pct'],qc_not_provided_pct=result['waveform_qc_not_provided_pct'],reports=1177,parseable_pairs=314,unresolved_report_pct=100*863/1177,reviewed_identity_pairs=148,normalized_events=result['normalized_events'])
(out/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
os.environ.setdefault('MLFLOW_ALLOW_FILE_STORE','true');os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT','true')
import mlflow
mlflow.set_tracking_uri((root/'.mlflow/mlruns').as_uri());mlflow.set_experiment('ntwc-arrival-foundation')
with mlflow.start_run(run_name=out.name,tags={'git_sha':sha_git,'lane':'paper-data-quality','portable_run_bundle':str(out.relative_to(root)),'decision':'descriptive_only; preserve_missingness; no_mcar_assumption'} ) as run:
    meta['mlflow_run_id']=run.info.run_id
    (out/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
    mlflow.log_params({'waveform_version':'foundation-v4','corpus_version':'foundation-v4','method':'checksum_bound_manifest_profile_and_report_row_recount','mcar_assumed':False,'model_fit':False})
    mlflow.log_metrics(metrics);mlflow.log_artifacts(str(out))
print(json.dumps({'bundle':str(out.relative_to(root)),'mlflow_run_id':meta['mlflow_run_id'],'counts':counts,'grid':result['coops_requested_grid'],'reports':report_stats,'by_magnitude':by_magnitude,'top_provider_counts':sorted(by_provider,key=lambda r:-r['rows'])[:5],'coverage':coverage_summary,'checks':result['checks']},indent=2))
