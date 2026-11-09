"""Authorized current-path scientific gap and lossless stop-marker reconciliation.

Never applies a journal disposition, launches a child, creates a phase summary,
rewrites a producer, reads private state bodies, or changes source/Gates/Git.
"""
from pathlib import Path
import hashlib,json
from scripts import run_arrival_development_journal as J
from analysis.arrival import model_development_fit as fit
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads((root/p).read_text())
jobid='dev-tcal-pooled-runner-up-check';gatepath=J.gate_path('check');gate=read(gatepath)
assert sha(root/gatepath)=='b90d8a903061e27ebf54d97d444f325838f8d1275cf572954eaff2f36fb9ac20'
sourcefiles={**gate['files'],gatepath:sha(root/gatepath)};assert len(sourcefiles)==14900
job=next(j for j in gate['jobs'] if j['id']==jobid);gap=J.gap_review_path(root,job).parent;gaprel=str(gap.relative_to(root));evidence=gap/'independent-checks-v1'
assert not J.gap_review_path(root,job).exists() and not evidence.exists()
paths={
 'runtime-before-archive.json':('/private/tmp/tsunami-journal-four-check-runtime-qa.json','90f324a058a941d3a229bb03e28b21993f2c1108cd6d24b25eb67a90a5e15766'),
 'runtime-after-archive.json':('/private/tmp/tsunami-journal-stop-archive-runtime-qa.json','390df075aded69d08a5bee2bce74da23947877372f65e5376f09c90a7a768c10'),
 'NTWC-scientific-review.json':('/private/tmp/tsunami-development-NTWC-final-independent.json','14bb3b1acc5ed2e13ece23e4587501d7d291482bacb5e59024c6fe2948b8fd21'),
 'Tobs-scientific-review.json':('/private/tmp/tsunami-development-Tobs-sealed-independent.json','cafc57319695e36c577344f82896337f1fa10d6be2ad97989d6da28ba28dd33f'),
 'archive-route-proof-code.txt':('/private/tmp/test_development_journal_archive_route.py','6be32c06fb095245ca817be19da0368d430bb547836da45b90bb824be68b870f'),
}
for p,h in paths.values():assert sha(Path(p))==h,p
before=json.loads(Path(paths['runtime-before-archive.json'][0]).read_text());after=json.loads(Path(paths['runtime-after-archive.json'][0]).read_text());science=json.loads(Path(paths['NTWC-scientific-review.json'][0]).read_text());tobs=json.loads(Path(paths['Tobs-scientific-review.json'][0]).read_text())
assert before['independent_checker'] and after['independent_checker'] and len(before['files'])==53 and len(after['files'])==57
assert before['accepted_receipts']==after['accepted_attempts']==3 and before['needs_review_receipts']==after['needs_review_attempts']==1
assert after['sampler_calls_charged']==after['sampler_calls_started']==0 and after['all_five_leases_absent']
assert after['original_fifty_three_persistent_files_unchanged'] and after['original_failure_root_absent']
manifestpath=str((gap/'controller-stop-archive.json').relative_to(root));manifest=read(manifestpath)
assert sha(root/manifestpath)==after['archive_manifest_sha256']=='7a80228a3d57063a4ccf040f19c5c04f021941c7887f9258dc0b1f9b24a6cf71'
assert manifest['archive_route_probe_sha256']==paths['archive-route-proof-code.txt'][1]
assert manifest['original_evidence_commit']=='b11c0eca7739452e4a4871a8caf3637ba47a0b60'
assert not (root/manifest['original_root']).exists() and not (root/manifest['original_root']).is_symlink()
assert len(manifest['files'])==3 and len(manifest['original_locations_history_only'])==3
for move in after['historical_move_map']:
 assert manifest['files'][move['current_path']]==manifest['original_locations_history_only'][move['original_path_history_only']]==move['sha256']
 assert sha(root/move['current_path'])==move['sha256']
# Build closure from all four quantitative/provenance records plus P's complete persistent map.
files=dict(sourcefiles)
def merge(mapping):
 for p,h in mapping.items():
  assert p not in files or files[p]==h,p
  files[p]=h
merge(before['files']);merge(after['files']);merge(manifest['files']);files[manifestpath]=sha(root/manifestpath)
for result in science['Tcal'].values():merge(result['files'])
for result in tobs['jobs'].values():merge(result['files'])
for proof in science['Tobs_full_artifact_proofs'].values():merge(proof['files'])
oldpaths=set(manifest['original_locations_history_only']);assert not oldpaths & set(files)
assert J.old.STATE not in files and J.c2.STATE not in files
assert {p:h for p,h in files.items() if p.startswith('context/')}=={p:h for p,h in sourcefiles.items() if p.startswith('context/')}
for p,h in files.items():assert sha(root/p)==h,p
failed=science['Tcal_pooled_failure'];assert failed['event_id']=='usb000sk6k' and failed['records']==2
assert failed['numerical_failures']==['chain_log_normalizer_disagreement'] and failed['normalized_chain_range']>failed['normalized_chain_range_threshold']==.005
last=science['Tcal'][jobid];assert last['checks']['prediction_rows']==last['checks']['prediction_rows_passed']==13 and last['checks']['usable_event_scores']==4
folder=fit.case_paths(root,job)[0];resultpath=str((folder/'result.json').relative_to(root));prediction=str((folder/'held-out-record-predictions.csv').relative_to(root));attemptpath=J.attempt_path(root,'check',job);attemptname=str(attemptpath.relative_to(root));attempt=read(attemptname)
assert sha(attemptpath)=='7b0e0174a03894a6bf4beb91970534305904d6481c3cc55ff0c59798597c26d7'
result=read(resultpath);events=read(str((folder/'event-results.json').relative_to(root)))
assert result['status']=='needs_numerical_review' and result['scoring_performed'] is True and result['sampler_call_started'] is False
assert result['prediction_rows']==13 and all(e['predictions']['status']=='computed_pending_review' for e in events['events'])
assert attempt['outcome']=='needs_review' and attempt['gap_eligible'] is True and attempt['cost']==attempt['start_markers']==0
assert all(read(str(J.attempt_path(root,'check',j).relative_to(root)))['outcome']=='accepted' for j in gate['jobs'][:-1])
evidence.mkdir()
# All new records live only inside the predeclared final check-review folder.
for name,(src,h) in paths.items():
 dest=evidence/name
 with dest.open('xb') as f:f.write(Path(src).read_bytes())
 assert sha(dest)==h;files[str(dest.relative_to(root))]=h
code_sources={
 'independent-math.py':Path('/private/tmp/check-tsunami-development-math.py'),
 'independent-case-check.py':Path('/private/tmp/check-tsunami-development-five.py'),
 'journal-target-audit.py':Path('/private/tmp/check-ms6-journal-NTWC.py'),
 'audit-two-sealed-Tobs.py':Path('/private/tmp/audit-ms6-Tobs-sealed.py'),
 'audit-final-NTWC.py':Path('/private/tmp/audit-ms6-NTWC-final-closed.py'),
 'original-audit-helpers.py':root/(J.data.ART+'development-check-diagnostics-v1/case-000/audit-case000.py'),
 'publish-evidence.py':Path(__file__),
}
for name,src in code_sources.items():
 dest=evidence/name
 with dest.open('xb') as f:f.write(src.read_bytes())
 files[str(dest.relative_to(root))]=sha(dest)
recipe=dict(scope='Only four closed NTWC producers; no sampler, new integration, private-state access or model retuning.',Root_authorized_actual_notice_required=True,working_directory=str(root),restore_exact_sources_to_clean_temporary_workspace={str((evidence/name).relative_to(root)):str(src) for name,src in code_sources.items() if name not in {'publish-evidence.py','original-audit-helpers.py'}},original_helpers_restore={str((evidence/'original-audit-helpers.py').relative_to(root)):'/private/tmp/audit-tsunami-development-case000.py'},order=['Restore pure helper/math sources to their literal temporary paths.','Run audit-two-sealed-Tobs.py only with explicit corresponding target-scoped closed notice.','Run audit-final-NTWC.py after all four closed; uses immutable successful fit.case_artifacts and reuses original Tobs arithmetic.','Existing output paths are exclusive: use an isolated clean temporary workspace for reproduction.'],scientific_evaluation_original_artifacts_never_rewritten=True)
rp=evidence/'reproduction.json'
with rp.open('xb') as f:f.write(J.numerical.encoded(recipe))
files[str(rp.relative_to(root))]=sha(rp)
reconciliation=dict(schema_version=1,status='accepted_frozen_development_controller_stop_marker_reconciliation',independent_checker=True,checker='/root/sumatra_path_oracles',scope='Lossless classification and relocation of exactly three invocation-stop blockers only; no worker or genuine runtime failure waiver.',pending_maker_manifest=manifestpath,pending_maker_manifest_sha256=sha(root/manifestpath),pending_maker_manifest_unchanged=True,original_locations_history_only=manifest['original_locations_history_only'],current_archived_marker_files=manifest['files'],original_evidence_commit=manifest['original_evidence_commit'],classification=before['controller_failure_classification'],postarchive_independent_classification=after['manual_classification'],three_successful_worker_statuses_and_receipts_unchanged=True,fourth_failed_worker_status_and_receipt_unchanged=True,allocations_unchanged=True,sampler_calls_charged=0,sampler_calls_started=0,private_state_hashes_history_only=after['states_conserved'],private_state_bodies_read_or_copied=False,source_and_old_authority_unchanged=True,no_worker_failure_waiver=True,no_scientific_gap_or_model_rejection_inferred_by_marker_reconciliation=True,no_run_or_child_or_summary_or_disposition_authorized_or_created=True,runtime_before_evidence=str((evidence/'runtime-before-archive.json').relative_to(root)),runtime_after_evidence=str((evidence/'runtime-after-archive.json').relative_to(root)),route_proof_code=str((evidence/'archive-route-proof-code.txt').relative_to(root)),synthetic_route_evidence='Three previously independently reviewed synthetic cases passed; zero-child CHECK application and conserved0→6→9 phase ceilings. No new execution performed by this review.',files=dict(files))
reconpath=gap/'controller-stop-reconciliation-review.json'
for p,h in files.items():assert sha(root/p)==h,p
with reconpath.open('xb') as f:f.write(J.numerical.encoded(reconciliation))
files[str(reconpath.relative_to(root))]=sha(reconpath)
review=dict(schema_version=1,status='accepted_frozen_development_check_numerical_gap',independent_checker=True,checker='/root/sumatra_path_oracles',original_job=job,failure_kind='numerical_precision_only',fully_computed_same_source=True,confirmation_outcomes_parsed=True,development_check_previously_inspected=True,reserved_outcomes='sealed',reserved_outcomes_parsed=False,primary_aggregate_available=False,without_crossing_aggregate_available=False,resolved_result=None,resolved_result_sha256=None,specification_freeze_sha256=files[J.data.FREEZE],attempt=attemptname,attempt_sha256=sha(attemptpath),prediction_file=prediction,prediction_sha256=files[prediction],prediction_rows_precision_passed=13,original_result=resultpath,original_result_sha256=files[resultpath],original_worker_result_status='needs_numerical_review',controller_attempt_outcome='needs_review',event_score_slots=5,usable_raw_event_scores=4,unresolved_event=failed,native_observation_log_jacobian=0,aggregate_views_withheld=['all5events','without_crossing5events'],raw_computed_scores_and_arrays_retained=True,no_failed_score_or_aggregate_promoted=True,no_threshold_softening_or_new_integration_or_refit=True,no_retuning=True,no_model_or_prior_or_data_change=True,model_rejected=False,Tcal_winner_claimed=False,equivalence_claimed=False,new_sampler_calls=0,marker_reconciliation_review=str(reconpath.relative_to(root)),marker_reconciliation_review_sha256=sha(reconpath),current_archive_manifest=manifestpath,current_archive_manifest_sha256=sha(root/manifestpath),historical_marker_locations_metadata_only=manifest['original_locations_history_only'],all_four_scientific_evidence=str((evidence/'NTWC-scientific-review.json').relative_to(root)),prior_Tobs_scientific_evidence=str((evidence/'Tobs-scientific-review.json').relative_to(root)),original_state_sha256=gate['original_state_sha256'],failed_continuation_state_sha256=gate['failed_continuation_state_sha256'],private_state_body_read_or_pinned=False,case0_review=J.CASE0,case0_review_sha256=files[J.CASE0],case1_review=J.CASE1,case1_review_sha256=files[J.CASE1],completed_six_check_review_created=False,journal_disposition_applied=False,phase_summary_created=False,child_launched=False,scientific_scope='The pooled Tcal alternative has one unresolved JOINT score and both aggregates unavailable, while all13 marginal predictions remain numerically usable. This does not rank selected versus alternative forms.',files=files)
assert not oldpaths & set(review['files']) and J.old.STATE not in files and J.c2.STATE not in files
assert str(J.gap_review_path(root,job).relative_to(root)) not in files
for p,h in files.items():assert sha(root/p)==h,p
reviewpath=J.gap_review_path(root,job)
with reviewpath.open('xb') as f:f.write(J.numerical.encoded(review))
# Actual frozen J metadata acceptance only; no journal application/summary/child.
a=dict(phase='check',files=sourcefiles,gate=gate,worker=fit)
record={**attempt,'receipt_sha256':sha(attemptpath)}
accepted_name,accepted_review,accepted_files=J._gap(root,a,job,record)
assert accepted_name==str(reviewpath.relative_to(root)) and accepted_review==review
for p,h in accepted_files.items():assert sha(root/p)==h,p
allphysical=[p for p in gap.rglob('*') if p.is_file()]
assert all(p.resolve()==p and not p.is_symlink() for p in gap.rglob('*'))
assert all(str(p.relative_to(root)) in accepted_files for p in allphysical)
assert sum(p.stat().st_size for p in allphysical)<32*1024**2
assert not (root/manifest['original_root']).exists()
assert not J.disposition_path(root,job).exists() and not J.summary_path(root,'check').exists()
print(json.dumps(dict(gap_review=accepted_name,status=review['status'],gap_sha256=sha(reviewpath),reconciliation_review=str(reconpath.relative_to(root)),reconciliation_sha256=sha(reconpath),gap_files=len(files),accepted_closure_pins=len(accepted_files),current_archive_manifest_sha256=sha(root/manifestpath),all_physical_gap_files=len(allphysical),physical_gap_bytes=sum(p.stat().st_size for p in allphysical),exact_J_gap_metadata_proof='PASS',old_marker_live_pins=0,worker_and_attempt_statuses_preserved=True,new_sampler_calls=0,child_launched=False,journal_applied=False,summary_created=False),indent=2),flush=True)
