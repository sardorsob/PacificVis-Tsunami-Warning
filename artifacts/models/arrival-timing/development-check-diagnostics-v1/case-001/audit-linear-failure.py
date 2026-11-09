"""Authorized closed NCEI linear job only; no other target or acceptance."""
import importlib.util,json,re
from pathlib import Path
from analysis.arrival.evidence import sha256
from scripts import run_arrival_development_completion as c
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times');jobid='dev-ncei-distance-scale-runner-up-check'
folder=root/c.old.fit.CHECK_OUTPUT/'jobs'/jobid
attempt=c.attempt_path(root,'check',{'id':jobid})
assert sha256(attempt)=='52d6ee797f47ca2f3dd51125446a715ee26e650369151045730ae1102666c291'
p=json.loads(folder.with_name(folder.name+'.supervisor.json').read_text())
assert p['returncode']==2 and p['reason']=='worker_exit' and p['cost']==p['start_markers']==0 and not p['monitor_failures']
assert p['invocation_git_sha']=='bb56e79e0a2d7db8d598e2b9da9936483772dcab'
assert p['worker_gate_sha256']==sha256(root/c.old.fit.GATE)
assert p['authority_gate_sha256']==sha256(root/c.gate_path('check'))
assert p['job_sha256']==sha256(folder.with_name(folder.name+'-spec.json'))
assert p['plan_sha256']==sha256(c.plan_path(root,'check'))
a=json.loads(attempt.read_text());assert a['outcome']=='needs_review' and a['cost']==a['start_markers']==0
s=importlib.util.spec_from_file_location('fivecheck','/private/tmp/check-tsunami-development-five.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=m.inspect_closed_job(jobid)
r['status']='independently_audited_closed_NCEI_linear_failure_not_accepted'
r['supervisor']=p;r['original_attempt_receipt']=str(attempt.relative_to(root));r['original_attempt_receipt_sha256']=sha256(attempt)
r['other_targets_or_models_or_raws_read']=False;r['accepted_check']=False;r['model_rejected']=False
out=Path('/private/tmp/tsunami-development-linear-failure-independent.json')
with out.open('x') as f:json.dump(r,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
print(json.dumps({'receipt':str(out),'sha256':sha256(out),'result_status':r['result_status'],'training_records':r['training_records'],'held_records':r['held_records'],'training_reference':r['training_reference'],'event_slots':r['checks']['event_slots'],'usable_event_scores':r['checks']['usable_event_scores'],'failed_events':[e for e in r['checks']['events'] if not e['precision_passed']],'prediction_rows':r['checks']['prediction_rows'],'prediction_rows_passed':r['checks']['prediction_rows_passed'],'max_dense_error':max(e['dense']['max_abs_error'] for e in r['checks']['events']),'max_logL_error':max(e['max_logL_error'] for e in r['checks']['events']),'max_PIT_error':r['checks']['max_PIT_error'],'max_quantile_CDF_error':r['checks']['max_quantile_CDF_error'],'aggregates':r['checks']['aggregates']},indent=2))
