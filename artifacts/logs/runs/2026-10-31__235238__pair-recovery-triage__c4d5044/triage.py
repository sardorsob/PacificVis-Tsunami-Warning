"""Read-only recovery triage. No dates inferred, labels promoted or frozen inputs modified."""
from pathlib import Path
from collections import Counter
from datetime import datetime,UTC
import csv,gzip,hashlib,json,os,re,shutil,subprocess
from pipeline.ntwc_archive import arrival_value_flags
root=Path.cwd();corpus=root/'data/processed/arrival-corpus/foundation-v4'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
reports=[]
for p in sorted(corpus.glob('*/arrival_report.csv.gz')):
 with gzip.open(p,'rt',newline='') as f:reports.extend(csv.DictReader(f))
with (root/'artifacts/generated/ntwc-batch/crosswalk-reviewed-v3/unique_report_crosswalk.csv').open(newline='') as f:cross={r['report_id']:r for r in csv.DictReader(f)}
missing={'blank','source_missing_token'};date={'date_ambiguous','calendar_context_missing','day_semantics_unverified'};good={'exact_reported_timestamp'}
triage=[]
for r in reports:
 states={r['estimate_state'],r['observed_state']};legacy=r['header_family']=='arrival_eta_utc'
 raw_est=r['legacy_eta_raw'] if legacy else r['estimated_raw'];raw_obs=r['legacy_arrival_raw'] if legacy else r['observed_raw']
 flags=arrival_value_flags({'estimated_arrival':raw_est,'observed_arrival':raw_obs})
 no_eta=bool(re.fullmatch(r'no\s+eta',' '.join(raw_est.split()),re.I))
 if r['structural_status']!='accepted_source_row':category='structural_review'
 elif legacy:category='legacy_semantics_both_candidate_entries' if flags['estimate_value'] and flags['observed_value'] else 'at_least_one_source_time_absent'
 elif r['disposition']=='exact_reported_pair':category='currently_resolved_pair'
 elif states&missing or no_eta:category='at_least_one_source_time_absent'
 elif states<=date|good:category='both_clocks_date_context_only'
 elif 'qualified_value' in states:category='modern_qualified_time_review'
 else:category='modern_format_or_footnote_review'
 triage.append(dict(report_id=r['report_id'],event_id=r['event_id'],category=category,header_family=r['header_family'],estimate_raw=raw_est,observed_raw=raw_obs,estimate_state=r['estimate_state'],observed_state=r['observed_state'],explicit_no_eta=no_eta,event_site_identity_verified=cross[r['report_id']]['event_site_identity_verified'],source_id=r['source_id'],source_sha256=r['source_sha256']))
counts=dict(Counter(r['category'] for r in triage))
assert counts=={'currently_resolved_pair':314,'at_least_one_source_time_absent':513,'structural_review':35,'both_clocks_date_context_only':230,'modern_format_or_footnote_review':18,'modern_qualified_time_review':5,'legacy_semantics_both_candidate_entries':62},counts
assert len(triage)==len({r['report_id'] for r in triage})==1177
candidates=[r for r in triage if r['category']=='both_clocks_date_context_only'];resolved=[r for r in triage if r['category']=='currently_resolved_pair']
assert sum(r['explicit_no_eta'] for r in triage)==5
summary={'status':'descriptive_triage_complete_no_labels_promoted','counts_exclusive':counts,'total_reports':1177,'date_candidates_reviewed_geographic_identity':sum(r['event_site_identity_verified']=='True' for r in candidates),'date_candidates_events':len({r['event_id'] for r in candidates}),'current_resolved_pair_events':len({r['event_id'] for r in resolved}),'current_plus_all_date_candidates_rows_upper_bound':544,'current_plus_all_date_candidates_events_upper_bound':len({r['event_id'] for r in resolved+candidates}),'explicit_no_eta_cells_previously_unknown_format':5,'source_absence_breakdown':{'modern_existing_blank_or_missing_token':427,'modern_explicit_no_eta':5,'legacy_at_least_one_time_absent':81},'original_863_unresolved_breakdown':{'source_time_absent':513,'date_context_only':230,'modern_format_or_footnote':18,'modern_qualified_time':5,'legacy_both_entries_semantics':62,'structural_review':35},'limitations':['Recovery candidates are not additional accepted pairs.','Clock-only dates require independently supported conventions; do not infer observed date by closest ETA or model agreement.','Legacy headers and footnotes/approximation signs need source-specific semantic review.','Original source-present-cell count634is a syntactic inventory and includes five No ETA strings; it is not634validated numeric pairs.','Geographic identity does not establish instrument/deployment continuity or physical onset.','A residual calibration target requires compatible predicted and observed evidence; Bayesian imputation is not independent validation.'],'recommended_order':['Source-specific date and inline-date adapters with provenance and adversarial date-rollover tests; prioritize230date-context rows and18format/footnote rows.','Review62legacy candidate pairs and5qualified modern pairs, keeping uncertainty and footnotes explicit.','For513source-absent rows, target compatible independent station/event reports or waveform annotation; preserve model product/version and published-vs-derived target distinction.','Recompute accepted event/station graph and holdout support, then design simulations before fitting hierarchy.'],'verified_external_sources':[{'url':'https://www.tsunami.gov/previous.events/01-13-07/01-13-07.html','relevance':'Official table distinguishes Observed vs Computed UTC arrival; Iquique row has explicit inline1/14dates0007/0048, demonstrating one recoverable format case.'},{'url':'https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis/global-historical-data','relevance':'Official alternative source inventory; observations must be matched by event, site, definition, references, instrument and chronology rather than merged as interchangeable labels.'}]}
sha_git=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();now=datetime.now(UTC);run=root/'artifacts/logs/runs'/(now.strftime('%Y-%m-%d__%H%M%S')+'__pair-recovery-triage__'+sha_git[:7]);run.mkdir();shutil.copyfile(__file__,run/'triage.py')
(run/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
with (run/'reports.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(triage[0]));w.writeheader();w.writerows(triage)
inputpaths=['data/processed/arrival-corpus/foundation-v4/summary.json','artifacts/generated/ntwc-batch/crosswalk-reviewed-v3/unique_report_crosswalk.csv','pipeline/arrival_corpus.py','pipeline/ntwc_archive.py']
(run/'inputs.json').write_text(json.dumps({p:sha(root/p) for p in inputpaths},indent=2)+'\n')
meta={'run_id':run.name,'git_sha':sha_git,'timestamp_utc':now.isoformat(),'lane':'paper-label-recovery-triage','decision':'prioritize_source_semantics_before_more_bulk_downloads','command':'PYTHONPATH=. .venv/bin/python triage.py from project root','no_label_promotion':True}
(run/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
os.environ.setdefault('MLFLOW_ALLOW_FILE_STORE','true');os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT','true')
import mlflow
mlflow.set_tracking_uri((root/'.mlflow/mlruns').as_uri());mlflow.set_experiment('ntwc-arrival-foundation')
with mlflow.start_run(run_name=run.name,tags={'git_sha':sha_git,'lane':'paper-label-recovery-triage','portable_run_bundle':str(run.relative_to(root)),'decision':meta['decision']}) as experiment:
 meta['mlflow_run_id']=experiment.info.run_id;(run/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
 mlflow.log_params({'corpus_version':'foundation-v4','no_label_promotion':True,'imputation_performed':False})
 mlflow.log_metrics({**counts,'reports':1177,'explicit_no_eta':5,'date_candidates_reviewed_geographic_identity':150});mlflow.log_artifacts(str(run))
print(json.dumps({'bundle':str(run.relative_to(root)),'mlflow_run_id':meta['mlflow_run_id'],'summary':summary},indent=2))
