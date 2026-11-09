"""Authorized one-time case0 cold QA; no sampler, STATE read or model changes."""
from pathlib import Path
import csv,hashlib,importlib.util,json,math,time
import numpy as np
import xarray as xr
from scipy import linalg,special,stats
from threadpoolctl import threadpool_limits
from analysis.arrival import model_development_score_resolution as m
from analysis.arrival.model_scoring import mean_mcse
from analysis.arrival.model_bridge import _mixing
ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
EVIDENCE=m.OUTPUT+'/independent-checks-v1'
PROC=str(Path(m.GATE).parent/'control/production-v1')
EXPECTED_RECEIPT='5a1a3d2aa39cd6e0cbf2a5a9a64601ea93f3ae252c3086c6134cc507bd8b5a59'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads((ROOT/p).read_text())
close=lambda a,b,t=2e-7:np.testing.assert_allclose(a,b,rtol=0,atol=t)
started=time.monotonic()
assert not (ROOT/EVIDENCE).exists() and not (ROOT/m.COLD_REVIEW).exists() and not (ROOT/m.REVIEW).exists()
a=m.verify_gate(ROOT);candidate=m.candidate_artifacts(ROOT,a['files'])
assert a['files'][m.GATE]=='2f34e8033c4f5eb15c81c450c12838a046bf88bd3789f57d6c4f13495dcb6ad7'
assert sha(ROOT/PROC/'receipt.json')==EXPECTED_RECEIPT
receipt=read(PROC+'/receipt.json');supervisor=read(PROC+'/supervisor.json')
assert receipt['candidate']==candidate and receipt['job']==m.job_descriptor()
assert receipt['status']=='unverified_candidate_requires_independent_cold_SCI'
assert receipt['sampler_calls_charged']==receipt['sampler_calls_started']==0
assert receipt['source_gate']==m.GATE and receipt['source_gate_sha256']==a['files'][m.GATE]
assert receipt['supervisor_sha256']==sha(ROOT/PROC/'supervisor.json')
assert receipt['numerical_result_is_not_scientifically_accepted'] is True
assert read(PROC+'/spec.json')==m.job_descriptor()
assert supervisor['job_sha256']==sha(ROOT/PROC/'spec.json')
assert supervisor['reason']=='worker_exit' and supervisor['returncode']==0
assert supervisor['sampler_calls']==supervisor['sampler_markers']==0 and supervisor['integration_markers']==1
assert supervisor['numeric_gate_sha256']==a['files'][m.GATE]
assert supervisor['original_kernel_gate_sha256']==a['files'][m.fit.GATE]
assert supervisor['specification_freeze_sha256']==a['files'][m.data.FREEZE]
assert supervisor['source_identity']==m.fingerprint(a['files'])
assert supervisor['protocol_sha256']==m.fingerprint(m.protocol())
assert supervisor['launcher_sha256']==a['gate']['launcher_sha256']=='7a999b1b80b6df0203bdd72dc7ef0e12fb57df60cf3bc39c2f5faa97b6725d01'
assert supervisor['invocation_git_sha']=='7a6c2d82900a38b1da7a0ed1524474940076f5f2'
assert not supervisor['monitor_failures'] and supervisor['elapsed_seconds']<=600
for body in [receipt,supervisor]:
 assert body['original_state_before_sha256']==body['original_state_after_sha256']==m.ORIGINAL_STATE_SHA
released=receipt['released_lease']
assert released==dict(path=str(Path(m.GATE).parent/'control/.controller.lock'),sha256='368da68085f125273857ace6941d37aa0dfce26cb2c915b53dcf6cae7bcdcdd3',disposition='released_exclusive_lease')
assert not (ROOT/released['path']).exists() and released['path'] not in a['files']
assert {p.name for p in (ROOT/PROC).iterdir()}=={'spec.json','worker.log','supervisor.json','receipt.json'}
assert all(p.is_file() and not p.is_symlink() for p in (ROOT/PROC).iterdir())
process_files={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/PROC).iterdir()}
assert not list((ROOT/m.CASE_OUTPUT).rglob('sampling-start*'))
# Create bounded, fully listed reproducibility evidence only after source/process admission.
(ROOT/EVIDENCE).mkdir()
for src,name in [(Path(__file__),'audit-actual.py'),(Path('/private/tmp/prepare-ms6-resolution-review.py'),'review-payload-helper.py'),(Path('/private/tmp/supervise-tsunami-development-score-resolution.py'),'production-launcher.py')]:
 assert name!='production-launcher.py' or sha(src)==a['gate']['launcher_sha256']
 with (ROOT/EVIDENCE/name).open('xb') as f:f.write(src.read_bytes())
print('Process/source/candidate admission PASS; beginning independent fixed-probe checks.',flush=True)
case=m.load_case(ROOT,a)
bundle=m._read_bundle(ROOT,a);values=bundle['values']
# Independent training-only empirical proposal from the original 4x2000 hyperparameters.
with xr.open_dataset(ROOT/m.RAW,group='posterior',engine='h5netcdf') as post:
 theta=np.column_stack([post.sigma_anchor.values.reshape(8000,3),post.tau_event.values.reshape(8000)])
 empirical=dict(mean=np.log(theta).mean(axis=0).tolist(),covariance=np.cov(np.log(theta),rowvar=False,ddof=1).tolist(),source='original_training_hyperparameters_only',training_posterior_sha256=m.RAW_SHA)
assert empirical==case['proposal']==values['proposal.json']
D=np.diag([.5**2,.25**2,.5**2]);x,y=case['x'],case['response'];nx,ny=case['new_x'],case['new_response']
z=(case['events'][:,None]==np.unique(case['events'])[None,:]).astype(float)
jac=-float(np.log(case['new_native']).sum());oracles=[]
probe_specs=[(5,0,0,0),(5,2,131072,4095),(9,3,258048,4095)]
with threadpool_limits(limits=2):
 for df,rep,first,offset in probe_specs:
  block=values[f'blocks/df{df}-rep{rep}-{first:06d}.json'];p=next(p for p in block['probes'] if p['offset']==offset)
  v=np.array(p['logtheta']);t=np.exp(v);sd=case['w']@t[:3];ns=case['new_w']@t[:3]
  C=np.diag(sd**2)+t[3]**2*(z@z.T)+x@D@x.T
  chol=linalg.cho_factor(C,lower=True);sol=linalg.cho_solve(chol,y)
  evidence=-.5*(len(y)*np.log(2*np.pi)+2*np.log(np.diag(chol[0])).sum()+y@sol)
  cross=x@D@nx.T;newcov=np.diag(ns**2)+t[3]**2*np.ones((20,20))+nx@D@nx.T-cross.T@linalg.cho_solve(chol,cross)
  pred=stats.multivariate_normal.logpdf(ny,mean=cross.T@sol,cov=newcov)+jac
  prior=stats.halfnorm.logpdf(t,scale=.4).sum()+v.sum()
  S=np.array(empirical['covariance'])*(df-2)/df;delta=v-np.array(empirical['mean']);q=delta@np.linalg.solve(S,delta)
  logq=special.gammaln((df+4)/2)-special.gammaln(df/2)-2*np.log(df*np.pi)-.5*np.linalg.slogdet(S)[1]-(df+4)/2*np.log1p(q/df)
  u=np.array(p['uniform']);mapped=np.array(empirical['mean'])+np.linalg.cholesky(S)@special.ndtri(u[:4])/np.sqrt(stats.chi2.ppf(u[4],df)/df)
  close(mapped,v,2e-13);close(logq,p['logq'],2e-11)
  close(evidence+prior-logq,p['training_logweight']);close(evidence+prior-logq+pred,p['numerator_logweight'])
  pe,pm,pc=m.training_conditional(x,y,case['events'],case['w'],t[None,:]);pp=m.predictive_loglik(nx,ny,case['new_native'],case['new_w'],t[None,:],pm,pc)
  close(pe[0],evidence);close(pp[0],pred)
  oracles.append(dict(df=df,replicate=rep,first=first,offset=offset,training_evidence_absolute_error=float(abs(pe[0]-evidence)),native_predictive_absolute_error=float(abs(pp[0]-pred)),logq_absolute_error=float(abs(logq-p['logq'])),transformed_training_weight_error=float(abs(evidence+prior-logq-p['training_logweight'])),native_jacobian_once=jac))
print('Independent fixed-probe Gaussian/t/proposal checks PASS; starting ONE full cold replay.',flush=True)
# THIS IS THE SOLE FULL PRODUCTION STREAM REPLAY IN THIS AUDIT.
replay_started=time.monotonic();replay=m.replay_resolution(ROOT);replay_seconds=time.monotonic()-replay_started
assert replay['passed'] and replay['blocks']==512 and replay['unique_nodes']==2097152 and replay['sampler_calls']==0 and replay['files']==candidate['files']
print('ONE full cold replay PASS; independently checking precision and aggregate arithmetic.',flush=True)
precision=values['precision.json'];metrics=[]
for df in [5,9]:
 for n in [65536,262144]:
  reps=[p for p in values['stream-summary.json']['prefixes'] if p['df']==df and p['n']==n]
  num=np.array([p['numerator']['log_integral'] for p in reps]);den=np.array([p['training']['log_integral'] for p in reps])
  joint=float(special.logsumexp(num)-special.logsumexp(den));scores=(num-den)/20
  scaled_num=np.exp(num-num.max());scaled_den=np.exp(den-den.max())
  paired=(scaled_num/scaled_num.mean()-scaled_den/scaled_den.mean())/20
  pairedse=float(stats.sem(paired));logse=float(stats.sem(scores));se=max(pairedse,logse)
  r=next(r for r in precision['results'] if r['df']==df and r['n']==n)
  close(r['joint_log_predictive'],joint,1e-12);close(r['paired_pooled_ratio_delta_mcse'],pairedse,1e-12);close(r['replicate_mcse_normalized'],se,1e-12)
  assert se<=.005 and all(p[k]['concentration']>=100 for p in reps for k in ['training','numerator'])
  metrics.append(dict(df=df,n=n,normalized_score=joint/20,paired_pooled_ratio_delta_mcse=pairedse,replicate_logratio_mcse=logse,governing_mcse=se,min_den_concentration=min(p['training']['concentration'] for p in reps),min_num_concentration=min(p['numerator']['concentration'] for p in reps)))
for field in ['refinement','cross_proposal']:
 assert all(p['discrepancy']<=.0005 and p['passed'] for p in precision[field])
assert precision['selected']['df']==5 and precision['selected']['n']==262144
aggregate_checks={}
for key,excluded,total in [('primary',None,14),('without_crossing_event',m.data.CROSS_CHECK,13)]:
 old=[e for e in case['originals'] if e['event_id'] not in {m.EVENT,excluded}]
 assert len(old)==total-1
 stream=np.zeros((4,2000))
 for e in old:stream+=e['influence']/e['records']/total
 oldse=mean_mcse(stream);mix=_mixing(stream);qse=precision['selected']['replicate_mcse_normalized']/total
 score=math.fsum(e['score']['normalized_event_score']/total for e in old)+precision['selected']['normalized_score']/total
 got=values['aggregate-diagnostics.json'][key]
 close(got['equal_event_score'],score,1e-12);close(got['original_shared_part_mcse'],oldse,1e-12);close(got['mcse_triangle_bound'],oldse+qse,1e-12)
 assert mix['passed'] and oldse+qse<=.002 and got['precision_passed']
 aggregate_checks[key]=dict(events=total,equal_event_score=score,old_shared_part_mcse=oldse,qmc_part_mcse=qse,conservative_mcse_sum=oldse+qse,functional_mixing=mix)
result=values['result.json'];prediction=m.ORIGINAL+'/held-out-record-predictions.csv'
assert result['original_predictions']==dict(path=prediction,sha256=a['files'][prediction],rows=151,unchanged=True)
with (ROOT/prediction).open() as f:predictions=list(csv.DictReader(f))
assert len(predictions)==151 and all(p['prediction_precision_passed']=='True' for p in predictions)
assert result['status']==m.SUCCESS and result['error'] is None and result['aggregates']['available'] is True
assert read(m.ORIGINAL+'/result.json')['status']=='needs_numerical_review'
assert candidate['computed_status']==m.SUCCESS
checks=dict(passed=True,scope='Only authorized NCEIcase0, original1040training/151check and81cbraw',fixed_probe_oracles=oracles,independent_precision_metrics=metrics,refinement=precision['refinement'],cross_proposal=precision['cross_proposal'],aggregate_checks=aggregate_checks,primary_supplement_contract_preserved=True,original_passing_events_retained=13,usable_event_scores_after_resolution=14,unchanged_prediction_rows=151,original_failed_result_not_relabelled=True,full_stream_replay_seconds=replay_seconds,new_sampler_calls=0,no_other_target_or_full57_or_reserved_read=True,range_diagnostic_only=True,no_QMC_independence_or_bias_certificate_claim=True)
process_proof=dict(closed=True,sampler_calls_charged=0,sampler_calls_started=0,receipt=PROC+'/receipt.json',receipt_sha256=EXPECTED_RECEIPT,supervisor=PROC+'/supervisor.json',supervisor_sha256=sha(ROOT/PROC/'supervisor.json'),released_ephemeral_files=[released],original_state_before_sha256=m.ORIGINAL_STATE_SHA,original_state_after_sha256=m.ORIGINAL_STATE_SHA,private_state_body_read=False,files=process_files)
report=dict(status='independent_actual_cold_and_math_QA_passed',checks=checks,process_proof=process_proof,source_gate=m.GATE,source_gate_sha256=a['files'][m.GATE],candidate=candidate,full_stream_replay=replay,elapsed_seconds=time.monotonic()-started)
reportpath=ROOT/EVIDENCE/'audit-receipt.json'
with reportpath.open('xb') as f:f.write(m.encoded(report))
extra={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/EVIDENCE).iterdir()}
assert len(extra)==4 and all(p.is_file() and not p.is_symlink() for p in (ROOT/EVIDENCE).iterdir())
assert sum(p.stat().st_size for p in (ROOT/EVIDENCE).iterdir())<32*1024**2
s=importlib.util.spec_from_file_location('review_helper',ROOT/EVIDENCE/'review-payload-helper.py');helper=importlib.util.module_from_spec(s);s.loader.exec_module(helper)
cold=helper.cold_review(m,a,candidate,replay,checks,process_proof,extra)
for p,h in cold['files'].items():assert sha(ROOT/p)==h,p
assert released['path'] not in cold['files']
# Publish in required acyclic order; the worker candidate and original failed files remain immutable.
m._new_json(ROOT/m.COLD_REVIEW,cold)
coldsha=sha(ROOT/m.COLD_REVIEW)
science=helper.science_review(m,a,candidate,cold,coldsha)
science['independent_checks']=checks
science['process_proof']=process_proof
for p,h in science['files'].items():assert sha(ROOT/p)==h,p
m._new_json(ROOT/m.REVIEW,science)
proof=m.case_artifacts(ROOT,a['files'])
assert proof['semantics_verified'] and proof['status']==m.SUCCESS
for p,h in proof['review_files'].items():assert sha(ROOT/p)==h,p
assert not (ROOT/released['path']).exists()
print(json.dumps(dict(status='accepted_case0_numerical_resolution',cold_review=m.COLD_REVIEW,cold_sha256=coldsha,science_review=m.REVIEW,science_sha256=sha(ROOT/m.REVIEW),audit_receipt=str(reportpath.relative_to(ROOT)),audit_sha256=sha(reportpath),full_closure_pins=len(proof['review_files']),selected_event_score=precision['selected']['normalized_score'],selected_event_mcse=precision['selected']['replicate_mcse_normalized'],precision_metrics=metrics,aggregates=aggregate_checks,refinement=precision['refinement'],cross_proposal=precision['cross_proposal'],dense_probe_errors=oracles,new_sampler_calls=0,private_state_body_read=False,original_failed_result_retained=True),indent=2),flush=True)
