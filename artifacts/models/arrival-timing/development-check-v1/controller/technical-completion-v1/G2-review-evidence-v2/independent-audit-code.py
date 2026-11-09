"""Authorized retained pooled G2 diagnosis; no full verifier rerun or sampling."""
import hashlib,importlib.util,json
from pathlib import Path
import numpy as np
import xarray as xr

ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
OUT=Path('/private/tmp/ms6-G2-closed-scientific-diagnostic')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
proofpath=Path('/private/tmp/tsunami-G2-closed-WORKER-diagnostic-process-proof.json')
assert sha(proofpath)=='180df32f94dd48dd201f5846b9e702c26147143b05c518cb3697e9d3df2f0e83'
proof=json.loads(proofpath.read_text());job=proof['job']
assert proof['closed'] and proof['diagnostic_scope_only'] and not proof['scientific_acceptance']
assert job['id']=='full-smoke-1-a' and proof['cost']==proof['start_markers']==1
assert proof['strict_verifier']['returncode']==1 and not proof['strict_verifier']['proof_json_present']
assert not OUT.exists()
helper=Path('/private/tmp/check-ms6-recovery-science.py')
assert sha(helper)=='7bda5269951809400825c8262ea0bb7434127c85d7a322295719f0dcfcd54713'
s=importlib.util.spec_from_file_location('frozen_G_science',helper);assert s and s.loader
q=importlib.util.module_from_spec(s);s.loader.exec_module(q)
from analysis.arrival import model_development_recovery as G
from analysis.arrival.evidence import read_rows
from analysis.arrival.model_sensitivity_priors import build_sensitivity_model
a=G.verify_gate(ROOT);assert job==a['gate']['jobs'][2]
G.data._unchanged(ROOT,proof['files'])
folder,raw=G.case_paths(ROOT,job)
assert sha(raw)=='0d9fcebefeb65471f9ce44e3f1d7b80479fde59711e85ed566af40a189ed9146'
assert not (folder.parent.parent/'strict-proofs'/job['id']/'proof.json').exists()
target,spec=a['specs'][job['model_key']]
views=G.data.load_full_development_lanes(ROOT,a['files']);design=views['combined'][target]
fake,generation=q.generation_checks(design,spec['kind'],job['truth'],job['simulator_seed'])
ids=np.flatnonzero(fake.included)
post=G.fit._read_population(ROOT,raw,fake,ids,spec['kind'])
with xr.open_dataset(raw,group='observed_data',engine='h5netcdf') as observed:
    assert observed.identical(G.fit._observed(fake,ids,'full_design_recovery'))
result=json.loads((folder/'result.json').read_text())
G.fit._replay_fit(ROOT,folder,raw,fake,ids,spec,job,result)
base,wider,settings=G.fit._priors(ROOT,target,spec)
model=build_sensitivity_model(fake,spec['kind'],base,spec['prior_variant'],wider_prior=wider,indices=ids)
saved=json.loads((folder/'numerical-oracles.json').read_text())
fresh=G.numerical_oracles(model,fake,spec['kind'],job['truth'],settings,post)
differences=[]
def compare(l,r,path=''):
    if isinstance(l,dict):
        assert set(l)==set(r),(path,set(l),set(r))
        for key in l:compare(l[key],r[key],path+'.'+key)
    elif isinstance(l,list):
        assert len(l)==len(r)
        for i,(old,new) in enumerate(zip(l,r,strict=True)):compare(old,new,path+f'[{i}]')
    elif l!=r:
        d=dict(path=path,saved=l,fresh=r)
        if type(l) in (int,float) and type(r) in (int,float):d['absolute_delta']=abs(l-r)
        differences.append(d)
compare(saved,fresh)
print(json.dumps(dict(stage='exact_oracle_field_comparison',saved_passed=saved['passed'],fresh_passed=fresh['passed'],exact_equal=saved==fresh,differences=differences)),flush=True)
density=q.density_checks(model,fake,spec['kind'],job['truth'],settings,post)
summary=G.summarize_posterior(fake,spec['kind'],post,indices=ids,seed=job['conditional_seed'],draws=800)
assert summary==json.loads((folder/'summary.json').read_text())
tables=q.summary_checks(fake,spec['kind'],post,job['conditional_seed'],summary,job['truth'],read_rows(folder/'truth-quantiles.csv'))
for name in G.TABLES:G.fit._replay_table(folder/(name.replace('_','-')+'.csv'),summary[name])
G.fit._replay_table(folder/'truth-quantiles.csv',G._truth_table(post,job['truth']))
OUT.mkdir()
with xr.open_dataset(raw,group='sample_stats',engine='h5netcdf') as stats:
    G.fit.references._native_protocol(post,stats)
    pictures=q.render_diagnostics(post,stats,job,OUT)
files=dict(a['files'])
for name,digest in proof['files'].items():
    assert name not in files or files[name]==digest
    files[name]=digest
G.data._unchanged(ROOT,files)
receipt=dict(status='independent_G2_diagnostic_original_strict_failure_retained',independent_checker=True,job=job,
    original_closed_proof=proof,original_closed_proof_sha256=sha(proofpath),
    generation=generation,density=density,seeded_tables=tables,native_diagnostics=result['diagnostics'],
    saved_oracle=saved,fresh_oracle=fresh,exact_oracle_equal=saved==fresh,oracle_field_differences=differences,
    suffix_fresh_summary_JSON_and_all6CSVs_passed=True,files=files,figures=pictures,
    original_controller_partial_failure_retained=True,proof_json_absent=True,
    normal_G_case_artifacts_called=False,original_source_predicates_unchanged=True,
    new_sampler_calls=0,scientific_acceptance=False,visual_review='PENDING_REQUIRED',
    no_coverage_or_calibration_or_physical_claim=True,audit_code_sha256=sha(Path(__file__)))
p=OUT/'scientific-diagnostic.json'
with p.open('x') as f:json.dump(receipt,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
G.data._unchanged(ROOT,files)
print(json.dumps(dict(receipt=str(p),sha256=sha(p),density=density['passed'],summary=tables['passed'],saved_passed=saved['passed'],fresh_passed=fresh['passed'],exact_equal=saved==fresh,differences=differences,visual_review='PENDING_REQUIRED')))
