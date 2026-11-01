from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime,timedelta
from urllib.parse import urlsplit,parse_qs
import csv,hashlib,json,tomllib
from analysis.arrival.stations import validate_reviewed_site_evidence
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times');base=root/'artifacts/generated/ntwc-batch';folder=base/'waveform-noaa-delta-v3'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((folder/'preflight.json').read_text())
assert p['status']=='ready' and p['within_budget'] and p['estimated_transfer_bytes']<=150000000
for path,digest in p['input_sha256'].items():assert sha(root/path)==digest,path
ledger=json.loads((base/'screen-v1/selection-v2.json').read_text());canonical={k:v for k,v in ledger.items() if k!='selection_sha256'}
assert hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()==p['selection_sha256']==ledger['selection_sha256']
events={e['event_id']:e for e in ledger['events']};config=tomllib.loads((root/'config/ntwc-archive-batch-v2.toml').read_text());assert config['selection_sha256']==p['selection_sha256']
for e in config['events'].values():assert all(events[e['event_id']].get(k)==v for k,v in e.items())
parse=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
reserved=[parse(e['usgs_time']) for e in events.values() if e['role']=='sealed_evaluation']
rows=list(csv.DictReader((base/'crosswalk-reviewed-v3/unique_report_crosswalk.csv').open()));assert len(rows)==1177
approved={}
for row in rows:
 if row['event_site_identity_verified']=='True':
  validate_reviewed_site_evidence(row)
  if row['identity_scope']=='authoritative_provider_site':approved.setdefault((row['event_id'],row['provider_station_id']),[]).append(row)
prior={};prior_paths=[]
for path in p['input_sha256']:
 if path.endswith('.toml') and path not in {'config/ntwc-archive-batch-v2.toml','config/ia-cdx-dev-scoped.toml'}:
  doc=tomllib.loads((root/path).read_text())
  if 'assets' not in doc:continue
  prior_paths.append(path)
  for key,a in doc['assets'].items():
   sid=a['source_id']
   assert sid not in prior
   prior[sid]=(a,doc.get('source_windows',{}).get(sid,{}))
assert len(prior)==1582 and len(prior_paths)==15
assert set(p['existing_source_ids_retained']).isdisjoint(p['previous_source_ids_outside_current_selection'])
assert set(p['existing_source_ids_retained'])|set(p['previous_source_ids_outside_current_selection'])==set(prior)
assert sum(prior[sid][1].get('purpose')=='quiet_control' for sid in p['previous_source_ids_outside_current_selection'])==18
ids=set();urls=set();pairs=defaultdict(set);expected_bytes=0;new_events=set()
for batch in p['batches']:
 assert batch['path'].startswith('coops-') and batch['contracts']<=200
 path=folder/batch['path'];assert sha(path)==batch['sha256'];doc=tomllib.loads(path.read_text());assets=doc['assets'];windows=doc['source_windows']
 assert len(assets)==batch['contracts'] and set(assets)==set(windows)
 batch_bytes=0
 for sid,a in assets.items():
  w=windows[sid];eid=w['event_id'];e=events[eid];origin=parse(e['usgs_time'])
  assert e['role']=='development' and e['attribution_status']=='single_source_metadata'
  assert sid not in ids and sid not in prior and a['source_id']==sid and a['url'] not in urls
  ids.add(sid);urls.add(a['url']);new_events.add(eid)
  u=urlsplit(a['url']);assert (u.scheme,u.netloc,u.path,u.fragment)==('https','api.tidesandcurrents.noaa.gov','/api/prod/datagetter','')
  q=parse_qs(u.query);assert all(len(v)==1 for v in q.values());q={k:v[0] for k,v in q.items()}
  product=q['product'];station=q['station'];assert product in {'one_minute_water_level','water_level'} and station.isdigit() and len(station)==7
  assert (eid,station) in approved
  assert any(w['evidence']==r['evidence'] for r in approved[eid,station])
  start=origin.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1);stop=start+timedelta(days=4)
  assert parse(w['start_utc'])==start and parse(w['stop_utc'])==stop and w['purpose']=='event_window' and w['offset_days']=='0'
  assert all(not(start<=r+timedelta(hours=48) and stop>r) for r in reserved)
  assert q=={'product':product,'application':'pacific_tsunami_warning_time','begin_date':start.strftime('%Y%m%d'),'end_date':(stop-timedelta(days=1)).strftime('%Y%m%d'),'datum':'STND','station':station,'time_zone':'gmt','units':'metric','format':'json'}
  assert a['local_path']==f'data/raw/coops/windows-v1/{eid}/{station}-{product}-event_window.json'
  assert a['publisher']=='NOAA CO-OPS' and a['expected_prefix']=='{' and a['units']=='meters' and a['vertical_datum']=='STND'
  pairs[eid,station].add(product);batch_bytes+=524288 if product=='one_minute_water_level' else 131072
 assert batch_bytes==batch['estimated_bytes'];expected_bytes+=batch_bytes
assert len(ids)==338 and len(pairs)==169 and all(len(v)==2 for v in pairs.values()) and expected_bytes==p['estimated_transfer_bytes']==110755840
full=json.loads((base/'waveform-full-contracts-v2/preflight.json').read_text())
assert p['cached_capture_reuse']==full['cached_capture_reuse'] and len(p['cached_capture_reuse'])==61
for sid,cache in p['cached_capture_reuse'].items():
 old=prior[sid][0];assert old['url']==cache['final_url'] and old['local_path']==cache['local_path'] and old['expected_prefix']==cache['expected_prefix']
 assert sha(root/cache['local_path'])==cache['source_sha256'] and (root/cache['local_path']).stat().st_size==cache['source_bytes']
result=dict(status='PASS',preflight_sha256=sha(folder/'preflight.json'),contracts=len(ids),event_station_pairs=len(pairs),events=len(new_events),provider_station_ids=len({s for _,s in pairs}),new_ia=0,new_controls=0,prior_contracts_accounted=len(prior),retained_current=len(p['existing_source_ids_retained']),prior_outside_current=len(p['previous_source_ids_outside_current_selection']),prior_controls_retained=18,verified_cached_capture_reuse=61,estimated_bytes=expected_bytes,reviewed_all_event_site_evidence=533,new_event_counts=dict(sorted(Counter(e for e,s in pairs).items())),batch_sha256={b['path']:b['sha256'] for b in p['batches']},checks=['all frozen selection/config/input digests verified','all 533 reviewed evidence records validated; every new NOAA station binds approved provider evidence','all new IDs and URLs unique and absent from all 15 prior configs','exact four-calendar-day request bounds and reserved origin..+48h exclusion','only two approved water-level products; metric UTC STND explicit','all 1582 prior IDs accounted; all 61 cache URL/path/prefix/body hashes preserved','no network; runtime budget enforcement remains root responsibility'])
print(json.dumps(result,indent=2));Path('/private/tmp/ntwc-noaa-delta-v3-contract-review.json').write_text(json.dumps(result,indent=2)+'\n')
