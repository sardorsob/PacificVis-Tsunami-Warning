"""Quick, source-grain integrity and missingness profile of accepted recovery products."""
from collections import Counter,defaultdict
from pathlib import Path
import csv,gzip,hashlib,json
root=Path.cwd();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
corpus=root/'data/processed/arrival-corpus/foundation-v5';wave=root/'data/processed/arrival-waveforms/foundation-v5/manifest.json';ncei=root/'data/processed/ncei-arrivals/foundation-v1'
c=json.loads((corpus/'summary.json').read_text());w=json.loads(wave.read_text());n=json.loads((ncei/'summary.json').read_text());counts=defaultdict(Counter);reasons=defaultdict(Counter)
for p in corpus.rglob('reported_time_value.csv.gz'):
 with gzip.open(p,'rt') as f:
  for r in csv.DictReader(f):counts[r['field_role']][r['state']]+=1
for p in corpus.rglob('target_eligibility.csv.gz'):
 with gzip.open(p,'rt') as f:
  for r in csv.DictReader(f):
   assert r['model_eligible']=='False'
   reasons[r['target_id']].update(json.loads(r['reason_codes']))
assert all(sum(v.values())==1177 for v in counts.values())
normal=[s for s in w['sources'] if s['processing_status']=='normalized_source_samples'];value=Counter();qc=Counter();groups={}
for s in normal:
 value.update(s['value_states']);qc.update(s['qc_states'])
for field in ('provider','units','vertical_datum','declared_cadence_seconds'):
 groups[field]={'source_files':dict(Counter(str(s[field]) for s in normal)),'source_rows':dict(sum((Counter({str(s[field]):s['source_rows']}) for s in normal),Counter()))}
assert sum(value.values())==3756344
out={'input_sha256':{str(p.relative_to(root)):sha(p) for p in [corpus/'summary.json',wave,ncei/'summary.json']},'ntwc':{'source_reports':1177,'resolved_pairs':388,'unresolved_pairs':789,'unresolved_pair_fraction':789/1177,'time_states_by_field':{k:dict(v) for k,v in counts.items()},'target_eligible':c['target_eligible'],'target_rejection_reasons_nonexclusive':{k:dict(v) for k,v in reasons.items()}},'waveforms':{'source_rows':w['source_rows'],'normalized_files':len(normal),'value_states':dict(value),'qc_states':dict(qc),'blank_fraction_of_retained_rows':value['blank']/w['source_rows'],'homogeneity':groups},'ncei':{'source_records':n['source_records'],'explicit_positive_durations':n['reported_duration_candidates'],'unusable_duration_fraction':(n['source_records']-n['reported_duration_candidates'])/n['source_records'],'travel_states':n['travel_states'],'arrival_component_states':n['arrival_component_states'],'all_absolute_arrival_utc_unknown':True},'interpretation':['Do not combine source-row denominators or treat source copies as independent measurements.','No imputation, invented calendar dates, origin substitution or homogeneous cadence/units/datum assumption.','MCAR is not established; MAR versus MNAR is not identifiable from these observed data alone.','Native source QC absent is distinct from a failed quality test; missing observations outside received windows have separate denominators.']}
p=root/'artifacts/generated/ntwc-batch/recovery-execution-v1/quality-summary.json';assert not p.exists();p.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({k:v for k,v in out['ntwc'].items() if k!='target_rejection_reasons_nonexclusive'},indent=2));print('NCEI',out['ncei']);print('waveforms',value,qc)
