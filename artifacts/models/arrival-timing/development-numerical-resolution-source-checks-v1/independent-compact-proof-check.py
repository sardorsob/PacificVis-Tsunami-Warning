"""Narrow independent anchor regressions; synthetic tiny streams only."""
import importlib.util,json,tempfile
from pathlib import Path
import pytest
from analysis.arrival import model_development_score_resolution as r
s=importlib.util.spec_from_file_location('resolver_tests','tests/test_arrival_model_development_score_resolution.py');t=importlib.util.module_from_spec(s);s.loader.exec_module(t)
results=[]
for damage in ['valid_no_replay','aggregate_score','aggregate_mcse','proposal','probes','omitted_source','cycle']:
 with tempfile.TemporaryDirectory(prefix='resolver-anchors-') as temp:
  with pytest.MonkeyPatch.context() as mp:
   root,adm,cfg=t.tiny_bundle.__wrapped__(Path(temp).resolve(),mp)
   r.run_resolution(root,root/r.CASE_OUTPUT);out=root/r.CASE_OUTPUT
   candidate=r.candidate_artifacts(root,adm['files']);cold=r.replay_resolution(root)
   cold_review,science=t.write_test_anchors(root,adm,candidate,cold)
   accepted=r.case_artifacts(root,adm['files'])
   def write(name,value): (out/name).write_bytes(r.encoded(value))
   if damage.startswith('aggregate'):
    a=json.loads((out/'aggregate-diagnostics.json').read_text());a['primary']['equal_event_score' if damage=='aggregate_score' else 'mcse_triangle_bound']=99. if damage=='aggregate_score' else 0.;write('aggregate-diagnostics.json',a)
    res=json.loads((out/'result.json').read_text());res['aggregates']=a;write('result.json',res);t.reseal_candidate(out)
   elif damage=='proposal':
    a=json.loads((out/'proposal.json').read_text());a['mean']=[999.]*4;write('proposal.json',a);t.reseal_candidate(out)
   elif damage=='probes':
    p=next((out/'blocks').glob('*.json'));a=json.loads(p.read_text());a['probes'][0]['training_logweight']=999.;write(str(p.relative_to(out)),a);t.reseal_candidate(out)
   elif damage=='omitted_source':
    del cold_review['files'][r.SELF];(root/r.COLD_REVIEW).write_bytes(r.encoded(cold_review));science['files'][r.COLD_REVIEW]=r.sha256(root/r.COLD_REVIEW);(root/r.REVIEW).write_bytes(r.encoded(science))
   elif damage=='cycle':
    cold_review['files'][r.REVIEW]=r.sha256(root/r.REVIEW);(root/r.COLD_REVIEW).write_bytes(r.encoded(cold_review));science['files'][r.COLD_REVIEW]=r.sha256(root/r.COLD_REVIEW);(root/r.REVIEW).write_bytes(r.encoded(science))
   mp.setattr(r,'integrate',lambda *a:(_ for _ in ()).throw(AssertionError('compact reuse unexpectedly reintegrated')))
   try:
    p=r.case_artifacts(root,adm['files'],accepted if damage=='valid_no_replay' else None)
    ok=damage=='valid_no_replay' and p['semantics_verified'] and p==accepted
    results.append({'check':damage,'passed':ok,'trusted':True})
   except ValueError as e:results.append({'check':damage,'passed':damage!='valid_no_replay','trusted':False,'error':str(e)})
print(json.dumps(results,indent=2));assert all(v['passed'] for v in results)
