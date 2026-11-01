import sys,json
from pathlib import Path
r=Path(sys.argv[1]).resolve();sys.path.insert(0,str(r))
from analysis.arrival.evidence import read_rows,write_rows
from scripts.build_paper_manifest import build
from pipeline.provenance import validate_manifest
old=read_rows(r/'artifacts/provenance/paper-source-manifest-v4.csv')
new=build(r,sorted((r/'artifacts/logs/runs').glob('*source-process-b*')))
p=r/'artifacts/provenance/paper-source-manifest-v5.csv'
write_rows(p,old+new,columns=list(old[0]));v=validate_manifest(p)
print('old',len(old),'new',len(new),'total',v.records)
