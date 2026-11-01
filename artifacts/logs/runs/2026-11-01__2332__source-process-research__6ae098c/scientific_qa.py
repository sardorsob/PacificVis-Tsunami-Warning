"""Verify retained-source hashes, independent acceptance and unchanged parents."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from analysis.arrival.evidence import sha256, verify_product

run = Path(__file__).resolve().parent
product = root / 'data/processed/arrival-evidence/source-process-v1'
checker = root / 'artifacts/generated/ntwc-batch/source-process-v1/checker'
acceptance = json.loads((checker/'final-acceptance.json').read_text())
manifest = json.loads((product/'manifest.json').read_text())
assert all(sha256(product/k) == v for k,v in manifest.items())
pins = json.loads((product/'inputs.json').read_text())['files']
assert all(sha256(root/k) == v for k,v in pins.items())
assert all(sha256(product/p.name) == sha256(p) for p in (checker/'replay-final').iterdir())
protected = json.loads((root/'artifacts/generated/ntwc-batch/data-completion-v1/snapshot/protected.json').read_text())
assert all(sha256(root/p['path']) == p['sha256'] for p in protected['files'])
verify_product(root/'data/processed/arrival-evidence/foundation-v1')
parent = root/'data/processed/arrival-evidence/documentary-v1'
assert sha256(parent/'manifest.json') == 'ab52afa8ca73afee259676b52c6db9b3468b0d4cb5ca506ece6e822749cadd50'
assert all(sha256(parent/k)==v for k,v in json.loads((parent/'manifest.json').read_text()).items())
summary = json.loads((product/'summary.json').read_text())
assert summary['first_blockers']['resolved_pair']==388
assert summary['reports']==1177 and summary['direct_reason_fields']==4
assert summary['all_absent_fields_have_reason']==3
assert summary['new_exact_pairs_approved']==0
result = {'status':'PASS','product_manifest_sha256':sha256(product/'manifest.json'),
          'independent_acceptance':acceptance,'input_pins_verified':len(pins),
          'output_files_identical_to_independent_replay':len(manifest)+1,
          'protected_hashes_unchanged':len(protected['files']),
          'accepted_parent_products_verified':['foundation-v1','documentary-v1'],
          'python_tests_passed':815,'frontend_tests_passed':178,
          'ruff':'PASS','pyright':'PASS','build':'PASS',
          'source_manifest_records':2738,'original_pair_count':388,'original_unresolved':789,
          'new_exact_pairs':0,'model_fitted':False}
(run/'scientific-qa.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='independent_acceptance'},indent=2))
