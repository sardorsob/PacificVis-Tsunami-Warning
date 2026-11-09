"""Root-authorized one retained G2 replay and append-only scientific review."""
import hashlib,json,os,time
from pathlib import Path

ROOT=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
CONTROL='artifacts/models/arrival-timing/development-check-v1/controller/technical-completion-v1'
REVIEW=CONTROL+'/G2-stable-review.json'
EVIDENCE=CONTROL+'/G2-review-evidence-v2/'
SOURCE_REVIEW='artifacts/models/arrival-timing/development-design-v1/technical-completion-v2/replay-source-review.json'
PROOF='artifacts/models/arrival-timing/full-development-recovery-v1/diagnostic-replay-v2/full-smoke-1-a/proof.json'
OLD_PROOF='artifacts/models/arrival-timing/full-development-recovery-v1/strict-proofs/full-smoke-1-a/proof.json'
ATTEMPT=CONTROL+'/attempts/full_design_recovery/full-smoke-1-a.json'
T_SOURCES={'analysis/arrival/model_development_technical_completion.py','scripts/run_arrival_development_technical_completion.py','tests/test_arrival_development_technical_completion.py'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda n:json.loads((ROOT/n).read_text())
encoded=lambda value:(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
assert not any((ROOT/n).exists() or (ROOT/n).is_symlink() for n in [REVIEW,EVIDENCE,PROOF,OLD_PROOF,ATTEMPT])
assert sha(ROOT/SOURCE_REVIEW)=='1e1ba81c8283e04a679bc7d24404693e595c2c16b07f2c7c454fdff59379d3c9'
qa=read(SOURCE_REVIEW)
assert qa['status']=='accepted_frozen_development_diagnostic_replay_source' and qa['independent_checker']
runtime=Path('/private/tmp/tsunami-technical-G2-retained-partial-runtime-qa.json')
scope=Path('/private/tmp/tsunami-G2-closed-WORKER-diagnostic-process-proof.json')
assert sha(runtime)=='0da732d18208ce5cb6385dbbd92f7d65b7f6cfa38d5fc33f908c2757afe24c78'
assert sha(scope)=='180df32f94dd48dd201f5846b9e702c26147143b05c518cb3697e9d3df2f0e83'
pqa=json.loads(runtime.read_text());closed=json.loads(scope.read_text());job=closed['job']
assert closed['closed'] and closed['diagnostic_scope_only'] and not closed['scientific_acceptance']
assert pqa['inclusive_calls_charged']==pqa['inclusive_calls_started']==3
started=time.monotonic()
from analysis.arrival import model_development_recovery as G
from analysis.arrival import model_development_replay as R
from scripts import run_arrival_development_journal as J

admission=G.verify_gate(ROOT)
pins={}
def merge(mapping):
 for name,digest in mapping.items():
  assert name not in pins or pins[name]==digest,name
  pins[name]=digest
merge(admission['files']);merge(qa['files']);merge({SOURCE_REVIEW:sha(ROOT/SOURCE_REVIEW)})
assert not T_SOURCES & set(pins)
assert job==admission['gate']['jobs'][2]
G.data._unchanged(ROOT,pins);G.data._unchanged(ROOT,closed['files'])
states_before={name:sha(ROOT/name) for name in pqa['states_conserved']}
assert states_before==pqa['states_conserved']
assert J.c2.quota(ROOT,dict(gate=admission['gate'],files=pins,phase='full_design_recovery'),reserve=True,known_files={**pins,**closed['files']}) is None
# The single newly authorized full replay. No sampler or old exact-verifier retry.
verified=R.case_artifacts(ROOT,job,pins)
assert verified['proof_contract']==R.PROOF_CONTRACT
assert len(verified['files'])==18 and verified['posterior_sha256']==pqa['raw_sha256']
proof=dict(status='scientific_artifact_replay_passed',proof_contract=R.PROOF_CONTRACT,
           job=job,worker_files=verified['files'],sampler_calls=0,
           original_exact_oracle_equal=verified['original_exact_oracle_equal'],
           diagnostic_comparison=verified['diagnostic_comparison'])
G.data._unchanged(ROOT,{**pins,**closed['files'],**verified['files']})
assert not (ROOT/OLD_PROOF).exists() and not (ROOT/ATTEMPT).exists()
path=ROOT/PROOF;path.parent.mkdir(parents=True)
with path.open('xb') as f:f.write(encoded(proof))
merge(closed['files']);merge(verified['files']);merge({PROOF:sha(path)})
folder,_=G.case_paths(ROOT,job)
allocation=CONTROL+'/allocations/full_design_recovery/'+job['id']+'.json'
alloc=read(allocation)
supervisor=str(folder.with_name(folder.name+'.supervisor.json').relative_to(ROOT))
failure=pqa['controller_failure_marker']
original_failed_process=closed['strict_verifier']['proof_process']
original_failed_log=closed['strict_verifier']['proof_log']
original_plan=alloc['plan'];authority=alloc['authority_gate'];kernel=alloc['worker_gate']
# Historical documents are pinned as artifacts, never by flattening their embedded old T maps.
historical=[allocation,supervisor,failure,original_failed_process,original_failed_log,
            original_plan,authority,kernel,CONTROL+'/sampler-pilot-review-acceptance.json',
            CONTROL+'/baseline-review.json']
merge({name:sha(ROOT/name) for name in historical})
assert not T_SOURCES & set(pins)
copies={
 'closed-runtime-qa.json':runtime,
 'closed-worker-diagnostic-scope.json':scope,
 'independent-numerics.json':Path('/private/tmp/ms6-G2-closed-scientific-diagnostic/scientific-diagnostic.json'),
 'independent-math-visual-review.json':Path('/private/tmp/ms6-G2-closed-scientific-diagnostic/independent-diagnostic-review.json'),
 'chart-diagnostics.json':Path('/private/tmp/ms6-G2-chart-diagnostics.json'),
 'trace-rank.png':Path('/private/tmp/ms6-G2-closed-scientific-diagnostic/trace-rank.png'),
 'energy.png':Path('/private/tmp/ms6-G2-closed-scientific-diagnostic/energy.png'),
 'independent-audit-code.py':Path('/private/tmp/audit-ms6-G2-closed-diagnostic.py'),
 'chart-audit-code.py':Path('/private/tmp/chartcheck-ms6-G2-trusted-plots.py'),
 'frozen-science-helper.py':Path('/private/tmp/check-ms6-recovery-science.py'),
 'frozen-dense-reference-source.py':Path('/private/tmp/recovery_scientific_checker.py'),
 'validation-publication-code.py':Path(__file__),
}
assert sha(copies['independent-numerics.json'])=='2832f0c32908f306974422e58875979ae079fad198c181127bb40ffe51334e6c'
assert sha(copies['independent-math-visual-review.json'])=='7e92e1e76371da54f82833afac91b5a36de35d7aff927266487d6a52d1c2d518'
science=json.loads(copies['independent-numerics.json'].read_text())
visual=json.loads(copies['independent-math-visual-review.json'].read_text())
assert science['density']['passed'] and science['seeded_tables']['passed']
assert visual['visual_review']['status']=='PASS_at_native_resolution_no_P0_P1'
evidence=ROOT/EVIDENCE;evidence.mkdir()
for name,source in copies.items():
 with (evidence/name).open('xb') as f:f.write(source.read_bytes())
 merge({EVIDENCE+name:sha(evidence/name)})
assert not T_SOURCES & set(pins)
review=dict(schema_version=1,status='accepted_frozen_development_G2_stable_revalidation',
 independent_checker=True,checker='/root/sumatra_path_oracles',job=job,cost=1,start_markers=1,
 calls_charged=3,calls_started=3,new_sampler_calls=0,
 original_controller_outcome='failed_before_attempt',original_exact_oracle_guard_passed=False,
 original_proof_output_absent=True,original_accepted_attempt_absent=True,
 confirmation_outcomes_parsed=True,development_check_previously_inspected=True,
 reserved_outcomes='sealed',reserved_outcomes_parsed=False,
 specification_freeze_sha256=pins[G.data.FREEZE],
 original_allocation=allocation,original_allocation_sha256=pins[allocation],
 original_failure=failure,original_failure_sha256=pins[failure],
 original_supervisor=supervisor,original_supervisor_sha256=pins[supervisor],
 original_failed_proof_process=original_failed_process,original_failed_proof_process_sha256=pins[original_failed_process],
 original_failed_proof_log=original_failed_log,original_failed_proof_log_sha256=pins[original_failed_log],
 original_plan=original_plan,original_plan_sha256=pins[original_plan],
 original_authority_gate=authority,original_authority_gate_sha256=pins[authority],
 original_worker_gate=kernel,original_worker_gate_sha256=pins[kernel],
 posterior=verified['posterior'],posterior_sha256=verified['posterior_sha256'],
 stable_proof=PROOF,stable_proof_sha256=pins[PROOF],
 original_invocation_git_sha=alloc['invocation_git_sha'],worker_files=verified['files'],
 proof_contract=R.PROOF_CONTRACT,stable_replay_original_exact_oracle_equal=verified['original_exact_oracle_equal'],
 diagnostic_comparison=verified['diagnostic_comparison'],
 original_diagnostic_cause=visual['cause'],
 prior_native_diagnostic_summary=visual['native_diagnostics'],
 independent_scientific_review=EVIDENCE+'independent-math-visual-review.json',
 independent_scientific_review_sha256=pins[EVIDENCE+'independent-math-visual-review.json'],
 replay_source_review=SOURCE_REVIEW,replay_source_review_sha256=pins[SOURCE_REVIEW],
 original_artifact_statuses_and_bytes_preserved=True,no_retuning_or_threshold_change=True,
 exact_diagnostic_equality_replaced_only_by_original_scientific_predicates=True,
 historical_runtime_maps_not_flattened=True,
 selected_model_or_prior_or_data_or_seed_changed=False,
 scope='One retained known-truth computation smoke, not calibration/coverage/bias or physical validation.',
 private_state_hashes_history_only=states_before,no_live_private_STATE_body_pins=True,
 full_G6_or_full3_complete=False,execution_authority=False,files=dict(pins))
for name,digest in pins.items():assert sha(ROOT/name)==digest,name
assert {name:sha(ROOT/name) for name in states_before}==states_before
assert J.c2.quota(ROOT,dict(gate=admission['gate'],files=pins,phase='full_design_recovery'),reserve=True,known_files=pins) is None
with (ROOT/REVIEW).open('xb') as f:f.write(encoded(review))
# Exact current coordinator metadata contract, without a future authority or native replay.
from analysis.arrival import model_development_technical_completion as T
checked=T._g2_revalidation(ROOT,dict(jobs=admission['gate']['jobs'],files={**pins,REVIEW:sha(ROOT/REVIEW)}))
assert checked['producer']=='G2_stable_scientific_revalidation'
assert J.c2.quota(ROOT,dict(gate=admission['gate'],files=pins,phase='full_design_recovery'),reserve=True,known_files={**pins,REVIEW:sha(ROOT/REVIEW)}) is None
for name,digest in pins.items():assert sha(ROOT/name)==digest,name
assert {name:sha(ROOT/name) for name in states_before}==states_before
assert not (ROOT/OLD_PROOF).exists() and not (ROOT/ATTEMPT).exists()
result=dict(status=review['status'],review=REVIEW,review_sha256=sha(ROOT/REVIEW),
            stable_proof=PROOF,stable_proof_sha256=sha(ROOT/PROOF),files=len(pins),
            original_exact_oracle_equal=verified['original_exact_oracle_equal'],
            diagnostic_deltas=verified['diagnostic_comparison']['diagnostic_deltas'],
            metadata_contract='T._g2_revalidation PASS',quota_with_608MiB='PASS',
            private_hashes_unchanged=True,elapsed_seconds=time.monotonic()-started,new_sampler_calls=0)
with Path('/private/tmp/tsunami-G2-stable-publication-receipt.json').open('x') as f:json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
print(json.dumps(result))
