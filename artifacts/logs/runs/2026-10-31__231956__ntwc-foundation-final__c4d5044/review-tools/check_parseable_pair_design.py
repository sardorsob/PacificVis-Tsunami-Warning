"""Descriptive incidence graph for parseable reported clocks with reviewed site identity."""
from pathlib import Path
from collections import Counter, defaultdict
import csv, gzip, hashlib, json
import numpy as np
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
corpus=root/'data/processed/arrival-corpus/foundation-v4'
allrows=[]
for path in sorted(corpus.glob('*/pair.csv.gz')):
    with gzip.open(path,'rt',newline='') as stream: allrows.extend(csv.DictReader(stream))
rows=[r for r in allrows if r['event_site_identity_verified']=='True' and r['review_status']=='independently_reviewed']
assert len(allrows)==314 and len(rows)==148
assert all(r['physical_onset_validated']=='False' and r['model_eligible']=='False' for r in allrows)
assert all(r['deployment_continuity_verified']=='False' for r in rows)
edges=sorted({(r['event_id'],r['physical_site_id']) for r in rows})
assert all(site not in ('','unknown') for event,site in edges)
events=sorted({e for e,s in edges});sites=sorted({s for e,s in edges})
eidx={e:i for i,e in enumerate(events)};sidx={s:i+len(events) for i,s in enumerate(sites)}
a=np.zeros((len(edges),len(events)+len(sites)))
parent=list(range(a.shape[1]))
def find(i):
    while parent[i]!=i: parent[i]=parent[parent[i]];i=parent[i]
    return i
for i,(e,s) in enumerate(edges):
    a[i,eidx[e]]=a[i,sidx[s]]=1
    parent[find(eidx[e])]=find(sidx[s])
components=defaultdict(lambda:{'events':[],'sites':[]})
for e in events:components[find(eidx[e])]['events'].append(e)
for s in sites:components[find(sidx[s])]['sites'].append(s)
rank=int(np.linalg.matrix_rank(a))
assert rank==a.shape[1]-len(components)
result=dict(status='pass',scope='Descriptive intersection of parseable reported-clock pairs and independently reviewed geographic identity; not frozen model design or validated physical onsets.',corpus_summary_sha256=hashlib.sha256((corpus/'summary.json').read_bytes()).hexdigest(),parseable_report_rows=len(allrows),reviewed_identity_report_rows=len(rows),unique_event_site_edges=len(edges),repeated_event_site_report_rows=len(rows)-len(edges),events=len(events),sites=len(sites),components=len(components),indicator_columns=a.shape[1],indicator_rank=rank,median_site_event_degree=float(np.median(list(Counter(s for e,s in edges).values()))),event_report_counts=dict(sorted(Counter(r['event_id'] for r in rows).items())),component_members=list(components.values()),edges=edges,model_eligible_rows=0,physical_onsets_validated=0,deployment_continuity_verified=0,decision='Recompute after target, deployment identity, observation rules and eligibility are fixed. Do not use the broader source-cell graph as this modeling graph.')
out=root/'artifacts/generated/ntwc-batch/parseable-pair-identity-design-v1.json'
assert not out.exists();out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('edges','component_members','event_report_counts')},indent=2))
