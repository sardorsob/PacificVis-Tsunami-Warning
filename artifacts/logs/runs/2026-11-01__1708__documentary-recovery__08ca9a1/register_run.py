"""Register reproducible documentary acquisition/processing; no model is fitted."""
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

import mlflow

root=Path(sys.argv[1]).resolve()
run=Path(__file__).resolve().parent
product=root/'data/processed/arrival-evidence/documentary-v1'
qa=root/'artifacts/generated/ntwc-batch/documentary-recovery-v1/checker/scientific-qa.json'
summary=json.loads((product/'summary.json').read_text())
controls=[json.loads(p.read_text()) for p in (root/'artifacts/generated/ntwc-batch/documentary-recovery-v1').glob('*-control.json')]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):
    (run/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
shutil.copyfile(qa,run/'scientific-qa.json')
meta={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
      'git_sha_at_registration':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
      'working_tree_at_registration':'dirty; final verified commit is tagged after landing',
      'lane':'paper','model_fitted':False,'disposition':'accepted_documentary_supplement',
      'mlflow_experiment':'ntwc-arrival-foundation'}
config={'max_http_attempts':340,'max_additional_bytes':100000000,'max_object_bytes':5000000,
        'min_noaa_interval_seconds':1,'source_selection':'adaptive source evidence; frozen development roles',
        'original_pair_replacement':False,'new_pair_approval':False,
        'extractors':sorted({d['extractor'] for d in json.loads((root/'artifacts/generated/ntwc-batch/documentary-recovery-v1/extracted-8.json').read_text())})}
metrics={k:v for k,v in summary.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
metrics.update(http_attempts=sum(x['requests'] for x in controls),
               received_body_bytes=sum(x['spent_bytes'] for x in controls),
               python_tests_passed=803,frontend_tests_passed=178,protected_hashes_unchanged=14512,
               source_ledger_records=2712,source_message_versions_retained=108)
write('meta.json',meta);write('config.json',config);write('metrics.json',metrics)
write('inputs.json',{'product_inputs_sha256':digest(product/'inputs.json'),
                    'product_inputs_path':str((product/'inputs.json').relative_to(root)),
                    'previous_release':'arrival-evidence/foundation-v1',
                    'ledger_v3_sha256':digest(root/'artifacts/provenance/paper-source-manifest-v3.csv')})
write('outputs.json',{'product_manifest_sha256':digest(product/'manifest.json'),
                     'product_manifest_path':str((product/'manifest.json').relative_to(root)),
                     'source_ledger_v4_sha256':digest(root/'artifacts/provenance/paper-source-manifest-v4.csv'),
                     'scientific_qa_sha256':digest(qa)})
write('seeds.json',{'randomness':'none; deterministic documentary extraction'})
(run/'notes.md').write_text('''# Documentary tsunami timing supplement

Original warning-center searches were checked for all 57 development entries on
56 event dates. Wider date windows recovered messages missed by shorter searches;
product-code filtering was unreliable. All 108 discovered original message versions
were retained. NOAA service assessments, ITIC collections and published first-wave
tables supplied additional records. Failed sources and unrelated current-event
responses were retained as dispositions, with no observation promotion.

The supplement contains 1,287 distinct dated forecast instances across 75 products
and nine events, plus 22 dated first-wave observations and 19 additional clocks with
unresolved calendar. Multiple bulletin copies, versions, issuers and time meanings
remain distinct. The 388 original pairs and 789 unresolved pairs are unchanged;
592 normalized-label links are candidates, not approved new pairs. Five observed
clock conflicts are preserved. All model approvals remain false.

Independent source checks and exact replay pass. The full gate passed 803 Python
and 178 frontend tests, static checks and build. All 14,512 protected hashes remain
unchanged. Current archive/source leads were exhausted for this pass; inaccessible
historical records, target/identity review and expert waveform picks remain possible
future work. No global archival-exhaustion claim is made. See docs/data/multi-event.md.
''')
mlflow.set_tracking_uri((root/'.mlflow/mlruns').as_uri())
mlflow.set_experiment('ntwc-arrival-foundation')
with mlflow.start_run(run_name=run.name) as active:
    mlflow.log_params(config)
    mlflow.log_metrics(metrics)
    mlflow.set_tags({'disposition':'accepted_documentary_supplement','model_fitted':'false',
                     'git_sha_at_registration':meta['git_sha_at_registration'],
                     'data_manifest_sha256':digest(product/'manifest.json'),
                     'role_freeze':'unchanged','remote_push':'false'})
    for path in sorted(run.iterdir()):
        if path.is_file():mlflow.log_artifact(str(path))
    mlflow.log_artifact(str(product/'manifest.json'),artifact_path='product')
    mlflow.log_artifact(str(product/'summary.json'),artifact_path='product')
    write('mlflow.json',{'run_id':active.info.run_id,'tracking_uri':'project-local .mlflow/mlruns'})
print((run/'mlflow.json').read_text())
