"""Lossless TEMP receipt serialization recovery; never repeats G.case_artifacts."""
import hashlib
import json
import os
from pathlib import Path

ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
CACHE=ROOT/'data/processed/models/arrival-development-recovery-v1/cache'
PARTIAL=Path('/private/tmp/tsunami-G0-exact-worker-artifact-proof.json')
OUTPUT=Path('/private/tmp/tsunami-G0-exact-worker-artifact-proof-recovered.json')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert not OUTPUT.exists()
text=PARTIAL.read_text()
marker='  "pytensor_config": {'
assert text.endswith('    "base_compiledir": ') and text.count(marker)==1
prefix=text[:text.index(marker)].rstrip().removesuffix(',')+'\n}'
receipt=json.loads(prefix)
assert receipt['proof']['role']=='full_design_recovery'
assert receipt['proof']['posterior_sha256']=='bd29f67ec725326efda9805f650af3f8cae033a4a5f7f28bdc3902edb71ed13c'
assert receipt['actual_replayed_oracle_bound_by_exact_unmodified_comparison']['passed'] is True
assert receipt['original_controller_attempt_outcome']=='needs_review'
assert receipt['original_worker_result_status']=='computed_pending_scientific_review'
assert receipt['calls_charged']==receipt['calls_started']==1
assert all(os.environ.get(k)==v for k,v in receipt['exact_environment_before_scientific_imports'].items())
assert sha(Path('/private/tmp/replay-ms6-G0-exact-worker-environment.py'))==receipt['audit_code_sha256']

import numba
import pytensor
from analysis.arrival import model_development_recovery as G
from scripts import run_arrival_development_journal as J

a=J.admit(ROOT,'full_design_recovery')
admitted=G.verify_gate(ROOT)
pqa=json.loads(Path('/private/tmp/tsunami-g0-closed-runtime-qa.json').read_text())
assert a['files']==receipt['authority_files']
assert pqa['files']==receipt['original_producer_files']
assert len(receipt['proof']['files'])==18
assert Path(pytensor.config.base_compiledir)==CACHE/'pytensor'
assert Path(pytensor.config.compiledir).is_relative_to(CACHE/'pytensor')
assert Path(numba.config.CACHE_DIR)==CACHE/'numba'
G.data._unchanged(ROOT,J.merge(a['files'],receipt['proof']['files'],pqa['files']))
J.safe(ROOT,a,extra=J.merge(pqa['files'],receipt['proof']['files']),reserve=True)
receipt.update(status='unmodified_G0_strict_artifact_proof_passed_exact_worker_startup',
               source_files=admitted['files'],
               pytensor_config=dict(floatX=str(pytensor.config.floatX),
                                    base_compiledir=str(pytensor.config.base_compiledir),
                                    compiledir=str(pytensor.config.compiledir),
                                    mode=str(pytensor.config.mode)),
               source_and_quota_with_608MiB_reserve_before_after='PASS',
               receipt_serialization_recovery=dict(original_partial_receipt=str(PARTIAL),
                    original_partial_sha256=sha(PARTIAL),
                    error='json.dump rejected PosixPath pytensor.config.base_compiledir after the complete unmodified verifier and post-proof source/quota checks returned.',
                    retained_partial_unmodified=True,proof_and_oracle_replayed_again=False,
                    original_code_control_flow_proves_success_before_serialization=True,
                    only_remaining_config_and_source_metadata_reconstructed=True,
                    fresh_metadata_source_quota_check='PASS',
                    recovery_code_sha256=sha(Path(__file__))),
               no_execution_continuation_or_logical_promotion_authorized=True)
assert all(sha(ROOT/n)==h for n,h in receipt['proof']['files'].items())
with OUTPUT.open('x') as stream:
    json.dump(receipt,stream,sort_keys=True,indent=2,allow_nan=False)
    stream.write('\n')
assert sha(PARTIAL)==receipt['receipt_serialization_recovery']['original_partial_sha256']
print(json.dumps(dict(receipt=str(OUTPUT),sha256=sha(OUTPUT),status=receipt['status'],
                     strict_proof_files=len(receipt['proof']['files']),
                     elapsed_seconds=receipt['elapsed_seconds'],cache_after_bytes=receipt['cache_after_bytes'],
                     native_proof_repeated=False,partial_sha256=sha(PARTIAL))))
