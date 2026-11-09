"""Unmodified G0 proof under exact prospective worker startup; zero sampling."""
import hashlib
import json
import os
import time
import traceback
from pathlib import Path

ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
CACHE=ROOT/'data/processed/models/arrival-development-recovery-v1/cache'
OUTPUT=Path('/private/tmp/tsunami-G0-exact-worker-artifact-proof.json')
ENV=dict(PYTENSOR_FLAGS=f'floatX=float64,base_compiledir={CACHE / "pytensor"}',
         NUMBA_CACHE_DIR=str(CACHE/'numba'),MPLCONFIGDIR=str(CACHE/'matplotlib'),
         OPENBLAS_NUM_THREADS='2',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',
         VECLIB_MAXIMUM_THREADS='2',NUMEXPR_NUM_THREADS='2')
assert not OUTPUT.exists()
assert all(os.environ.get(k)==v for k,v in ENV.items())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pqa_path=Path('/private/tmp/tsunami-g0-closed-runtime-qa.json')
assert sha(pqa_path)=='4ee01a8ecd2791055ddd112a5ae7487ec7b6c2a987fdf9f5978552e17354871a'
pqa=json.loads(pqa_path.read_text())
assert pqa['job']['id']=='full-smoke-0-a' and pqa['worker_returncode']==0


def cache_manifest():
    found={}
    for p in sorted(CACHE.rglob('*')):
        assert p.resolve()==p and (p.is_dir() or p.is_file()),p
        if p.is_file():found[str(p.relative_to(ROOT))]=dict(sha256=sha(p),bytes=p.stat().st_size)
    return found


started=time.monotonic()
before=cache_manifest()
receipt=dict(status='unmodified_G0_strict_proof_started',
             exact_environment_before_scientific_imports=ENV,
             original_failure_status_preserved=True,new_sampler_calls=0,
             cache_only_project_writes=True,cache_before=before,
             original_runtime_qa_sha256=sha(pqa_path))
try:
    import numba
    import pytensor
    from analysis.arrival import model_development_recovery as G
    from scripts import run_arrival_development_journal as J
    assert pytensor.config.floatX=='float64'
    assert Path(pytensor.config.base_compiledir)==CACHE/'pytensor'
    assert Path(pytensor.config.compiledir).is_relative_to(CACHE/'pytensor')
    assert Path(numba.config.CACHE_DIR)==CACHE/'numba'
    a=J.admit(ROOT,'full_design_recovery')
    G.data._unchanged(ROOT,pqa['files'])
    J.safe(ROOT,a,extra=pqa['files'],reserve=True)
    admitted=G.verify_gate(ROOT)
    job=admitted['gate']['jobs'][0]
    assert job==pqa['job']
    # The public verifier is called directly and remains unmodified/unwrapped.
    proof=G.case_artifacts(ROOT,job,admitted['files'])
    folder,raw=G.case_paths(ROOT,job)
    saved_oracle=json.loads((folder/'numerical-oracles.json').read_text())
    assert saved_oracle['passed'] is True
    J.safe(ROOT,a,extra=J.merge(pqa['files'],proof['files']),reserve=True)
    G.data._unchanged(ROOT,J.merge(admitted['files'],proof['files'],pqa['files']))
    receipt.update(status='unmodified_G0_strict_artifact_proof_passed_exact_worker_startup',
                   proof=proof,source_files=admitted['files'],
                   authority_files=a['files'],original_producer_files=pqa['files'],
                   actual_replayed_oracle_bound_by_exact_unmodified_comparison=saved_oracle,
                   raw_sha256=sha(raw),worker_gate_sha256=admitted['files'][G.GATE],
                   authority_gate_sha256=a['files'][J.gate_path('full_design_recovery')],
                   original_worker_result_status=json.loads((folder/'result.json').read_text())['status'],
                   original_controller_attempt_outcome=json.loads((ROOT/pqa['attempt']).read_text())['outcome'],
                   calls_charged=1,calls_started=1,
                   source_and_quota_with_608MiB_reserve_before_after='PASS',
                   live_STATE_or_context_bodies_copied=False,
                   no_execution_continuation_or_logical_promotion_authorized=True,
                   pytensor_config=dict(floatX=pytensor.config.floatX,
                                        base_compiledir=pytensor.config.base_compiledir,
                                        compiledir=pytensor.config.compiledir,
                                        mode=str(pytensor.config.mode)),
                   numba_cache_dir=numba.config.CACHE_DIR)
except Exception as error:
    receipt.update(status='unmodified_G0_strict_proof_failed_retained',
                   exception=dict(type=type(error).__name__,message=str(error),
                                  traceback=traceback.format_exc()))
finally:
    after=cache_manifest()
    receipt.update(elapsed_seconds=time.monotonic()-started,cache_after=after,
                   cache_after_bytes=sum(v['bytes'] for v in after.values()),
                   audit_code_sha256=sha(Path(__file__)))
    with OUTPUT.open('x') as f:json.dump(receipt,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(dict(receipt=str(OUTPUT),sha256=sha(OUTPUT),status=receipt['status'],
                          exception=receipt.get('exception'),elapsed_seconds=receipt['elapsed_seconds'],
                          cache_bytes=receipt['cache_after_bytes'])))
