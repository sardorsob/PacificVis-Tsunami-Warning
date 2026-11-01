"""Check raw NCEI gauge pages and identify exact pagination follow-ups."""
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from collections import Counter
import csv,hashlib,json,sys
root=Path.cwd();run=root/sys.argv[1];out=root/sys.argv[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
match_path=root/'artifacts/generated/ntwc-batch/recovery-evidence-review-v1/event-matches.csv';matches={int(m['ncei_event_id']):m for m in csv.DictReader(match_path.open())}
ins={x['source_id']:x for x in json.loads((run/'inputs.json').read_text())};outcomes=json.loads((run/'outputs.json').read_text());rows=[]
for o in outcomes:
 assert o['status'] in ('downloaded','cached'),o
 c=ins[o['source_id']];url=c['url'];q=parse_qs(urlparse(url).query);nid=int(q['tsunamiEventId'][0]);assert nid in matches
 assert set(q['typeMeasurementId'])=={'2','3'} and q['itemsPerPage']==['200']
 p=root/o['local_path'];raw=p.read_bytes();assert len(raw)==o['bytes'] and sha(p)==o['sha256'];assert p.with_name(p.name+'.sha256').read_text().strip()==sha(p);assert o['final_url']==url
 d=json.loads(raw);assert 'error' not in d and isinstance(d['items'],list);assert d['page']==int(q['page'][0]);assert d['itemsPerPage']==200
 assert len(d['items'])==max(0,min(200,d['totalItems']-200*(d['page']-1)))
 for r in d['items']:assert r['tsunamiEventId']==nid and r['typeMeasurementId'] in (2,3)
 ids=[r['id'] for r in d['items']];duplicates=[k for k,v in Counter(ids).items() if v>1]
 rows.append({'source_id':o['source_id'],'development_event_id':matches[nid]['development_event_id'],'ncei_event_id':nid,'source_url':url,'records':len(ids),'total_items':d['totalItems'],'total_pages':d['totalPages'],'page':d['page'],'additional_pages_required':list(range(d['page']+1,d['totalPages']+1)),'duplicate_record_ids':duplicates,'complete_duration_components':sum(all(k in r for k in ('travHours','travMins')) for r in d['items']),'source_sha256':o['sha256']})
receipt={'status':'PASS_RAW_INTEGRITY_paginated_events_require_followup','contracts':len(outcomes),'bytes':sum(o['bytes'] for o in outcomes),'records':sum(r['records'] for r in rows),'extra_pages':sum(len(r['additional_pages_required']) for r in rows),'reserved_requests':0,'rows':rows,'event_match_sha256':sha(match_path),'script_sha256':sha(Path(__file__))}
assert not out.exists();out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print({k:v for k,v in receipt.items() if k!='rows'})
