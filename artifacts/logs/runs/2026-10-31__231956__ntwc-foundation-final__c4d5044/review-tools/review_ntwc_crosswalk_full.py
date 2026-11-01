from pathlib import Path
import csv,json,hashlib,tomllib,re,sys,math,base64
from urllib.parse import urlsplit,unquote,parse_qs
from datetime import datetime
from pyproj import Geod
root=Path.cwd(); folder=Path(sys.argv[1]); review_name=sys.argv[2]
sha=lambda b:hashlib.sha256(b).hexdigest()
normal=lambda s:re.sub('[^a-z0-9]','',s.casefold())
canon=lambda u:unquote(u).replace('http://','https://')
contracts={}
cdx_sources={a['local_path']:a for a in tomllib.loads(Path('config/ia-cdx-dev-scoped.toml').read_text())['assets'].values()}
cdx_receipts={r['source_id']:r for r in json.loads(Path('artifacts/logs/runs/2026-10-31__2034__ia-cdx-dev-scoped__c4d5044/outputs.json').read_text())}
for p in [Path('config/tohoku-data-proof.toml'),Path('config/ia-header-probes-reviewed.toml'),Path('artifacts/generated/ntwc-batch/waveform-contracts-v1/ia-001.toml'),Path('config/ia-site-headers-v2.toml'),Path('config/station-registries-verified.toml'),Path('config/coops-waveform-audit.toml')] + sorted(Path('artifacts/generated/ntwc-batch/waveform-full-contracts-v2').glob('ia-*.toml')):
 for k,a in tomllib.loads(p.read_text()).get('assets',{}).items():contracts[a.get('source_id',k)]=a
links=json.loads(Path('artifacts/generated/ntwc-batch/census-v4/links.json').read_text());rows=json.loads(Path('artifacts/generated/ntwc-batch/census-v4/rows.json').read_text())
reports={f"{r['event_id']}:{r['table_index']}:{r['row_index']}":r for r in rows}
linkmap={}
for l in links:linkmap.setdefault(f"{l['event_id']}:{l['table_index']}:{l['row_index']}",set()).add(canon(l['resolved_url']))
a=list(csv.DictReader((folder/'unique_report_crosswalk.csv').open()));assert len(a)==1177 and len({r['report_id'] for r in a})==1177
approved=[]; distances=[];headers=set(); seenlabels=set();g=Geod(ellps='WGS84')
for r in a:
 assert r['role']=='development' and r['report_id'] in reports
 assert r['model_eligible']=='False' and r['physical_onset_validated']=='False' and r['deployment_continuity_verified']=='False'
 assert sha(r['evidence'].encode())==r['identity_evidence_sha256']
 if r['event_site_identity_verified']!='True':continue
 assert r['identity_tier']=='header_exact'
 alts=json.loads(r['evidence']);assert len(alts)==int(r['alternative_count'])
 for e in alts:
  assert e['event_id']==r['event_id'] and e['report_id']==r['report_id'] and e['physical_site_id']==r['physical_site_id']
  assert ' '.join(reports[r['report_id']]['fields']['location'].split())==e['report_label']
  for h in e['headers']:
   c=contracts[h['source_id']];p=Path(c['local_path']);b=p.read_bytes();assert sha(b)==h['sha256']==p.with_name(p.name+'.sha256').read_text().strip()
   assert c['url']==h['source_url']
   if c.get('expected_cdx_sha1'):
    assert base64.b32encode(hashlib.sha1(b,usedforsecurity=False).digest()).decode()==c['expected_cdx_sha1']
    cd=Path(c['cdx_evidence_path']);cb=cd.read_bytes();assert sha(cb)==c['cdx_evidence_sha256']==cd.with_name(cd.name+'.sha256').read_text().strip()
    u=c['url']; capture=re.fullmatch(r'https://web.archive.org/web/(\d{14})id_/(https?://.+)',u);assert capture
    crows=json.loads(cb);matches=[dict(zip(crows[0],v)) for v in crows[1:] if dict(zip(crows[0],v)).get('timestamp')==capture[1] and dict(zip(crows[0],v)).get('original')==capture[2]]
    cc=cdx_sources[str(cd)];cr=cdx_receipts[cc['source_id']]
    assert parse_qs(urlsplit(cc['url']).query)['filter']==['statuscode:200']
    assert cr['status'] in {'downloaded','cached'} and cr['sha256']==sha(cb) and cr['local_path']==str(cd)
    assert any(v.get('digest')==c['expected_cdx_sha1'] and v.get('statuscode','200')=='200' for v in matches)

   assert canon(h['original_url']) in linkmap[r['report_id']]
   first=b.decode('utf-8').splitlines()[0].split(); assert len(first)==7,first
   assert first[0]==h['header_name'] and first[1]==h['header_station_id'] and first[2]==h['provider'] and first[3]==h['sampling_mode']
   assert float(first[4])==h['latitude'] and float(first[5])==h['longitude']
   assert datetime.strptime(first[6],'%Y%m%d').date().isoformat()==h['header_date']
   fname=unquote(urlsplit(h['original_url']).path.rsplit('/',1)[-1]); mt=re.fullmatch(r'([A-Za-z0-9]+)_([A-Za-z0-9]+)_(\d{4})\.(\d{3})',fname) or re.fullmatch(r'([a-z0-9]+)([A-Z])(\d{4})\.(\d{3})',fname)
   assert mt and mt.groups()==(h['link_code'],h['link_sensor'],h['link_year'],h['link_day']), (r['report_id'],fname,mt.groups() if mt else None,h['link_code'],h['link_sensor'],h['link_year'],h['link_day'])
   assert datetime.strptime(h['link_year']+h['link_day'],'%Y%j').date().isoformat()==h['header_date']
   assert -90<=h['latitude']<=90 and -180<=h['longitude']<=180 and h['coordinate_crs']=='unknown'
   headers.add(h['source_id']);seenlabels.add((r['identity_scope'],e['report_label'],h['header_name'],r['provider_station_id']))
   if r['identity_scope']=='source_qualified_geographic_site':
    assert normal(e['report_label'])==normal(h['header_name'])
    sig={'provider':h['provider'],'archive_code':h['link_code'],'header_name':normal(h['header_name']),'header_station_id_state':h['header_station_id'],'latitude':h['latitude'],'longitude':h['longitude'],'coordinate_crs':'unknown'}
    assert sig==e['geographic_signature'] and 'ntwc-header-site:'+sha(json.dumps(sig,sort_keys=True,separators=(',',':')).encode())==r['physical_site_id']
   else:
    assert r['identity_scope']=='authoritative_provider_site' and r['provider']=='CO-OPS' and h['provider'] in ['NOS','NOAA','CO-OPS']
    assert r['provider_station_id']==h['header_station_id'] and r['physical_site_id']=='coops:'+h['header_station_id']
    assert e['registry_id_checks']
    for reg in e['registry_id_checks']:
     c2=contracts[reg['source_id']];p2=Path(c2['local_path']);b2=p2.read_bytes();assert sha(b2)==reg['sha256']
     station=[s for s in json.loads(b2)['stations'] if s['id']==reg['station_id']];assert len(station)==1
     s=station[0];assert s['lat']==reg['latitude'] and s['lng']==reg['longitude'] and s['id']==h['header_station_id']
     d=g.inv(h['longitude'],h['latitude'],s['lng'],s['lat'])[2]/1000;assert d<=2;distances.append(d)
 approved.append({'event_id':r['event_id'],'report_id':r['report_id'],'identity_evidence_sha256':r['identity_evidence_sha256'],'decision':'approved','reviewer':'root_independent_raw_witness_review_2026-10-31'})
print('RAW REVIEW:',len(approved),'identities',len(headers),'unique header sources',len(seenlabels),'distinct label pairs','distance range',min(distances),max(distances))
output=Path(review_name)
assert not output.exists()
with output.open('w') as f:w=csv.DictWriter(f,fieldnames=list(approved[0]));w.writeheader();w.writerows(approved)
receipt={'status':'pass','reviewer':'root independent raw-source and registry check','candidate_unique_report_sha256':sha((folder/'unique_report_crosswalk.csv').read_bytes()),'review_ledger_sha256':sha(output.read_bytes()),'report_matches_approved':len(approved),'distinct_site_ids':len({r['physical_site_id'] for r in a if r['event_site_identity_verified']=='True'}),'unique_raw_header_sources':len(headers),'report_header_labels_inspected':sorted(seenlabels),'checks':['All1177 report IDs conserved; no reserved or model/physical-onset promotion','Every candidate raw SHA/header name/provider/ID/coordinates/date exact','Each report exact linked-day/source URL verified','Every provider identity independently matched pinned registry ID and geodesic distance<=2km','All source-qualified geographic signatures independently recomputed; full names agree; sensors not part of site','Geographic identity only; deployment continuity unknown'],'registry_distance_km':[min(distances),max(distances)]}
output.with_suffix('.review.json').write_text(json.dumps(receipt,indent=2)+'\n')
