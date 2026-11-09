import sys,json
from pathlib import Path
import numpy as np,pymc as pm,pytensor.tensor as pt,pytensor
from scipy import stats,linalg
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times');sys.path.insert(0,str(root))
from analysis.arrival import model_development_recovery as w
from analysis.arrival.model_sensitivity_priors import _population_spec,build_sensitivity_model,_prior_settings
from tests.test_arrival_model_development_recovery import small_lane,posterior,FORMS
results=[]
forms=[(t,k,'base') for t,k in FORMS]+[('NCEI-native-duration','mean-curvature','t4_matched'),('T-OBS','pooled','power_0.5'),('T-CAL','event','joint_wider'),('NCEI-native-duration','mean-curvature','gamma_wider_only')]
# Independent simulator reconstruction, all eight forms and both frozen truths.
for target,kind in FORMS:
 lane=small_lane(target)
 for case in ['A','B']:
  truth=w._truth(target,kind,case);fake,effects=w.simulate(lane,kind,truth,444)
  rng=np.random.default_rng(444);events=sorted(set(lane.event_ids));u={e:rng.normal()*truth.get('tau_event',0) for e in events};dist=lane.distance_km;mu=truth['alpha']+truth.get('beta',0)*np.log(dist/1000)
  if 'gamma' in truth:mu+=truth['gamma']*np.log((dist+500)/(1.5*dist))
  noise=rng.normal(size=len(dist));sd=np.interp(np.log(dist),np.log([500,2000,5000]),truth['sigma_anchor']) if 'sigma_anchor' in truth else truth['sigma'];expected=mu+np.array([u[e] for e in lane.event_ids])+sd*noise
  np.testing.assert_allclose(fake.response,expected,rtol=1e-14,atol=1e-14);assert effects==u
print('Independent generative equations PASS16 forms/truth cases',flush=True)

def manual(lane,kind,theta,family,scales):
 ids=np.flatnonzero(lane.included);dist=lane.distance_km[ids];resp=lane.response[ids];mu=theta['alpha']+theta.get('beta',0)*np.log(dist/1000)
 if 'gamma' in theta:mu+=theta['gamma']*np.log((dist+500)/(1.5*dist))
 sigma=np.interp(np.log(dist),np.log([500,2000,5000]),theta['sigma_anchor']) if 'sigma_anchor' in theta else np.full(len(dist),theta['sigma']);events=np.array(lane.event_ids)[ids];answer=0.
 for event in np.unique(events):
  ix=np.flatnonzero(events==event);resid=resp[ix]-mu[ix];cov=np.diag(sigma[ix]**2)+theta.get('tau_event',0)**2*np.ones((len(ix),len(ix)));L=np.linalg.cholesky(cov);z=linalg.solve_triangular(L,resid,lower=True);answer-=.5*(len(ix)*np.log(2*np.pi)+2*np.log(np.diag(L)).sum()+z@z)
 prior=0.
 for name,(key,shape) in _population_spec(lane.target,kind).items():
  x=np.asarray(theta[name]);prior+=float(np.sum(stats.t.logpdf(x,4,scale=scales[key]) if family=='t4' else stats.norm.logpdf(x,scale=scales[key])))
  if name in ['sigma','sigma_anchor','tau_event']:prior+=x.size*np.log(2)+np.log(x).sum()
 return answer+prior,prior

for target,kind,variant in forms:
 truth=w._truth(target,kind,'B');fake,_=w.simulate(small_lane(target),kind,truth,555);base=dict(alpha_sd=30.,beta_sd=15.,tau_sd=30.,sigma_sd=30.) if target=='T-CAL' else dict(alpha_sd=.5,beta_sd=.25,tau_sd=.4,sigma_sd=.4)
 if kind=='mean-curvature':base['gamma_sd']=.5
 wider={k:v*2 for k,v in base.items()} if variant=='joint_wider' else None
 family,scales=_prior_settings(kind,base,variant,wider);model=build_sensitivity_model(fake,kind,base,variant,wider_prior=wider,indices=np.flatnonzero(fake.included));lp=model.compile_logp();grad=model.compile_dlogp();spec=_population_spec(target,kind)
 point={model.rvs_to_values[model[n]].name:np.log(np.asarray(truth[n])) if n in ['sigma','sigma_anchor','tau_event'] else np.asarray(truth[n],float) for n in spec}
 mapping={model.rvs_to_values[model[n]].name:n for n in spec};names=[v.name for v in model.value_vars]
 def thetaof(p):return {n:np.exp(p[v]) if n in ['sigma','sigma_anchor','tau_event'] else p[v] for v,n in mapping.items()}
 numeric=[]
 for name in names:
  val=np.asarray(point[name]);
  for idx in np.ndindex(val.shape) if val.shape else [()]:
   h=1e-5;plus={k:np.array(v,copy=True) for k,v in point.items()};minus={k:np.array(v,copy=True) for k,v in point.items()};plus[name][idx]+=h;minus[name][idx]-=h
   numeric.append((manual(fake,kind,thetaof(plus),family,scales)[0]-manual(fake,kind,thetaof(minus),family,scales)[0])/(2*h))
 actualg=np.asarray(grad(point));np.testing.assert_allclose(actualg,numeric,atol=2e-5,rtol=1e-7);val,prior=manual(fake,kind,truth,family,scales);err=abs(float(lp(point))-val);assert err<=1e-6
 result=w.numerical_oracles(model,fake,kind,truth,dict(family=family,distribution_scales=scales),posterior(target,kind,truth,perturb=True));assert result['passed']
 results.append({'target':target,'kind':kind,'variant':variant,'independent_finite_difference_gradient_error':float(np.max(abs(actualg-numeric))),'uncorrected_logp_error':err})
 print(target,kind,variant,'PASS independent finite-diff gradient',results[-1]['independent_finite_difference_gradient_error'],flush=True)
 if target=='T-CAL' and kind=='event' and variant=='base':
  pred=sum(np.log(float(scales[key]))-float(np.log(np.float32(scales[key]))) for name,(key,_) in spec.items())
  assert abs(pred-result['prior_only_checks'][0]['offset'])<1e-12
  assert all(x=='float32' for x in result['selected_prior_scale_dtypes'].values());print('ACTUAL dtype cause',pytensor.config.floatX,'predicted',pred,'observed prior offsets',[x['offset'] for x in result['prior_only_checks']],flush=True)
# Counterexamples: no joint offset fit and no wrong-gradient certification.
target,kind='T-OBS','pooled';truth=w._truth(target,kind,'A');fake,_=w.simulate(small_lane(target),kind,truth,123);base=dict(alpha_sd=.5,beta_sd=.25,tau_sd=.4,sigma_sd=.4);model=build_sensitivity_model(fake,kind,base,'base',indices=np.flatnonzero(fake.included));settings=dict(family='normal',distribution_scales=base);post=posterior(target,kind,truth)
with model:pm.Potential('checker_joint_plus_0p01',pt.as_tensor_variable(.01))
assert not w.numerical_oracles(model,fake,kind,truth,settings,post)['passed']
model=build_sensitivity_model(fake,kind,base,'base',indices=np.flatnonzero(fake.included));original=model.compile_dlogp;model.compile_dlogp=lambda: lambda point: original()(point)+.01
assert not w.numerical_oracles(model,fake,kind,truth,settings,post)['passed']
print('Independent joint+.01 and gradient+.01 counterexamples REJECTED',flush=True)
Path('/private/tmp/recovery-scientific-checker-results.json').write_text(json.dumps(results,indent=2))
