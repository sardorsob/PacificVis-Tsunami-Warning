"""Extend the frozen source ledger without changing any original record or pin."""
from pathlib import Path
import csv,json,hashlib,sys
sys.path.insert(0,str(Path.cwd()))
from scripts.build_paper_manifest import build
from pipeline.provenance import REQUIRED_COLUMNS,validate_manifest
root=Path.cwd();baseline=root/'artifacts/provenance/paper-source-manifest.csv';old=list(csv.DictReader(baseline.open()));run_names={a['run'] for row in old for a in json.loads(row['notes'])['attempts']}
new_runs=[]
for p in (root/'artifacts/logs/runs').glob('2026-11-01*'):
 if not (p/'config.json').exists():continue
 d=json.loads((p/'config.json').read_text())
 if 'toml' in d:new_runs.append(p)
runs=sorted({root/'artifacts/logs/runs'/r for r in run_names}|set(new_runs));rows=build(root,runs);lookup={r['source_id']:r for r in rows}
for row in old:assert lookup[row['source_id']]==row,('original record changed',row['source_id'])
out=root/'artifacts/provenance/paper-source-manifest-v2.csv';assert not out.exists()
with out.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=REQUIRED_COLUMNS);w.writeheader();w.writerows(rows)
assert validate_manifest(out).records==len(rows)
raw={r['local_path']:r for r in rows if r['local_path']!='not-downloaded'}
receipt={'status':'PASS','sources':len(rows),'unchanged_frozen_records':len(old),'acquisition_runs':len(runs),'new_acquisition_runs':len(new_runs),'distinct_retained_paths':len(raw),'retained_raw_bytes':sum((root/p).stat().st_size for p in raw),'source_ledger_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'frozen_ledger_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest(),'runs':[str(p.relative_to(root)) for p in runs],'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(root/'artifacts/generated/ntwc-batch/recovery-execution-v1/source-ledger-v2-check.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print({k:v for k,v in receipt.items() if k!='runs'})
