"""Authorized append-only G0 science baseline; no numeric replay or execution."""
import hashlib
import json
from pathlib import Path

ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
CONTROL='artifacts/models/arrival-timing/development-check-v1/controller/technical-completion-v1'
REVIEW=CONTROL+'/baseline-review.json'
EVIDENCE=CONTROL+'/review-evidence-v1/'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads((ROOT/p).read_text())
sources={
 'strict-proof.json':('/private/tmp/tsunami-G0-exact-worker-artifact-proof-recovered.json','eb75a9416604bb63177ad7a7c06991d2d5bd6b01f8262506210c20bef9f21ed1'),
 'strict-original-serialization.partial.txt':('/private/tmp/tsunami-G0-exact-worker-artifact-proof.json','5fd8c808f26949664d3c5817ea636ae9d3195b097d9a6bcae4ff71fdbcaa882b'),
 'runtime-qa.json':('/private/tmp/tsunami-g0-closed-runtime-qa.json','4ee01a8ecd2791055ddd112a5ae7487ec7b6c2a987fdf9f5978552e17354871a'),
 'original-proof-failure.json':('/private/tmp/tsunami-g0-original-artifact-proof-diagnosis.json','c494152746190662674381917f1d442688fd708833c7c2b1bcb7b842735c6911'),
 'independent-science.json':('/private/tmp/ms6-G0-closed-scientific-diagnostic/scientific-diagnostic.json','f338d23cec6de2c093783201961c6e1d05c5e51c21ba4781faef9d8a8571fcd7'),
 'independent-math-and-visual-review.json':('/private/tmp/ms6-G0-closed-scientific-diagnostic/completed-diagnostic-review.json','d63511e4c414d012b16c7692e8274165ab90a5a4db8178cd5d64506a68d0751e'),
 'independent-math-helper.py':('/private/tmp/check-ms6-recovery-science.py','7bda5269951809400825c8262ea0bb7434127c85d7a322295719f0dcfcd54713'),
 'pure-dense-reference-source.py':('/private/tmp/recovery_scientific_checker.py','d976791947a9dcbdb672728acf01ee14abc95a2aefd5a05c4442e2560f5f3243'),
}
for path,digest in sources.values():assert sha(Path(path))==digest,path
strict=json.loads(Path(sources['strict-proof.json'][0]).read_text())
pqa=json.loads(Path(sources['runtime-qa.json'][0]).read_text())
science=json.loads(Path(sources['independent-science.json'][0]).read_text())
visual=json.loads(Path(sources['independent-math-and-visual-review.json'][0]).read_text())
assert strict['status']=='unmodified_G0_strict_artifact_proof_passed_exact_worker_startup'
assert strict['source_and_quota_with_608MiB_reserve_before_after']=='PASS'
assert strict['receipt_serialization_recovery']['proof_and_oracle_replayed_again'] is False
assert science['density']['passed'] and science['seeded_tables']['passed']
assert visual['visual_review']['status']=='PASS_at_native_resolution'
assert not (ROOT/REVIEW).exists() and not (ROOT/EVIDENCE).exists()
files={}
def merge(mapping):
 for name,digest in mapping.items():
  assert name not in files or files[name]==digest,name
  files[name]=digest
for mapping in [strict['source_files'],strict['authority_files'],strict['proof']['files'],pqa['files'],science['files']]:merge(mapping)
job=pqa['job'];assert job['id']=='full-smoke-0-a'
allocation=read(pqa['allocation']);attempt=read(pqa['attempt'])
folder=ROOT/'artifacts/models/arrival-timing/full-development-recovery-v1/jobs'/job['id']
supervisor=str(folder.with_name(folder.name+'.supervisor.json').relative_to(ROOT))
process=read(supervisor);result=read(str((folder/'result.json').relative_to(ROOT)))
assert allocation['job']==job and result['job']==job
assert attempt['outcome']=='needs_review' and attempt['cost']==attempt['start_markers']==1
assert result['status']=='computed_pending_scientific_review'
assert process['returncode']==0 and process['reason']=='worker_exit' and not process['monitor_failures']
assert process['cost']==process['start_markers']==1
assert process['invocation_git_sha']==allocation['invocation_git_sha']==pqa['producer_git_sha']
assert process['authority_gate_sha256']==files[allocation['authority_gate']]
assert process['worker_gate_sha256']==files[allocation['worker_gate']]
worker_files=strict['proof']['files']
assert len(worker_files)==18 and worker_files[result['posterior']]==result['posterior_sha256']
manifest=read(str((folder/'output-checksums.json').relative_to(ROOT)))
assert all(worker_files[str((folder/n).relative_to(ROOT))]==h for n,h in manifest.items())
for name,digest in files.items():
 p=ROOT/name;assert p.resolve()==p and p.is_file() and sha(p)==digest,name
freeze='artifacts/models/arrival-timing/specification-freeze-v1/review-acceptance.json'
inherited={n:h for n,h in read(freeze)['files'].items() if n.startswith('context/')}
assert len(inherited)==12 and {n:h for n,h in files.items() if n.startswith('context/')}==inherited
assert not any(n.endswith('/development-state.json') or n.endswith('/development-completion-state.json') or n.endswith('/sensitivity-state.json') for n in files)
# Durable byte-identical code/evidence copies; never import the old loop-bearing reference.
more={
 'strict-replay-code.py':Path('/private/tmp/replay-ms6-G0-exact-worker-environment.py'),
 'strict-receipt-recovery-code.py':Path('/private/tmp/recover-ms6-G0-worker-proof-receipt.py'),
 'independent-audit-code.py':Path('/private/tmp/audit-ms6-G0-closed-diagnostic.py'),
 'publication-code.py':Path(__file__),
 'trace-rank.png':Path('/private/tmp/ms6-G0-closed-scientific-diagnostic/trace-rank.png'),
 'energy.png':Path('/private/tmp/ms6-G0-closed-scientific-diagnostic/energy.png'),
}
assert sha(more['strict-replay-code.py'])==strict['audit_code_sha256']
assert sha(more['strict-receipt-recovery-code.py'])==strict['receipt_serialization_recovery']['recovery_code_sha256']
assert sha(more['independent-audit-code.py'])==visual['audit_code']['sha256']
for name in ['trace-rank.png','energy.png']:assert sha(more[name])==visual['figures'][str(more[name])]
evidence=ROOT/EVIDENCE;evidence.mkdir(parents=True)
for name,(path,digest) in sources.items():
 dest=evidence/name
 with dest.open('xb') as f:f.write(Path(path).read_bytes())
 assert sha(dest)==digest;files[EVIDENCE+name]=digest
for name,path in more.items():
 dest=evidence/name
 with dest.open('xb') as f:f.write(path.read_bytes())
 assert sha(dest)==sha(path);files[EVIDENCE+name]=sha(dest)
recipe=dict(scope='One closed synthetic G0 computation smoke revalidated; no calibration/coverage claim or new execution.',
 restore_literal_TEMP_sources={str((evidence/name).relative_to(ROOT)):path for name,(path,_) in sources.items()},
 restore_code_and_images={str((evidence/name).relative_to(ROOT)):str(path) for name,path in more.items()},
 warning='Never import pure-dense-reference-source.py as a module: its historical top-level loops are deliberately not executed. The accepted helper extracts only its pinned manual AST.',
 strict_environment_before_imports=strict['exact_environment_before_scientific_imports'],
 dynamic_cache_manifests_history_only=True,cache_bytes_after=strict['cache_after_bytes'],
 audit_cost=dict(new_sampler_calls=0,new_integration=0,existing_retained_cost=1),
 original_controller_failure_remains_immutable=True,
 serialization_recovery='Original unmodified strict proof returned all18 artifacts and passed exact saved-oracle comparison; JSON emission then rejected Path config. Exact partial bytes and metadata-only recovery are retained; strict proof was not repeated.',
 original_reason_not_fully_isolated=True,no_precision_threshold_or_model_change=True)
with (evidence/'reproduction.json').open('x') as f:json.dump(recipe,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
files[EVIDENCE+'reproduction.json']=sha(evidence/'reproduction.json')
review=dict(schema_version=1,status='accepted_frozen_development_G0_strict_revalidation',
 independent_checker=True,checker='/root/sumatra_path_oracles',confirmation_outcomes_parsed=True,
 development_check_previously_inspected=True,reserved_outcomes='sealed',reserved_outcomes_parsed=False,
 specification_freeze_sha256=files[freeze],job=job,cost=1,start_markers=1,
 original_controller_outcome='needs_review',original_worker_result_status=result['status'],
 original_receipt=pqa['attempt'],original_receipt_sha256=files[pqa['attempt']],
 original_allocation=pqa['allocation'],original_allocation_sha256=files[pqa['allocation']],
 original_supervisor=supervisor,original_supervisor_sha256=files[supervisor],
 original_plan=allocation['plan'],original_plan_sha256=files[allocation['plan']],
 original_worker_gate=allocation['worker_gate'],original_worker_gate_sha256=files[allocation['worker_gate']],
 original_authority_gate=allocation['authority_gate'],original_authority_gate_sha256=files[allocation['authority_gate']],
 posterior=result['posterior'],posterior_sha256=result['posterior_sha256'],
 original_invocation_git_sha=allocation['invocation_git_sha'],
 strict_proof=EVIDENCE+'strict-proof.json',strict_proof_sha256=files[EVIDENCE+'strict-proof.json'],
 worker_files=worker_files,unmodified_case_artifacts_complete_pass=True,
 strict_source_thresholds_and_exact_oracle_equality_unchanged=True,
 exact_worker_startup_environment=strict['exact_environment_before_scientific_imports'],
 cache_manifest_scope='historical hashes only; evolving cache files are not live Source pins',
 original_proof_failure=EVIDENCE+'original-proof-failure.json',original_proof_failure_sha256=files[EVIDENCE+'original-proof-failure.json'],
 runtime_review=EVIDENCE+'runtime-qa.json',runtime_review_sha256=files[EVIDENCE+'runtime-qa.json'],
 independent_math_visual_review=EVIDENCE+'independent-math-and-visual-review.json',
 independent_math_visual_review_sha256=files[EVIDENCE+'independent-math-and-visual-review.json'],
 original_reason_not_fully_isolated=True,original_statuses_and_all_original_bytes_preserved=True,
 no_failed_posterior_or_threshold_waiver=True,no_simulation_redraw_or_model_prior_seed_change=True,
 new_sampler_calls=0,calls_charged=1,calls_started=1,
 calibration_or_coverage_or_bias_or_physical_claim=False,
 completed_G6_or_full3_review=False,execution_authority=False,
 private_state_hashes_history_only=pqa['states_conserved'],no_live_private_STATE_body_pins=True,
 files=files)
# Existing frozen resource/history primitives only; no admission, numerical replay or child.
from scripts import run_arrival_development_journal as J
a=dict(gate=read(allocation['authority_gate']),files=strict['authority_files'],phase='full_design_recovery')
J.safe(ROOT,a,extra=files,reserve=True)
assert sum(p.stat().st_size for p in evidence.iterdir())<32*1024**2
for name,digest in files.items():assert sha(ROOT/name)==digest,name
with (ROOT/REVIEW).open('x') as f:json.dump(review,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
J.safe(ROOT,a,extra={**files,REVIEW:sha(ROOT/REVIEW)},reserve=True)
for name,digest in files.items():assert sha(ROOT/name)==digest,name
print(json.dumps(dict(review=REVIEW,status=review['status'],sha256=sha(ROOT/REVIEW),
                      files=len(files),worker_files=len(worker_files),
                      evidence_bytes=sum(p.stat().st_size for p in evidence.iterdir()),
                      original_outcome=attempt['outcome'],new_sampler_calls=0)))
