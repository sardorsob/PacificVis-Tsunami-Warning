"""Read back acquired metadata bodies before expanding any NOAA request tranche."""
import hashlib,json,sys,tomllib
from pathlib import Path
from urllib.parse import urlparse,parse_qs
root=Path.cwd();run=root/sys.argv[1];out=root/sys.argv[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ins={x['source_id']:x for x in json.loads((run/'inputs.json').read_text())};outs=json.loads((run/'outputs.json').read_text())
events={e['event_id']:e for e in tomllib.loads((root/'config/ntwc-archive-batch-v2.toml').read_text())['events'].values()}
rows=[]
for o in outs:
 assert o['status'] in ('downloaded','cached'),o
 contract=ins[o['source_id']];url=contract['url'];meta=json.loads(contract['station_metadata'])
 for eid in meta['affected_event_ids']:assert events[eid]['role']=='development'
 path=root/o['local_path'];raw=path.read_bytes();assert len(raw)==o['bytes'] and sha(path)==o['sha256'];assert path.with_name(path.name+'.sha256').read_text().strip()==sha(path)
 assert o['final_url']==url
 d=json.loads(raw);assert isinstance(d,dict) and 'error' not in d and isinstance(d['items'],list)
 q=parse_qs(urlparse(url).query);assert q['op']==['and'] and q['page']==['1'] and q['itemsPerPage']==['20'];assert d['page']==1 and d['totalPages']<=1 and d['totalItems']==len(d['items'])
 for r in d['items']:assert all(str(r[k])==q[k][0] for k in ('year','month','day'))
 rows.append({'source_id':o['source_id'],'development_event_ids':meta['affected_event_ids'],'returned_events':len(d['items']),'ncei_event_ids':[r['id'] for r in d['items']],'raw_sha256':o['sha256']})
receipt={'status':'PASS','contracts':len(outs),'bytes':sum(o['bytes'] for o in outs),'date_and_pagination_validated':True,'reserved_requests':0,'counts':[r['returned_events'] for r in rows],'rows':rows,'script_sha256':sha(Path(__file__))}
assert not out.exists();out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print({k:v for k,v in receipt.items() if k!='rows'})
