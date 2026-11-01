from pathlib import Path
import base64
import hashlib
import json
import re
import tomllib
from collections import Counter
from urllib.parse import urlsplit, parse_qs

root = Path.cwd()
state_path = Path('artifacts/generated/ntwc-batch/full-continuation-acquisition-v1.json')
state = json.loads(state_path.read_text())
sha = lambda data: hashlib.sha256(data).hexdigest()
assert state['status'] == 'completed' and not state['unattempted_batches']
assert not state.get('active_command') and len(state['batches']) == 8
seen = set()
counts = Counter()
raw = {}
cdx_cache = {}
cdx_sources = {a['local_path']: a for a in tomllib.loads(Path('config/ia-cdx-dev-scoped.toml').read_text())['assets'].values()}
cdx_receipts = {r['source_id']: r for r in json.loads(Path('artifacts/logs/runs/2026-10-31__2034__ia-cdx-dev-scoped__c4d5044/outputs.json').read_text())}
rejected = []
for batch in state['batches']:
    config = tomllib.loads(Path(batch['config']).read_text())['assets']
    contracts = {a.get('source_id', k): a for k, a in config.items()}
    receipts = json.loads((Path(batch['run']) / 'outputs.json').read_text())
    assert set(contracts) == {r['source_id'] for r in receipts}
    assert len(contracts) == len(receipts)
    for receipt in receipts:
        sid = receipt['source_id']
        assert sid not in seen
        seen.add(sid)
        source = contracts[sid]
        counts[receipt['status']] += 1
        if receipt['status'] not in {'downloaded', 'cached'}:
            assert receipt['status'] == 'quarantined'
            assert receipt['reason'] == 'local_or_download_error: exact_archive_capture_redirect_rejected'
            rejected.append(sid)
            continue
        path = Path(source['local_path'])
        body = path.read_bytes()
        assert receipt['local_path'] == str(path)
        assert len(body) == receipt['bytes']
        assert sha(body) == receipt['sha256'] == Path(str(path) + '.sha256').read_text().strip()
        if receipt['status'] == 'downloaded':
            assert receipt['final_url'] == source['url']
        else:
            assert receipt['final_url'] in {source['url'], 'not-recorded'}
            if receipt['final_url'] == 'not-recorded':
                counts['cached_final_url_not_recorded'] += 1
        raw[str(path)] = {'sha256': sha(body), 'bytes': len(body)}
        if source.get('expected_cdx_sha1'):
            digest = base64.b32encode(hashlib.sha1(body, usedforsecurity=False).digest()).decode()
            assert digest == source['expected_cdx_sha1'] == receipt['verified_cdx_sha1']
            cp = source['cdx_evidence_path']
            if cp not in cdx_cache:
                cb = Path(cp).read_bytes()
                assert sha(cb) == source['cdx_evidence_sha256'] == Path(cp + '.sha256').read_text().strip()
                cc = cdx_sources[cp]
                cr = cdx_receipts[cc['source_id']]
                assert parse_qs(urlsplit(cc['url']).query)['filter'] == ['statuscode:200']
                assert cr['status'] in {'downloaded', 'cached'} and cr['sha256'] == sha(cb) and cr['local_path'] == cp
                table = json.loads(cb)
                cdx_cache[cp] = [dict(zip(table[0], row)) for row in table[1:]]
            match = re.fullmatch(r'https://web.archive.org/web/(\d{14})id_/(https?://.+)', source['url'])
            assert match
            assert any(row.get('timestamp') == match[1] and row.get('original') == match[2]
                       and row.get('digest') == digest and row.get('statuscode', '200') == '200'
                       for row in cdx_cache[cp])
            counts['independent_cdx_body_checks'] += 1
assert len(seen) == 1311 and counts['independent_cdx_body_checks'] == 1214
assert len(rejected) == 5
output = Path('artifacts/generated/ntwc-batch/full-acquisition-root-review-v1.json')
assert not output.exists()
result = {
    'status': 'pass', 'reviewer': 'root independent standard-library raw byte/CDX check',
    'checkpoint_sha256': sha(state_path.read_bytes()), 'counts': dict(counts),
    'all_contracts_accounted': len(seen), 'raw_unique_paths': len(raw),
    'raw_bytes': sum(row['bytes'] for row in raw.values()),
    'rejected_exact_capture_redirects': sorted(rejected),
    'checks': ['Every terminal contract accounted exactly once', 'Every retained response SHA-256, sidecar and byte count matches receipt',
               'Every fresh successful final URL equals its exact source contract; cached final URLs may be explicitly not-recorded and are checked by pinned body digest', 'All 1214 retained IA bodies independently match pinned CDX SHA-1 and exact capture row from receipted statuscode:200-filtered index (status column omitted by source query)',
               'Five rejected redirects are retained as outcomes; no substituted captures'],
    'raw_sha256': raw,
}
output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print({k: v for k, v in result.items() if k not in {'raw_sha256', 'checks'}})
