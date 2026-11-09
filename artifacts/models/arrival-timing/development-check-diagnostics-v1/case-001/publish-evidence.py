"""Publish the explicitly authorized scientific gap, preserving failed computations."""
from pathlib import Path
import hashlib,json
from analysis.arrival import model_development_score_resolution as m
from analysis.arrival import model_development_fit as fit
from scripts import run_arrival_development_completion as c
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
t=Path('/private/tmp/tsunami-development-case1-gap-draft')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
packet=json.loads((t/'publication-packet.json').read_text())
assert sha(t/'publication-packet.json')=='97ab6eef0f1b843898604d86d2a8cec26f4de5370fdd099edec6e5a48a860559'
assert sha(t/'review-acceptance.DRAFT.json')=='c319c3f7db0fce6cb7d70dcf11799b66d325f23906064f6e5f5c62e3b15a7517'
review=json.loads((t/'review-acceptance.DRAFT.json').read_text());public=Path(packet['public_review']).parent
assert not (root/public).exists()
pqa_path=Path('/private/tmp/tsunami-development-failed-check-runtime-qa.json')
assert sha(pqa_path)=='20b6c3c6977e990fb224719d6bdb5a55a55bda2ac3d44feeb14d2852fa1bae25'
pqa=json.loads(pqa_path.read_text())
assert pqa['status']=='accepted_retained_failed_check_runtime_metadata' and pqa['independent_checker'] is True
assert pqa['actual_sampler_calls_charged']==pqa['actual_sampler_calls_started']==pqa['sampler_markers']==0
assert pqa['all_four_leases_absent'] and pqa['strict_inventory_recheck_after_removal']=='passed' and pqa['current_and_reserved_quota_passed']
assert pqa['live_STATE_pinned_or_copied'] is False and pqa['remaining_four_jobs_unattempted'] is True
assert pqa['closed_continuation_state_sha256']==review['failed_continuation_state_sha256']=='09e38b7765779348dc33945fddb1ca57b7ac072462a5e8e6d05f86451b6eaa57'
assert pqa['original_development_state_sha256']==review['original_state_sha256']==m.ORIGINAL_STATE_SHA
assert pqa['attempt_receipt']==review['original_attempt_receipt'] and pqa['attempt_receipt_sha256']==review['original_attempt_receipt_sha256']
# Verify every source before allocating evidence; future copy pins are checked against staged bytes.
future={v['public']:v for v in packet['copy_plan'].values()}
for name,h in review['files'].items():
 if name in future:assert sha(Path(future[name]['temporary']))==h
 else:assert sha(root/name)==h,name
baseline=packet['baseline']['prospective_public'];b=root/baseline
assert b.is_file() and not b.is_symlink() and sha(b)==packet['baseline']['sha256']=='440d6e7a976d9a8709d7986d8b75b86279a9fce6ea70a311fe2305a7ff3072d4'
base=json.loads(b.read_text())
assert base['private_state_bodies_copied'] is False and base['calls_charged']==base['calls_started']==0
assert base['failed_continuation_state_sha256']==review['failed_continuation_state_sha256']
assert all(review['files'].get(p)==h for p,h in base['source_references'].items())
review['files'][baseline]=sha(b)
folder=root/fit.CHECK_OUTPUT/'jobs'/review['original_job']['id']
worker=json.loads((folder/'result.json').read_text());attempt=json.loads((root/review['original_attempt_receipt']).read_text())
assert worker['status']=='needs_numerical_review' and attempt['outcome']=='needs_review'
assert sha(folder/'result.json')==review['original_result_sha256']
assert worker['job']==review['original_job'] and attempt['cost']==attempt['start_markers']==0
assert worker['confirmation_outcomes_parsed'] is True and worker['reserved_outcomes']=='sealed'
assert worker['sampler_call_started'] is False
assert review['original_result_status']=='needs_numerical_review'
assert review['primary_aggregate_available'] is False and review['without_crossing_aggregate_available'] is False
assert review['resolved_result'] is review['resolved_result_sha256'] is None
assert review['case1_outcome']=='accepted_unresolved_gap'
assert sha(root/review['prediction_file'])==review['prediction_sha256']
assert len(review['original_attempt_persistent_files'])==11
for p,h in review['original_attempt_persistent_files'].items():assert sha(root/p)==h,p
assert sha(c.plan_path(root,'check'))==review['plan_sha256']==pqa['plan_sha256']
assert sha(folder.with_name(folder.name+'.supervisor.json'))==pqa['supervisor_sha256']
assert review['case0_review_sha256']==sha(root/review['case0_review'])=='4c68821d6f9e48df1e0d28a988c00306594ef9891db340050f01d1baed03bfeb'
(root/public).mkdir(parents=True)
for entry in packet['copy_plan'].values():
 dest=root/entry['public']
 with dest.open('xb') as f:f.write(Path(entry['temporary']).read_bytes())
 assert sha(dest)==entry['sha256']
extra={'runtime-qa.json':pqa_path,'original-audit-helpers.py':root/(m.data.ART+'development-check-diagnostics-v1/case-000/audit-case000.py'),'publish-evidence.py':Path(__file__)}
for name,src in extra.items():
 dest=root/public/name
 with dest.open('xb') as f:f.write(src.read_bytes())
 review['files'][str(dest.relative_to(root))]=sha(dest)
reproduction=dict(scope='Audit-only reproduction using exact accepted source snapshots; no fit or retuning.',requires='Explicit permission for the same closed NCEIlinear case; use a clean temporary workspace because audit outputs are exclusive.',working_directory=str(root),restore_code_snapshots={str(public/'independent-math.py'):'/private/tmp/check-tsunami-development-math.py',str(public/'original-audit-helpers.py'):'/private/tmp/audit-tsunami-development-case000.py',str(public/'independent-case-check.py'):'/private/tmp/check-tsunami-development-five.py',str(public/'audit-linear-failure.py'):'/private/tmp/audit-ms6-linear-failure.py'},command='PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. UV_CACHE_DIR=/private/tmp/tsunami-uv-cache uv run --locked --offline python /private/tmp/audit-ms6-linear-failure.py',no_production_or_state_authority=True)
rp=root/public/'reproduction.json'
with rp.open('xb') as f:f.write(m.encoded(reproduction))
review['files'][str(rp.relative_to(root))]=sha(rp)
review.update(original_worker_result_status=worker['status'],controller_attempt_outcome=attempt['outcome'],production_semantic_replay_status='needs_numerical_review',runtime_review=str(public/'runtime-qa.json'),runtime_review_sha256=sha(root/public/'runtime-qa.json'),runtime_review_status=pqa['status'],baseline_history=baseline,baseline_history_sha256=sha(b),runtime_metadata_independently_accepted_as_failure=True,scientific_scope='Only the closed NCEIlinear runner-up; Tobs/Tcal remain unattempted and unaudited.',scientific_disposition='One event joint score and both aggregate views unavailable numerically;151marginal predictions and13passing raw event scores retained. No model rejection, winner or equivalence claim.')
assert c.STATE not in review['files'] and c.old.STATE not in review['files']
assert len([p for p in review['files'] if p.startswith('context/')])==12
assert str(public/'review-acceptance.json') not in review['files']
for p,h in review['files'].items():assert sha(root/p)==h,p
reviewpath=root/public/'review-acceptance.json'
with reviewpath.open('xb') as f:f.write(m.encoded(review))
assert json.loads(reviewpath.read_text())==review
for p,h in review['files'].items():assert sha(root/p)==h,p
actual=list((root/public).iterdir())
assert len(actual)==9 and all(p.is_file() and not p.is_symlink() for p in actual)
assert all(p==reviewpath or str(p.relative_to(root)) in review['files'] for p in actual)
assert sum(p.stat().st_size for p in actual)<=32*1024**2
print(json.dumps({'review':str(reviewpath.relative_to(root)),'status':review['status'],'sha256':sha(reviewpath),'pins':len(review['files']),'public_physical_files':len(actual),'worker_result_status':worker['status'],'controller_attempt_outcome':attempt['outcome'],'runtime_qa_sha256':review['runtime_review_sha256'],'baseline_sha256':review['baseline_history_sha256'],'aggregate_views_available':False,'prediction_rows_usable':151,'usable_event_scores':13,'event_slots':14,'new_sampler_calls':0,'no_private_state_read_or_pin':True},indent=2))
