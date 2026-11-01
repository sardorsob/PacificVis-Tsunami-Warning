"""Register the accepted source-process investigation in project-local MLflow."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import mlflow

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from analysis.arrival.evidence import sha256

run = Path(__file__).resolve().parent
product = root/'data/processed/arrival-evidence/source-process-v1'
summary = json.loads((product/'summary.json').read_text())
acquisition = json.loads((run/'acquisition-summary.json').read_text())
qa = json.loads((run/'scientific-qa.json').read_text())
assert qa['status']=='PASS'
def write(name, value):
    (run/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
meta = {'timestamp_utc':datetime.now(UTC).isoformat(),'lane':'paper',
        'git_sha_at_registration':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        'disposition':'accepted_source_process_supplement','model_fitted':False,
        'tracking':'project-local .mlflow/mlruns; no remote action',
        'working_tree':'final scientific receipts pending local commit'}
config = {'max_http_attempts':160,'max_additional_bytes':100000000,
          'max_object_bytes':10000000,'max_attempts_per_exact_url':3,
          'min_noaa_interval_seconds':1,'source_scope':'frozen development cohort',
          'original_label_replacement':False,'pair_approval':False,
          'attribution':'direct field reason counted separately from policy and context'}
metrics = {k:v for k,v in summary.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
metrics.update(http_acquisition_attempts=acquisition['http_attempts'],
               response_bytes=acquisition['retained_bytes'],raw_snapshots=21,
               source_ledger_records=2738,python_tests_passed=815,
               frontend_tests_passed=178,protected_hashes_unchanged=14512,
               independent_adversaries_rejected=11)
write('meta.json',meta);write('config.json',config);write('metrics.json',metrics)
write('inputs.json',{'product_input_pins_path':str((product/'inputs.json').relative_to(root)),
                    'product_inputs_sha256':sha256(product/'inputs.json'),
                    'curation_path':'config/arrival-source-process-review-v1.json',
                    'curation_sha256':sha256(root/'config/arrival-source-process-review-v1.json'),
                    'parent_releases':['arrival-evidence/foundation-v1','arrival-evidence/documentary-v1']})
write('outputs.json',{'product_manifest_path':str((product/'manifest.json').relative_to(root)),
                     'product_manifest_sha256':sha256(product/'manifest.json'),
                     'ledger_path':'artifacts/provenance/paper-source-manifest-v5.csv',
                     'ledger_sha256':sha256(root/'artifacts/provenance/paper-source-manifest-v5.csv'),
                     'scientific_qa_sha256':sha256(run/'scientific-qa.json')})
write('seeds.json',{'randomness':'none; deterministic reviewed evidence accounting'})
(run/'notes.md').write_text('''# Source-process evidence supplement

The development-only source census and original technical documents establish
conditional reporting, product selection/lifecycle, sampling versus telemetry,
noise-limited onset interpretation, station damage/restoration, archive-transfer
failures and provider errors. Evidence strength, station/time/field applicability
and unknown technical causes remain explicit. See docs/data/source-process.md.

Four absent NTWC observation fields have direct near-arrival-gap support; three
source-absence rows have every absent field supported. Policy context covers all
289 absent observations but is not an individual cause. Four NCEI definition
comparisons and one approximate Tonga statement remain unapproved. Starodubsk's
noise-related arrival limitation uses the separate documentary denominator.

Original 388 pairs / 789 unresolved rows are unchanged. No model was fitted or
held-out evaluation outcomes parsed. Prior diagnostic metadata exposure is not
reset. Source-family saturation is not a claim of global archival exhaustion.
Remaining useful evidence includes original operator logs, failure start/end
bounds, archive-transfer records and reviewed first-arrival definitions.

Independent source/count review, exact 12-file replay, eleven adversarial
curation checks, 815 Python and 178 frontend tests, static checks, build and
provenance pass. All 14,512 protected hashes and accepted parent manifests verify.
Twenty-one new original snapshots total 28,450,010 bytes. Ledger v5 preserves every
v4 row and adds 26 source identities. Raw/processed products stay local; contracts,
scientific curation and reproduction/QA evidence are committed. No push or
personal archive synchronization is included.
''')
mlflow.set_tracking_uri((root/'.mlflow/mlruns').as_uri())
mlflow.set_experiment('ntwc-arrival-foundation')
with mlflow.start_run(run_name=run.name) as active:
    mlflow.log_params(config);mlflow.log_metrics(metrics)
    mlflow.set_tags({'disposition':meta['disposition'],'model_fitted':'false',
                     'git_sha_at_registration':meta['git_sha_at_registration'],
                     'data_manifest_sha256':sha256(product/'manifest.json'),
                     'selection_decision':'accept evidence supplement; reject automatic primary-time promotion',
                     'role_freeze':'unchanged','remote_push':'false'})
    for p in sorted(run.iterdir()):
        if p.is_file():mlflow.log_artifact(str(p))
    mlflow.log_artifact(str(product/'summary.json'),artifact_path='product')
    mlflow.log_artifact(str(product/'manifest.json'),artifact_path='product')
    mlflow.log_artifact(str(root/'docs/data/source-process.md'),artifact_path='report')
    write('mlflow.json',{'run_id':active.info.run_id,'tracking_uri':'project-local .mlflow/mlruns'})
print((run/'mlflow.json').read_text())
