"""Prepared NTWC scientific audit adapter; no bodies read before Root CLOSED notice.

The independent mathematics is frozen helper30b. This adapter binds the new
journal allocations/attempts and reuses the original immutable scientific worker.
No new NCEI numerical replay, sampler, private state read, Gate or public write.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
import numpy as np
from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival import model_development_references as refs
from analysis.arrival.evidence import read_rows,sha256
from analysis.arrival.model_data import lane_arrays
from scripts import run_arrival_development_journal as J
BASE=Path('/private/tmp/check-tsunami-development-five.py')
BASE_SHA='30b7879011544c5431dfe378e1ffaf4a47a7dbf51fbc2266a705123eb30620fe'
ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
JOBS=('dev-tobs-pooled-selected-check','dev-tobs-distance-runner-up-check','dev-tcal-distance-selected-check','dev-tcal-pooled-runner-up-check')


def require(ok,message):
    if not ok:raise ValueError(message)


def independent_helper():
    require(sha256(BASE)==BASE_SHA,'frozen independent mathematical checker changed')
    spec=importlib.util.spec_from_file_location('frozen_five_check_math',BASE)
    require(spec is not None and spec.loader is not None,'checker source loader required')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    return helper


def inspect_closed_job(jobid,*,notice,all_four_closed=False):
    require(notice.get('root_closed_authorization') is True and notice.get('closed') is True and jobid in notice.get('job_ids',[]),'exact Root CLOSED-job notice required before source/result/native reads')
    require(jobid in JOBS,'only the four declared NTWC jobs may be audited')
    require(not all_four_closed or set(JOBS)<=set(notice['job_ids']),'all-four native/scientific scope must be explicitly closed')
    authority=J.gate_path('check');gate=json.loads((ROOT/authority).read_text());pins={**gate['files'],authority:sha256(ROOT/authority)}
    data._unchanged(ROOT,pins)
    require(pins[authority]=='b90d8a903061e27ebf54d97d444f325838f8d1275cf572954eaff2f36fb9ac20','exact accepted journal authority required')
    kernel=fit.verify_gate(ROOT,'check_evaluate');data._require(pins,kernel['files'])
    job=next(j for j in gate['jobs'] if j['id']==jobid);target,model=kernel['specs'][job['model_key']]
    require(target in {'T-OBS','T-CAL'} and job['role']=='check_evaluate' and job['training_reference']=={'kind':'historical'},'unchanged target-specific historical zero-call model')
    folder,raw=fit.case_paths(ROOT,job);require(raw is None,'evaluator cannot allocate a new raw posterior')
    allocation=J.allocation_path(ROOT,'check',job);attemptpath=J.attempt_path(ROOT,'check',job);plan=J.plan_path(ROOT,'check')
    charge=json.loads(allocation.read_text());attempt=json.loads(attemptpath.read_text());processpath=folder.with_name(folder.name+'.supervisor.json');process=json.loads(processpath.read_text())
    require(charge['job']==job and charge['job_id']==jobid and charge['cost']==0 and charge['role']=='check_evaluate','immutable literal zero-call allocation')
    require(charge['authority_gate']==authority and charge['authority_gate_sha256']==pins[authority] and charge['worker_gate']==fit.GATE and charge['worker_gate_sha256']==kernel['files'][fit.GATE],'allocation dual authority')
    require(charge['plan']==str(plan.relative_to(ROOT)) and charge['plan_sha256']==sha256(plan),'immutable phase plan binding')
    require(attempt['job_id']==jobid and attempt['phase']=='check' and attempt['role']=='check_evaluate' and attempt['cost']==attempt['start_markers']==0,'literal attempt role/cost')
    require(attempt['allocation']==str(allocation.relative_to(ROOT)) and attempt['allocation_sha256']==sha256(allocation) and attempt['receipt']==str(attemptpath.relative_to(ROOT)),'attempt/charge binding')
    require(process['reason']=='worker_exit' and process['returncode'] in [0,2] and process['cost']==process['start_markers']==0 and not process['monitor_failures'],'closed zero-call process')
    require(process['allocation']==str(allocation.relative_to(ROOT)) and process['allocation_sha256']==sha256(allocation) and process['invocation_git_sha']==charge['invocation_git_sha'],'process literal allocation/Git')
    require(process['authority_gate_sha256']==pins[authority] and process['worker_gate_sha256']==kernel['files'][fit.GATE] and process['plan_sha256']==sha256(plan),'process dual authority/plan')
    require(not list(folder.glob('sampling-start*')),'check must never manufacture sampler start')
    specpath=folder.with_name(folder.name+'-spec.json')
    require(sha256(specpath)==charge['spec_sha256']==process['job_sha256'] and json.loads(specpath.read_text())==job,'native spec identity')
    manifest=json.loads((folder/'output-checksums.json').read_text());require(set(manifest)=={'job.json','inputs.json','membership.json','result.json','event-results.json','direct-score-arrays.npz','held-out-record-predictions.csv'},'exact eight-file check worker')
    require({p.name for p in folder.iterdir()}==set(manifest)|{'output-checksums.json'},'no unknown producer file')
    files={str((folder/k).relative_to(ROOT)):v for k,v in manifest.items()}
    for path in [folder/'output-checksums.json',specpath,folder.with_name(folder.name+'.log'),processpath,allocation,attemptpath,plan]:files[str(path.relative_to(ROOT))]=sha256(path)
    data._unchanged(ROOT,{**pins,**files});data._require(files,attempt['files'])
    require(json.loads((folder/'inputs.json').read_text())==dict(files=kernel['files'],model_spec=model,specification_freeze_sha256=kernel['files'][data.FREEZE]),'complete original worker scientific admission')
    require(json.loads((folder/'job.json').read_text())==job,'literal original job')
    _,_,roles,sequences=data.verify_development_sources(ROOT,kernel['files'])
    exploration=read_rows(data._path(ROOT,data.TARGET_FILES[target]));held_rows=read_rows(data._path(ROOT,data.CHECK_FILES[target]))
    require(all(n==1 for n in Counter((r['event_id'],r['physical_site_id']) for r in held_rows).values()),'no new check ambiguity')
    source=lane_arrays(target,exploration,sequences,roles['exploration']);held=lane_arrays(target,held_rows,sequences,roles['confirmation'])
    cross={sequences[e] for e in roles['confirmation']};mask=source.included & ~np.isin(source.sequences,sorted(cross));training=replace(source,included=mask)
    require(int(mask.sum())=={'T-OBS':236,'T-CAL':156}[target] and int(held.included.sum())=={'T-OBS':22,'T-CAL':13}[target],'exact source-specific training/check cohorts')
    membership=json.loads((folder/'membership.json').read_text());require(membership['training_record_ids']==[source.record_ids[i] for i in np.flatnonzero(mask)] and membership['check_primary_ids']==[held.record_ids[i] for i in np.flatnonzero(held.included)],'native ordered membership')
    post,provenance=refs.load_frozen_training_reference(ROOT,job['model_key'],training,kernel['files'])
    replay=fit._evaluate(ROOT,folder,training,held,model,post,provenance,verify=True)
    result=json.loads((folder/'result.json').read_text());require(all(result[k]==v for k,v in replay.items()),'exact original worker semantic replay without promotion')
    checks=independent_helper().independent_math(folder,training,held,model['kind'],post)
    proof=fit.case_artifacts(ROOT,job,kernel['files']) if all_four_closed and result['status']==fit.SUCCESS else None
    if result['status']==fit.SUCCESS:require(attempt['outcome']=='accepted' and process['returncode']==0,'successful science/process disposition')
    else:require(attempt['outcome']=='needs_review' and process['returncode']==2,'retained failed science/process disposition')
    data._unchanged(ROOT,{**pins,**files,provenance['raw']:provenance['raw_sha256']})
    return dict(status='independent_closed_NTWC_scientific_QA',job=job,model_spec=model,result_status=result['status'],controller_attempt_outcome=attempt['outcome'],checks=checks,training_reference=provenance,training_records=int(mask.sum()),held_records=int(held.included.sum()),process=process,attempt=str(attemptpath.relative_to(ROOT)),attempt_sha256=sha256(attemptpath),full_worker_case_artifacts=proof,files={**pins,**files,provenance['raw']:provenance['raw_sha256']},new_sampler_calls=0,no_retuning=True,reserved_outcomes='sealed',old_NCEI_numerics_not_rerun=True,no_completed_check_acceptance_created=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--describe',action='store_true');args=parser.parse_args()
    if args.describe:print(json.dumps({'jobs':JOBS,'requires':'Root CLOSED notice before any result/target/native read','all_four_closed':'Use full immutable fit.case_artifacts in addition to independent math for each successful closed NTWC case','old_dispositions':'Only fresh byte/closure checks of C0/C1; no old NCEI numerical replay or promotion','publication':'No automatic completed-six-dispositions review'},indent=2))


if __name__=='__main__':main()
