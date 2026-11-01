"""Verify untouched foundation/audit/story products against their original receipts."""
from pathlib import Path
import hashlib,json
root=Path.cwd();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=root/'artifacts/logs/runs/2026-10-31__231956__ntwc-foundation-final__c4d5044/outputs.json';groups=json.loads(source.read_text());verified={}
for group,value in groups.items():
 for r in value['files']:
  p=root/r['path'];assert sha(p)==r['sha256'],r['path'];assert p.stat().st_size==r['bytes']
 verified[group]=len(value['files'])
reference=root/'artifacts/logs/runs/2026-10-14-story-followups-v3/inputs.json';records=json.loads(reference.read_text());print('storyreference',type(records).__name__)
if isinstance(records,dict):records=records['files']
for r in records:
 p=root/r['path'];assert sha(p)==r['sha256'],r['path']
assert len(records)==72
receipt={'status':'PASS','frozen_foundation_groups':verified,'frozen_files_checked':sum(verified.values()),'original_story_files_checked':len(records),'story_reference_sha256':sha(reference),'frozen_output_manifest_sha256':sha(source),'script_sha256':sha(Path(__file__))}
(root/'artifacts/generated/ntwc-batch/recovery-execution-v1/frozen-products-check.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(receipt)
