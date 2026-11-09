"""Authorized G0 only: retained verifier failure plus independent frozen science."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import xarray as xr

ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
OUT=Path('/private/tmp/ms6-G0-closed-scientific-diagnostic')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pqa_path=Path('/private/tmp/tsunami-g0-closed-runtime-qa.json')
failure_path=Path('/private/tmp/tsunami-g0-original-artifact-proof-diagnosis.json')
assert sha(pqa_path)=='4ee01a8ecd2791055ddd112a5ae7487ec7b6c2a987fdf9f5978552e17354871a'
assert sha(failure_path)=='c494152746190662674381917f1d442688fd708833c7c2b1bcb7b842735c6911'
pqa=json.loads(pqa_path.read_text());failure=json.loads(failure_path.read_text())
assert pqa['job']['id']=='full-smoke-0-a' and pqa['worker_returncode']==0
assert pqa['sampler_calls_charged']==pqa['sampler_calls_started']==1
assert failure['exception']['type']=='ValueError'
assert failure['exception']['message']=='independent full-design density/gradient oracles must replay'
assert not OUT.exists()
source=Path('/private/tmp/check-ms6-recovery-science.py')
assert sha(source)=='7bda5269951809400825c8262ea0bb7434127c85d7a322295719f0dcfcd54713'
s=importlib.util.spec_from_file_location('independent_G_science',source)
assert s and s.loader
q=importlib.util.module_from_spec(s);s.loader.exec_module(q)
# Closed notice + independent runtime proof precede scientific imports and data.
from analysis.arrival import model_development_recovery as G
from analysis.arrival.evidence import read_rows
from analysis.arrival.model_sensitivity_priors import build_sensitivity_model
a=G.verify_gate(ROOT);job=a['gate']['jobs'][0]
assert job==pqa['job'] and a['files'][G.GATE]==pqa['worker_gate_sha256']
G.data._unchanged(ROOT,pqa['files'])
folder,raw=G.case_paths(ROOT,job);target,spec=a['specs'][job['model_key']]
assert sha(raw)==pqa['native_raw_sha256']
views=G.data.load_full_development_lanes(ROOT,a['files'])
design=views['combined'][target]
fake,generation=q.generation_checks(design,spec['kind'],job['truth'],job['simulator_seed'])
ids=np.flatnonzero(fake.included)
post=G.fit._read_population(ROOT,raw,fake,ids,spec['kind'])
with xr.open_dataset(raw,group='observed_data',engine='h5netcdf') as observed:
    assert observed.identical(G.fit._observed(fake,ids,'full_design_recovery'))
base,wider,settings=G.fit._priors(ROOT,target,spec)
model=build_sensitivity_model(fake,spec['kind'],base,spec['prior_variant'],wider_prior=wider,indices=ids)
density=q.density_checks(model,fake,spec['kind'],job['truth'],settings,post)
summary=json.loads((folder/'summary.json').read_text())
tables=q.summary_checks(fake,spec['kind'],post,job['conditional_seed'],summary,job['truth'],read_rows(folder/'truth-quantiles.csv'))
fresh_summary=G.summarize_posterior(fake,spec['kind'],post,indices=ids,seed=job['conditional_seed'],draws=800)
assert fresh_summary==summary
for name in G.TABLES:
    G.fit._replay_table(folder/(name.replace('_','-')+'.csv'),fresh_summary[name])
G.fit._replay_table(folder/'truth-quantiles.csv',G._truth_table(post,job['truth']))
saved=json.loads((folder/'numerical-oracles.json').read_text())
regenerated=G.numerical_oracles(model,fake,spec['kind'],job['truth'],settings,post)
differences=[]
def compare(old,new,path=''):
    if isinstance(old,dict) and isinstance(new,dict):
        assert set(old)==set(new)
        for k in old:compare(old[k],new[k],path+'.'+k)
    elif isinstance(old,list) and isinstance(new,list):
        assert len(old)==len(new)
        for i,(left,right) in enumerate(zip(old,new,strict=True)):compare(left,right,f'{path}[{i}]')
    elif old!=new:
        row=dict(path=path,saved=old,replayed=new)
        if type(old) in (int,float) and type(new) in (int,float):row['absolute_delta']=abs(old-new)
        differences.append(row)
compare(saved,regenerated)
OUT.mkdir()
with xr.open_dataset(raw,group='sample_stats',engine='h5netcdf') as stats:
    G.fit.references._native_protocol(post,stats)
    pictures=q.render_diagnostics(post,stats,job,OUT)
    native=dict(inference_library=post.attrs['inference_library'],version=post.attrs['inference_library_version'],tuning_steps=int(post.attrs['tuning_steps']),settings=json.loads(stats.attrs['inference_library_settings']))
files=dict(a['files'])
for name,h in pqa['files'].items():
    assert name not in files or files[name]==h
    files[name]=h
G.data._unchanged(ROOT,files)
receipt=dict(status='independent_G0_scientific_diagnostic_original_proof_failure_retained',independent_checker=True,job=job,generation=generation,density=density,seeded_tables=tables,native_protocol=native,diagnostics=json.loads((folder/'diagnostics.json').read_text()),original_unconditional_verifier_failure=failure['exception'],original_failure_receipt_sha256=sha(failure_path),runtime_QA_sha256=sha(pqa_path),saved_oracle_passed=saved['passed'],regenerated_oracle_passed=regenerated['passed'],exact_oracle_json_equal=(saved==regenerated),oracle_field_differences=differences,regenerated_oracles=regenerated,files=files,figures=pictures,visual_review='PENDING_REQUIRED',controller_attempt_outcome_unchanged='needs_review',worker_result_status_unchanged='computed_pending_scientific_review',technical_or_scientific_repair_authorized=False,new_sampler_calls=0,no_calibration_or_coverage_or_physical_claim=True)
with (OUT/'scientific-diagnostic.json').open('x') as stream:json.dump(receipt,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
G.data._unchanged(ROOT,files)
print(json.dumps(dict(receipt=str(OUT/'scientific-diagnostic.json'),sha256=sha(OUT/'scientific-diagnostic.json'),independent_density_passed=density['passed'],seeded_tables_passed=tables['passed'],saved_oracle_passed=saved['passed'],regenerated_oracle_passed=regenerated['passed'],exact_oracle_json_equal=(saved==regenerated),field_differences=differences,plots=pictures)))
