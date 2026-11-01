"""Append this acquisition's identities without changing any v3 source row."""
import json
import sys
from pathlib import Path

root=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root))
from analysis.arrival.evidence import read_rows,write_rows
from scripts.build_paper_manifest import build
from pipeline.provenance import validate_manifest

old=read_rows(root/'artifacts/provenance/paper-source-manifest-v3.csv')
new=build(root,sorted((root/'artifacts/logs/runs').glob('*documentary-recovery-b*')))
for row in new:
    if row['source_id'] in {'documentary-b03-02','documentary-b03-05'}:
        notes=json.loads(row['notes'])
        notes['scientific_disposition']='excluded_wrong_event_response'
        row['notes']=json.dumps(notes,sort_keys=True)
        row['status']='rejected'
        row['missingness']='Historical query returned current-event metadata; excluded; raw retained'
output=root/'artifacts/provenance/paper-source-manifest-v4.csv'
write_rows(output,old+new,columns=list(old[0]))
result=validate_manifest(output)
assert result.records==len(old)+len(new)
print('preserved',len(old),'appended',len(new),'total',len(old)+len(new))
