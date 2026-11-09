"""Root-authorized two immutable Tobs producers while other targets remain active."""
import importlib.util,json
from pathlib import Path
from analysis.arrival.evidence import sha256
from scripts import run_arrival_development_journal as J
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
expected={'dev-tobs-pooled-selected-check':'cc8c5dd49b69904c9324008b4cf0e0b1c2e613b7938561ea948593eff256bbec','dev-tobs-distance-runner-up-check':'7725c5feee50810131999f9e2002fdf4518de181d80534a2b121d39dba0e3e37'}
for jobid,h in expected.items():
 p=J.attempt_path(root,'check',{'id':jobid});assert sha256(p)==h
 r=json.loads(p.read_text());assert r['outcome']=='accepted' and r['cost']==r['start_markers']==0
s=importlib.util.spec_from_file_location('NTWC_journal_audit','/private/tmp/check-ms6-journal-NTWC.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
notice=dict(root_closed_authorization=True,closed=True,job_ids=list(expected),scope='two immutable Tobs producers only; journal active on other targets')
results={}
for jobid in expected:
 r=m.inspect_closed_job(jobid,notice=notice,all_four_closed=False)
 assert r['result_status']=='computed_pending_scientific_review' and r['controller_attempt_outcome']=='accepted'
 assert r['checks']['usable_event_scores']==r['checks']['event_slots'] and r['checks']['prediction_rows_passed']==r['checks']['prediction_rows']==22
 assert r['training_records']==236 and r['full_worker_case_artifacts'] is None
 results[jobid]=r
 print(json.dumps(dict(job=jobid,status='target_scoped_independent_science_passed',events=r['checks']['event_slots'],records=22,max_dense_error=max(e['dense']['max_abs_error'] for e in r['checks']['events']),max_logL_error=max(e['max_logL_error'] for e in r['checks']['events']),max_PIT_error=r['checks']['max_PIT_error'],max_CDF_error=r['checks']['max_quantile_CDF_error'],aggregate=r['checks']['aggregates'])),flush=True)
out=Path('/private/tmp/tsunami-development-Tobs-sealed-independent.json')
with out.open('x') as f:json.dump(dict(status='two_sealed_Tobs_science_passed_global_runtime_review_pending',jobs=results,controller_active_on_other_targets=True,Tcal_outcomes_or_posteriors_read=False,full_global_inventory_or_quota_asserted=False,final_check_accepted=False,new_sampler_calls=0),f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
print(json.dumps({'receipt':str(out),'sha256':sha256(out)},indent=2),flush=True)
