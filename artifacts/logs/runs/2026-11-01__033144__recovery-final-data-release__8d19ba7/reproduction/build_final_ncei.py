"""Build the complete, lineage-separated NCEI development observation snapshot."""
from pathlib import Path
import json,subprocess,sys
root=Path.cwd();work=root/'artifacts/generated/ntwc-batch/recovery-execution-v1'
configs=['config/arrival-recovery-ncei-sample-v1.toml']+[f'artifacts/generated/ntwc-batch/recovery-evidence-review-v1/ncei-development-runups-v1/runups-{i:03}.toml' for i in (1,2,3)]+['artifacts/generated/ntwc-batch/recovery-execution-v1/ncei-runups-pagination-001.toml']
runs=['2026-11-01__0258__recovery-ncei-sample-001__c4ed572','2026-11-01__0311__recovery-ncei-runups-001__d83e303','2026-11-01__0313__recovery-ncei-runups-002__d83e303','2026-11-01__0314__recovery-ncei-runups-003__d83e303','2026-11-01__0315__recovery-ncei-pagination-001__d83e303']
args=[sys.executable,'scripts/build_ncei_observations.py']
for config,run in zip(configs,runs,strict=True):args+=['--config',config,'--receipts','artifacts/logs/runs/'+run+'/outputs.json']
args+=['--event-matches','artifacts/generated/ntwc-batch/recovery-evidence-review-v1/event-matches.csv','--events','config/ntwc-archive-batch-v2.toml','--selection','artifacts/generated/ntwc-batch/screen-v1/selection-v2.json','--schema','data/raw/arrival-recovery/evidence-v1/recovery-evidence-f036f966ecdb5a3e.json','--semantics-proof','artifacts/generated/ntwc-batch/time-evidence-review-v1/hazel-discovery/discovery-receipt.json','--semantics-source','data/raw/arrival-recovery/ncei-semantics-v1/main.4768c122.js','--output',sys.argv[1] if len(sys.argv)>1 else 'data/processed/ncei-arrivals/foundation-v1']
command=work/'ncei-final-build-command.json'
if not command.exists():command.write_text(json.dumps(args[1:],indent=2)+'\n')
subprocess.run(args,check=True,cwd=root)
