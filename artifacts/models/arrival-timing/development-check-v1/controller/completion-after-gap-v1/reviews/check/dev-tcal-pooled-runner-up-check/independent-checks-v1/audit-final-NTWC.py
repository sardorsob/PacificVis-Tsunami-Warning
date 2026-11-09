"""Authorized all-four closed target scope; TEMP only pending runtime reconciliation."""
import importlib.util,json
from pathlib import Path
from analysis.arrival import model_development_fit as fit
from analysis.arrival.evidence import sha256
from scripts import run_arrival_development_journal as J
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
s=importlib.util.spec_from_file_location('NTWC_final','/private/tmp/check-ms6-journal-NTWC.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
notice=dict(root_closed_authorization=True,closed=True,job_ids=list(m.JOBS))
expected={'dev-tcal-distance-selected-check':'1dbbc39f9c7fb3529b9c0673109f0bb319dd4044330628e98fefc77c3035db38','dev-tcal-pooled-runner-up-check':'7b0e0174a03894a6bf4beb91970534305904d6481c3cc55ff0c59798597c26d7'}
results={}
for jobid,h in expected.items():
 assert sha256(J.attempt_path(root,'check',{'id':jobid}))==h
 r=m.inspect_closed_job(jobid,notice=notice,all_four_closed=True)
 assert r['training_records']==156 and r['checks']['prediction_rows']==r['checks']['prediction_rows_passed']==13
 results[jobid]=r
 print(json.dumps(dict(job=jobid,status=r['result_status'],events=r['checks']['event_slots'],usable_event_scores=r['checks']['usable_event_scores'],predictions_pass=13,failed=[e for e in r['checks']['events'] if not e['precision_passed']],max_dense_error=max(e['dense']['max_abs_error'] for e in r['checks']['events']),max_logL_error=max(e['max_logL_error'] for e in r['checks']['events']),max_PIT_error=r['checks']['max_PIT_error'],max_CDF_error=r['checks']['max_quantile_CDF_error'],aggregates=r['checks']['aggregates']),indent=2),flush=True)
# Reuse the already independent Tobs arithmetic and refresh exact byte/native proofs,
# never rerun old NCEI failure/resolution numerics or a QMC stream.
oldpath=Path('/private/tmp/tsunami-development-Tobs-sealed-independent.json')
assert sha256(oldpath)=='cafc57319695e36c577344f82896337f1fa10d6be2ad97989d6da28ba28dd33f'
old=json.loads(oldpath.read_text());kernel=fit.verify_gate(root,'check_evaluate');tobs_proofs={}
for jobid,r in old['jobs'].items():
 for p,h in r['files'].items():assert sha256(root/p)==h,p
 proof=fit.case_artifacts(root,r['job'],kernel['files'])
 tobs_proofs[jobid]=proof
 print(jobid+' unconditional full native/source/artifact semantic proof PASS; existing independent arithmetic reused.',flush=True)
# Exact failed endpoint details are retained as diagnostic computations, not usable scores.
f=root/fit.CHECK_OUTPUT/'jobs/dev-tcal-pooled-runner-up-check'
ev=json.loads((f/'event-results.json').read_text());failed=[e for e in ev['events'] if not e['score']['precision_passed']]
assert len(failed)==1
failure={k:v for k,v in failed[0]['score'].items() if k!='metadata'}
failure['event_id']=failed[0]['event_id'];failure['records']=len(failed[0]['record_ids'])
failure['normalized_chain_range']=float(__import__('numpy').ptp(failure['chain_joint_log_predictive'])/failure['records'])
failure['normalized_chain_range_threshold']=max(.005,6*failure['normalized_mcse'])
out=Path('/private/tmp/tsunami-development-NTWC-final-independent.json')
value=dict(status='closed_NTWC_science_complete_Tcal_runner_gap_pending_Root_disposition',Tcal=results,Tobs_independent_receipt=str(oldpath),Tobs_independent_receipt_sha256=sha256(oldpath),Tobs_full_artifact_proofs=tobs_proofs,Tcal_pooled_failure=failure,public_review_written=False,completed_check_accepted=False,runtime_marker_reconciliation_pending=True,new_sampler_calls=0,full57_or_G6_or_reserved_data_read=False,old_NCEI_numerics_not_rerun=True)
with out.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
print(json.dumps(dict(receipt=str(out),sha256=sha256(out),Tcal_pooled_failure=failure),indent=2),flush=True)
