"""Preserve small portable replay/check tools and verify the local MLflow artifact copy."""
from pathlib import Path
from urllib.parse import urlparse,unquote
import hashlib,json,shutil,platform
import mlflow
root=Path.cwd();work=root/'artifacts/generated/ntwc-batch/recovery-execution-v1';index=json.loads((work/'mlflow-stage-index.json').read_text());record=index['recovery-final-data-release'];folder=root/record['portable_run'];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
helpers=['complete_release_bundle.py','record_recovery_stages.py','build_final_ncei.py','ncei-final-build-command.json','check_waveform_v5.py','check_ncei_metadata_tranche.py','check_ncei_runup_tranche.py','profile_recovered_data.py','verify_frozen_products.py','build_source_ledger_v2.py','mlflow-stage-index.json']
for name in helpers:
 d=folder/'reproduction'/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(work/name,d)
reviews={
 'event-matches.csv':root/'artifacts/generated/ntwc-batch/recovery-evidence-review-v1/event-matches.csv',
 'field-semantics.json':root/'artifacts/generated/ntwc-batch/time-evidence-review-v1/hazel-discovery/discovery-receipt.json',
 'ncei-final-raw-review.json':root/'artifacts/generated/ntwc-batch/recovery-evidence-review-v1/final-raw-review.json',
 'ncei-final-product-checker.json':root/'artifacts/generated/ntwc-batch/recovery-evidence-review-v1/final-product-checker-receipt.json',
 'recovery-design-checker.json':root/'artifacts/generated/ntwc-batch/recovery-design-review-v1/review.json',
}
for name,path in reviews.items():
 d=folder/'source-reviews'/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,d)
for name,source in {'pytest-first-failed.log':'/private/tmp/tsunami-recovery-final-pytest.log','pytest-final-passed.log':'/private/tmp/tsunami-recovery-final-pytest-rerun.log','frontend-check-passed.log':'/private/tmp/tsunami-recovery-final-frontend.log','clock-isolation-regression-red.log':'/private/tmp/tsunami-spacing-red.log','graphify-update.log':'/private/tmp/tsunami-recovery-graphify.log'}.items():
 d=folder/'verification-logs'/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,d)
shutil.copyfile(work/'final-verification.json',folder/'verification.json')
(folder/'environment.json').write_text(json.dumps({'python':platform.python_version(),'mlflow':mlflow.__version__,'tracking_uri':'.mlflow/mlruns','MLFLOW_ALLOW_FILE_STORE':'true','new_services_or_dependency_upgrades':False},indent=2)+'\n')
(folder/'REPRODUCE.md').write_text('''# Recovered tsunami data release

This bundle pins the completed acquisition, extraction, native samples and
candidate reported targets. It does not certify physical onsets or a fitted model.
See `docs/data/multi-event.md` for table definitions, current products and limits.

Use the project Python environment from the repository root. Required scientific
source bytes and generated inputs remain in the ignored local data cache. Raw
redistribution is not authorized by this bundle. Original request contracts are
saved verbatim in each acquisition run's `config.json`; their body/query/hash and
outcome records are in `inputs.json` and `outputs.json`. No credentials are needed
for the new public NOAA sources.

`reproduction/ncei-final-build-command.json` saves the exact NCEI CLI argument
array. `reproduction/build_final_ncei.py NEW_OUTPUT_DIRECTORY` rebuilds from its
pinned local receipts; the source-review copies preserve the reviewed event map
and official field-definition locators. Use a new output directory; never edit
existing scientific products. The other replay and profile tools preserve source
conservation, frozen-product checks and denominators. The earlier corpus/waveform
and consumer builders are documented in the data guide and their pinned manifests.

`verification.json` records the final gate. The first full-suite log captures a
test-only global-clock mock failure; the fail-first regression and independent
review are retained. A module-local test clock fixed it without production or
data changes. The final full suite passed 761 tests. Frontend checks passed 178
tests, type checking and build. Source ledgers validated 19/2253/2388 records.

`reproduction/mlflow-stage-index.json` maps ten logical recovery stages to their
portable bundles and project-local MLflow IDs. Registration occurs after review;
original acquisition/build timestamps remain in their receipts. File-store use
requires `MLFLOW_ALLOW_FILE_STORE=true`. No tracking server or migration was added.
''')
manifest={str(p.relative_to(folder)):sha(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='bundle-manifest.json'}
(folder/'bundle-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
mlflow.set_tracking_uri((root/'.mlflow/mlruns').as_uri())
with mlflow.start_run(run_id=record['mlflow_run_id']):mlflow.log_artifacts(str(folder),artifact_path='portable-run')
client=mlflow.tracking.MlflowClient();run=client.get_run(record['mlflow_run_id']);assert run.data.metrics['python_tests_passed']==761
uri=urlparse(run.info.artifact_uri);assert uri.scheme=='file';uploaded=Path(unquote(uri.path))/'portable-run'
for path in folder.rglob('*'):
 if path.is_file():assert sha(path)==sha(uploaded/path.relative_to(folder)),path.name
receipt={'status':'PASS','portable_run':record['portable_run'],'mlflow_run_id':record['mlflow_run_id'],'bundle_files':sum(p.is_file() for p in folder.rglob('*')),'bundle_manifest_sha256':sha(folder/'bundle-manifest.json'),'all_uploaded_artifacts_byte_identical':True}
(work/'final-run-readback.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(receipt)
