"""Bounded scientific checks for Root-notified closed remaining development jobs.

No work runs on import or --help. No sampler, state access, retuning, repair,
publication or completed-check acceptance. Call inspect_closed_job only after
Root identifies that exact job as closed; all-target replay is opt-in at final5.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path
import numpy as np
from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival import model_development_references as refs
from analysis.arrival.evidence import read_rows,sha256
from analysis.arrival.model_data import lane_arrays
from scripts import run_arrival_development_completion as controller
s=importlib.util.spec_from_file_location('original_independent_case_audit','/private/tmp/audit-tsunami-development-case000.py')
original=importlib.util.module_from_spec(s);s.loader.exec_module(original)
O=original.oracle;close=original.close;require=original.require;mcse=original.mcse;mixing=original.mixing
ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
JOBS=('dev-ncei-distance-scale-runner-up-check','dev-tobs-pooled-selected-check','dev-tobs-distance-runner-up-check','dev-tcal-distance-selected-check','dev-tcal-pooled-runner-up-check')


def independent_math(folder,training,held,kind,post):
    events=json.loads((folder/'event-results.json').read_text());pred=read_rows(folder/'held-out-record-predictions.csv')
    ids_by_row={p['record_id']:p for p in pred};pop={p:post[p].values for p in post.data_vars}
    require(len(pred)==len(ids_by_row)==int(held.included.sum()),'all literal prediction records retained')
    expected=sorted(set(np.asarray(held.event_ids)[held.included]));require(events['expected_event_ids']==expected,'exact event slots')
    scores=[];sizes=[];event_checks=[];maxpit=maxcdf=maxdelta=0.;pass_predictions=0
    with np.load(folder/'direct-score-arrays.npz',allow_pickle=False) as arrays:
        require(np.array_equal(arrays['chain_coordinates'],post.chain.values) and np.array_equal(arrays['draw_coordinates'],post.draw.values),'literal posterior chain/draw ordering')
        for n,event in enumerate(events['events']):
            eventid=event['event_id'];ix=np.flatnonzero(held.included & (np.asarray(held.event_ids)==eventid))
            require(event['record_ids']==[held.record_ids[i] for i in ix],'event membership and ordering')
            native,reference,distance=held.y[ix],held.reference_minutes[ix],held.distance_km[ix]
            logl,jac=O.block_loglikelihood(native,reference,distance,pop,held.target)
            dense=O.dense_points(native,reference,distance,pop,held.target)
            llerr=close(arrays[f'event_{n:03d}_native_loglikelihood'],logl,'independent all8k Gaussian event logL')
            score=O.score_arrays(logl,len(ix));scores.append(score);sizes.append(len(ix));saved=event['score']
            close(arrays[f'event_{n:03d}_joint_influence'],score['joint_influence'],'joint influence',atol=2e-8)
            error=mcse(score['joint_influence']/len(ix));mix=mixing(score['joint_influence']/len(ix))
            for key in ['joint_log_predictive','normalized_event_score']:
                close(saved[key],score[key],key)
            close(saved['normalized_mcse'],error,'event MCSE',atol=1e-11)
            close(saved['density_weight_concentration_ess'],score['weight_concentration'],'event concentration',atol=1e-7)
            close(saved['chain_joint_log_predictive'],score['chain_joint_scores'],'per-chain normalizers')
            close(saved['metadata']['native_log_jacobian'],jac,'native Jacobian once/zero',atol=1e-12)
            failures=[]
            if not (mix['rhat']<=1.01 and mix['ess_bulk']>=400 and mix['ess_tail']>=400):failures.append('functional_mixing')
            if score['weight_concentration']<100:failures.append('density_weight_concentration')
            if error>.005:failures.append('event_mcse')
            if np.ptp(score['chain_joint_scores'])/len(ix)>max(.005,6*error):failures.append('chain_log_normalizer_disagreement')
            require(saved['numerical_failures']==failures and saved['precision_passed']==(not failures),'all event numerical screens unchanged')
            q={key:np.array([float(ids_by_row[held.record_ids[i]][key]) for i in ix]) for key in ['q05','q25','q50','q75','q95']}
            streams=O.marginal_streams(native,reference,distance,pop,held.target,q)
            lo,hi=training.distance_km[training.included].min(),training.distance_km[training.included].max()
            for j,i in enumerate(ix):
                row=ids_by_row[held.record_ids[i]]
                require(row['event_id']==eventid and row['sequence']==held.sequences[i] and row['site_id']==held.site_ids[i] and row['target']==held.target and row['kind']==kind,'native prediction identity')
                for key,value in [('observed_reported_minutes',native[j]),('modeled_response',held.response[i]),('distance_km',distance[j]),('reference_minutes',reference[j])]:close(float(row[key]),value,key,atol=1e-12)
                within=lo<=distance[j]<=hi;clamp=kind in {'distance-scale','mean-curvature'} and (distance[j]<500 or distance[j]>5000)
                require(row['within_training_distance_range']==str(within) and row['residual_scale_endpoint_clamped']==str(clamp),'support and SD endpoint clamp')
                require(row['distance_support']==('within' if within else 'below' if distance[j]<lo else 'above'),'support category')
                maxpit=max(maxpit,close(float(row['pit']),streams['pit'][j],'PIT',atol=2e-12))
                close(float(row['pit_chain_range']),streams['pit_chain_range'][j],'PIT chain range',atol=2e-12)
                pe=mcse(streams['pit_stream'][...,j]);close(float(row['pit_mcse']),pe,'PIT MCSE',atol=1e-11)
                errors=[];relative=[];width=q['q95'][j]-q['q05'][j]
                require(width>0,'finite ordered 90% interval')
                for key,prob in zip(q,[.05,.25,.5,.75,.95],strict=True):
                    cdferror=abs(float(streams[key]['cdf'][j])-prob);maxcdf=max(maxcdf,cdferror);require(cdferror<=1e-8,'saved native quantile CDF inversion')
                    se=mcse(streams[key]['cdf_stream'][...,j]);delta=se/streams[key]['native_density'][j]
                    close(float(row[key+'_cdf_mcse']),se,'quantile CDF MCSE',atol=1e-11)
                    maxdelta=max(maxdelta,close(float(row[key+'_mcse_native']),delta,'native quantile MCSE',atol=1e-8))
                    errors.append(se);relative.append(delta/width)
                pp=pe<=.005 and max(errors)<=.005 and max(relative)<=.01
                require(row['prediction_precision_passed']==str(pp),'prediction precision gates')
                require(row['coverage90_numerically_ambiguous']==str(any(abs(streams['pit'][j]-b)<=3*pe for b in [.05,.95])),'coverage ambiguity')
                pass_predictions+=pp
            event_checks.append(dict(event_id=eventid,records=len(ix),dense=dense,max_logL_error=llerr,normalized_score=score['normalized_event_score'],mcse=error,weight_concentration=score['weight_concentration'],failures=failures,precision_passed=not failures))
        aggregates={}
        for name,keep,saved in [('aggregate_shared_influence',list(range(len(scores))),events['aggregate']),('aggregate_without_crossing_shared_influence',[i for i,e in enumerate(events['events']) if e['event_id']!=data.CROSS_CHECK],events['aggregate_without_crossing_event'])]:
            if not keep:
                require(saved['status']=='not_applicable' and saved['events']==0,'empty supplementary aggregate');continue
            shared=O.shared_influence([scores[i] for i in keep],[sizes[i] for i in keep]);se=mcse(shared)
            if name in arrays:close(arrays[name],shared,'shared influences before MCSE',atol=2e-8)
            score=math.fsum(scores[i]['normalized_event_score']/len(keep) for i in keep)
            close(saved['equal_event_score'],score,'equal-event aggregate')
            close(saved['mcse_equal_event_score'],se,'shared-covariance aggregate MCSE',atol=1e-11)
            aggregates[name]=dict(events=len(keep),equal_event_score=score,mcse=se,status=saved['status'])
    return dict(events=event_checks,usable_event_scores=sum(e['precision_passed'] for e in event_checks),event_slots=len(event_checks),prediction_rows=len(pred),prediction_rows_passed=int(pass_predictions),max_PIT_error=maxpit,max_quantile_CDF_error=maxcdf,max_native_quantile_MCSE_error=maxdelta,aggregates=aggregates)


def inspect_closed_job(jobid,*,all_five_closed=False):
    """Explicit caller authorization needed; NEVER call before Root's closed notice."""
    require(jobid in JOBS,'only the five fixed remaining jobs are eligible')
    name=controller.gate_path('check');gate=json.loads((ROOT/name).read_text());pins={**gate['files'],name:sha256(ROOT/name)}
    kernel=fit.verify_gate(ROOT,'check_evaluate');data._require(pins,kernel['files']);data._unchanged(ROOT,pins)
    job=next(j for j in gate['jobs'] if j['id']==jobid);target,model=kernel['specs'][job['model_key']]
    require(job['role']=='check_evaluate' and job['training_reference']=={'kind':'historical'},'frozen zero-call historical job')
    folder,raw=fit.case_paths(ROOT,job);require(raw is None,'no new posterior')
    manifest=json.loads((folder/'output-checksums.json').read_text())
    require(set(manifest)=={'job.json','inputs.json','membership.json','result.json','event-results.json','direct-score-arrays.npz','held-out-record-predictions.csv'},'exact closed worker inventory')
    require({p.name for p in folder.iterdir()}==set(manifest)|{'output-checksums.json'},'unknown closed worker file')
    files={str((folder/k).relative_to(ROOT)):v for k,v in manifest.items()};files[str((folder/'output-checksums.json').relative_to(ROOT))]=sha256(folder/'output-checksums.json')
    for suffix in ['-spec.json','.log','.supervisor.json']:
        p=folder.with_name(folder.name+suffix);files[str(p.relative_to(ROOT))]=sha256(p)
    receipt=controller.attempt_path(ROOT,'check',job);files[str(receipt.relative_to(ROOT))]=sha256(receipt)
    data._unchanged(ROOT,{**pins,**files})
    require(json.loads((folder/'inputs.json').read_text())==dict(files=kernel['files'],model_spec=model,specification_freeze_sha256=kernel['files'][data.FREEZE]),'exact original scientific worker input closure')
    require(json.loads((folder/'job.json').read_text())==json.loads(folder.with_name(folder.name+'-spec.json').read_text())==job,'literal job/spec')
    _,_,roles,sequences=data.verify_development_sources(ROOT,kernel['files'])
    training_rows=read_rows(data._path(ROOT,data.TARGET_FILES[target]));check_rows=read_rows(data._path(ROOT,data.CHECK_FILES[target]))
    require(all(n==1 for n in Counter((r['event_id'],r['physical_site_id']) for r in check_rows).values()),'no new check event/site ambiguity')
    source=lane_arrays(target,training_rows,sequences,roles['exploration']);held=lane_arrays(target,check_rows,sequences,roles['confirmation'])
    checkseq={sequences[e] for e in roles['confirmation']};mask=source.included & ~np.isin(source.sequences,sorted(checkseq));training=replace(source,included=mask)
    require(int(mask.sum())=={'NCEI-native-duration':1040,'T-OBS':236,'T-CAL':156}[target],'frozen complete purged training cohort')
    require(int(held.included.sum())=={'NCEI-native-duration':151,'T-OBS':22,'T-CAL':13}[target],'complete native check cohort')
    membership=json.loads((folder/'membership.json').read_text());require(membership['training_record_ids']==[source.record_ids[i] for i in np.flatnonzero(mask)] and membership['check_primary_ids']==[held.record_ids[i] for i in np.flatnonzero(held.included)],'literal ordered train/check membership')
    post,provenance=refs.load_frozen_training_reference(ROOT,job['model_key'],training,kernel['files'])
    replay=fit._evaluate(ROOT,folder,training,held,model,post,provenance,verify=True)
    result=json.loads((folder/'result.json').read_text());require(all(result[k]==v for k,v in replay.items()),'exact production semantic replay including failures')
    checks=independent_math(folder,training,held,model['kind'],post)
    proof=fit.case_artifacts(ROOT,job,kernel['files']) if all_five_closed and result['status']==fit.SUCCESS else None
    data._unchanged(ROOT,{**pins,**files,provenance['raw']:provenance['raw_sha256']})
    return dict(status='independent_closed_job_scientific_QA',job=job,model_spec=model,result_status=result['status'],checks=checks,training_reference=provenance,training_records=int(mask.sum()),held_records=int(held.included.sum()),target_scoped_replay=True,all_target_case_artifacts_replay=proof,files={**pins,**files,provenance['raw']:provenance['raw_sha256']},new_sampler_calls=0,no_retuning=True,reserved_outcomes='sealed',no_completed_check_acceptance_created=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true')
    args=parser.parse_args()
    if args.describe:print(json.dumps({'fixed_jobs':JOBS,'execution':'Only import inspect_closed_job AFTER Root names exact closed jobs; no CLI data-reading mode.','first_batch':'target-scoped production replay plus independent Gaussian/CDF/MCSE; defer all-target loader.','final_batch':'all-five-closed permits full accepted case_artifacts for each successful job.','completed_check_review':'Separate canonical review only after case0 resolved plus all five independent dispositions; no automatic retune/repair/acceptance.'},indent=2))


if __name__=='__main__':main()
