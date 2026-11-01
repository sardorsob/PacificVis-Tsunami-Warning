"""Independent conservation check of the complete v5 waveform build."""
from pathlib import Path
from datetime import UTC, datetime
from collections import Counter
import csv, gzip, hashlib, json, math
root=Path.cwd()
base=root/'data/processed/arrival-waveforms/foundation-v4'
current=root/'data/processed/arrival-waveforms/foundation-v5'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
a=json.loads((base/'manifest.json').read_text());b=json.loads((current/'manifest.json').read_text())
old={s['source_id']:s for s in a['sources']};new={s['source_id']:s for s in b['sources']}
assert len(old)==len(new)==1902 and set(old)==set(new)
for rel,digest in b['input_sha256'].items():assert sha(root/rel)==digest,(rel,'input hash')
rows=0;additions=[]
for sid,s in new.items():
 if s.get('source_sha256') not in (None,'unknown'):
  assert sha(root/s['raw_path'])==s['source_sha256'],(sid,'raw hash')
 if old[sid]['processing_status']=='normalized_source_samples':
  assert old[sid]==s,(sid,'baseline metadata')
 if s['processing_status']!='normalized_source_samples':continue
 path=current/s['output_path'];assert sha(path)==s['output_sha256'],(sid,'output hash')
 rows+=s['source_rows']
 if old[sid]['processing_status']=='normalized_source_samples':
  assert sha(base/s['output_path'])==sha(path),(sid,'baseline native rows')
  continue
 raw=(root/s['raw_path']).read_text().splitlines();native=raw[4:]
 with gzip.open(path,'rt',newline='') as f:records=list(csv.DictReader(f))
 assert len(records)==len(native)==s['source_rows']
 for r,line in zip(records,native,strict=True):
  epoch,value,calendar=line.split();clock=datetime.fromtimestamp(int(epoch),UTC)
  assert clock.strftime('%Y%m%d%H%M%S')==calendar
  assert r['timestamp_utc']==clock.isoformat().replace('+00:00','Z')
  assert r['raw_value']==value and float(r['numeric_value'])==float(value)
  assert math.isfinite(float(value))
  assert json.loads(r['raw_row_json'])['line']==line
 assert s['declared_cadence_seconds']=='unknown'
 assert s['units']==raw[1].split()[1]
 assert s['source_processing_level']=='source_reported_unfiltered'
 additions.append({'source_id':sid,'rows':len(records),'family':s['source_metadata']['format_rule_id'],'duplicates':s['duplicate_timestamp_excess']})
assert rows==b['source_rows']==3756344
assert len(additions)==15 and sum(s['rows'] for s in additions)==68204
blank=sum(s.get('value_states',{}).get('blank',0) for s in new.values())
qc=sum(s.get('qc_states',{}).get('not_provided',0) for s in new.values())
receipt={'status':'PASS','baseline_manifest_sha256':sha(base/'manifest.json'),'current_manifest_sha256':sha(current/'manifest.json'),'source_entries':1902,'normalized_sources':1783,'source_rows':rows,'baseline_sources_unchanged':1768,'baseline_rows_unchanged':3688140,'additional_sources':additions,'blank_value_rows':blank,'blank_value_fraction':blank/rows,'qc_not_provided_rows':qc,'qc_not_provided_fraction':qc/rows,'processing_status_counts':dict(Counter(s['processing_status'] for s in new.values())),'claims':'All source/output hashes verified, all old normalized native bytes and metadata unchanged; every new native sample independently read back to raw epoch/calendar/value; no interpolation or onset labels.'}
(root/'artifacts/generated/ntwc-batch/recovery-execution-v1/waveform-v5-check.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('additional_sources','claims')},indent=2))
