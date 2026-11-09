"""Synthetic re-sealed artifact checks only; no actual data or integration."""
import importlib.util, json, tempfile
from pathlib import Path
import pytest
from analysis.arrival import model_development_score_resolution as r
spec=importlib.util.spec_from_file_location('resolver_tests','tests/test_arrival_model_development_score_resolution.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
results=[]
for damage in ['aggregate_score','aggregate_mcse','proposal','probes']:
 with tempfile.TemporaryDirectory(prefix='resolver-review-') as temp:
  with pytest.MonkeyPatch.context() as mp:
   root,adm,cfg=t.tiny_bundle.__wrapped__(Path(temp).resolve(),mp)
   r.run_resolution(root,root/r.CASE_OUTPUT)
   out=root/r.CASE_OUTPUT
   def write(name,value): (out/name).write_bytes(r.encoded(value))
   if damage in ['aggregate_score','aggregate_mcse']:
    a=json.loads((out/'aggregate-diagnostics.json').read_text())
    a['primary']['equal_event_score']=99.0 if damage=='aggregate_score' else a['primary']['equal_event_score']
    a['primary']['mcse_triangle_bound']=0.0 if damage=='aggregate_mcse' else a['primary']['mcse_triangle_bound']
    write('aggregate-diagnostics.json',a)
    res=json.loads((out/'result.json').read_text());res['aggregates']=a;write('result.json',res)
   elif damage=='proposal':
    a=json.loads((out/'proposal.json').read_text());a['mean']=[999.0]*4;write('proposal.json',a)
   else:
    path=next((out/'blocks').glob('*.json'))
    a=json.loads(path.read_text());a['probes'][0]['training_logweight']=999.;write(str(path.relative_to(out)),a)
   man=json.loads((out/'output-checksums.json').read_text())
   for name in man:man[name]=r.sha256(out/name)
   write('output-checksums.json',man)
   try:
    proof=r.case_artifacts(root,adm['files'])
    results.append({'mutation':damage,'accepted_by_compact_proof':True,'status':proof['status']})
   except Exception as e:results.append({'mutation':damage,'accepted_by_compact_proof':False,'error':str(e)})
print(json.dumps(results,indent=2))
