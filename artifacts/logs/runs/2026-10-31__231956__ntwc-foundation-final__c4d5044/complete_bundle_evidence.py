"""Preserve executed review tools, checksum the complete run, and verify local MLflow copies."""
from pathlib import Path
from urllib.parse import urlparse,unquote
from datetime import datetime,UTC
from importlib.metadata import distributions
import hashlib,json,os,platform,shutil,sys
root=Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
result=json.loads(Path('/private/tmp/ntwc-final-run-result.json').read_text());bundle=root/result['bundle'];run_id=result['mlflow_run_id']
base=root/'artifacts/generated/ntwc-batch';acceptance=json.loads((base/'foundation-final-root-acceptance-v1.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def copy_exact(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():assert sha(src)==sha(dst),dst
    else:shutil.copyfile(src,dst)
for p in sorted((base/'final-review-tools-v1').glob('*.py')):copy_exact(p,bundle/'review-tools'/p.name)
copy_exact(Path('/private/tmp/record_ntwc_foundation_final.py'),bundle/'review-tools/record_ntwc_foundation_final.py')
copy_exact(Path(__file__),bundle/'complete_bundle_evidence.py')
copy_exact(Path('/private/tmp/ntwc-final-evidence-preflight.json'),bundle/'review-receipts/final-writer-preflight.json')
for path in acceptance['review_receipts']:
    p=root/path;copy_exact(p,bundle/'review-receipts'/p.name)
for name in ['foundation-final-root-acceptance-v1.json','foundation-final-independent-review-v1.json']:
    p=base/name;copy_exact(p,bundle/'review-receipts'/name)
environment={'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'packages':sorted([{'name':d.metadata['Name'],'version':d.version} for d in distributions() if d.metadata.get('Name')],key=lambda x:x['name'].casefold()),'project_environment_sha256':{str(p.relative_to(root)):sha(p) for p in [root/'pyproject.toml',root/'uv.lock',root/'package.json',root/'package-lock.json'] if p.exists()}}
(bundle/'environment.json').write_text(json.dumps(environment,indent=2,sort_keys=True)+'\n')
(bundle/'REPRODUCE.md').write_text('''# Final data-foundation evidence

This run records the completed finite data acquisition and descriptive exports.
It does not certify physical onsets, deployments, model eligibility, or publication
rights. Data versions and full file inventories are in outputs.json; input and
code hashes are in inputs.json and the copied independent acceptance receipts.
Raw data remain in the repository's ignored cache, identified by path, size and
checksum in acquisition-inventory.json. Copy that cache and the pinned code/config
files with the project when moving this run; this compact bundle does not embed
all scientific data.

Run commands from the project root using its Python environment. config.json
records the consolidation arguments; the data guide gives waveform/catalog
build commands. Always rebuild into a new directory. Review tools are byte-for-byte
copies of the executed independent checks. Some preserve the original checkout
or temporary replay paths; inspect their arguments before using a relocated
checkout. Do not rerun evidence writers over frozen receipts. For waveform row
conservation, supply the final waveform folder, a fresh replay folder and a new
review-receipt path. The catalog verifier takes the catalog folder as its argument.
The saved pytest module imports its sibling record_ntwc_foundation_final.py.

bundle-manifest.json hashes every other file in this run, including this guide,
review tools, review receipts and environment metadata. Its own hash is recorded
by the separate final-bundle-mlflow-review-v1.json receipt, also logged to the same
MLflow run under checks/final-bundle-readback. No late file additions are omitted
from MLflow: the entire completed bundle is re-logged under portable-run and
independently compared to the local artifact-store copy.
''')
manifest={'schema_version':1,'run_id':result['run_id'],'mlflow_run_id':run_id,'scope':'Every file in completed portable run except this manifest; original data remain bound by separate inventories.','output_sha256':{str(p.relative_to(bundle)):sha(p) for p in sorted(bundle.rglob('*')) if p.is_file() and p.name!='bundle-manifest.json'}}
(bundle/'bundle-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
os.environ.setdefault('MLFLOW_ALLOW_FILE_STORE','true');os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT','true')
from mlflow import MlflowClient
client=MlflowClient(tracking_uri=(root/'.mlflow/mlruns').as_uri());run=client.get_run(run_id)
assert run.info.status=='FINISHED' and run.data.metrics['waves.source_rows']==3688140
assert run.data.metrics['acquisition.paper_acquisition_runs']==31
client.log_artifacts(run_id,str(bundle),artifact_path='portable-run')
uri=urlparse(client.get_run(run_id).info.artifact_uri);assert uri.scheme=='file'
artifact_root=Path(unquote(uri.path));assert artifact_root.is_relative_to(root/'.mlflow/mlruns')
all_files={str(p.relative_to(bundle)):sha(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
assert set(all_files)==set(manifest['output_sha256'])|{'bundle-manifest.json'}
for rel,digest in all_files.items():assert sha(artifact_root/'portable-run'/rel)==digest,rel
for role,primary in [('crosswalk','connectivity.json'),('design','summary.json'),('corpus','summary.json'),('waves','manifest.json'),('catalog','manifest.json'),('audit','manifest.json'),('comparison','manifest.json'),('diagnostics','manifest.json')]:
    output=json.loads((bundle/'outputs.json').read_text())[role]
    group='frozen' if role in {'audit','comparison','diagnostics'} else 'final'
    assert sha(root/output['directory']/primary)==sha(artifact_root/group/role/primary)
receipt={'status':'pass','reviewer':'root independent completed-bundle hashes and local MLflow artifact-store readback','timestamp_utc':datetime.now(UTC).isoformat(),'bundle':result['bundle'],'bundle_manifest_sha256':sha(bundle/'bundle-manifest.json'),'bundle_files_including_manifest':len(all_files),'mlflow_run_id':run_id,'mlflow_status':client.get_run(run_id).info.status,'mlflow_artifacts_byte_identical':len(all_files),'unique_role_manifest_copies_verified':8,'independent_review_sha256':sha(base/'foundation-final-independent-review-v1.json'),'checks':['Every final run file hashed, including preserved executed review scripts, independent receipts and environment','All completed portable-run files match local MLflow artifacts byte-for-byte after supplemental logging','All eight final/frozen role manifests match source package primary manifests','Run status FINISHED and key acquisition/row metrics match accepted data']}
receipt_path=base/'final-bundle-mlflow-review-v1.json';assert not receipt_path.exists();receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
client.log_artifact(run_id,str(receipt_path),artifact_path='checks/final-bundle-readback')
assert sha(receipt_path)==sha(artifact_root/'checks/final-bundle-readback'/receipt_path.name)
print(json.dumps(receipt,indent=2))
