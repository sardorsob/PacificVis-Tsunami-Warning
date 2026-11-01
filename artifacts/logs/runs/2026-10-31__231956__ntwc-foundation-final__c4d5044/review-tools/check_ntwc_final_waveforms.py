from pathlib import Path
from collections import Counter
from itertools import zip_longest
import csv
import gzip
import hashlib
import json
import math
import sys

base = Path(sys.argv[1])
preview = Path(sys.argv[2])
receipt_path = Path(sys.argv[3])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
tree = lambda folder: {str(p.relative_to(folder)): sha(p) for p in folder.rglob('*') if p.is_file()}
assert tree(base) == tree(preview)
manifest = json.loads((base / 'manifest.json').read_text())
counts = Counter()
value_states = Counter()
timestamp_states = Counter()
qc_states = Counter()
purposes = Counter()
cadences = Counter()
units = Counter()
seen = set()
for source in manifest['sources']:
    sid = source['source_id']
    assert sid not in seen
    seen.add(sid)
    counts[source['processing_status']] += 1
    purposes[source.get('purpose', 'unknown')] += 1
    if source['processing_status'] != 'normalized_source_samples':
        continue
    raw = Path(source['raw_path'])
    assert sha(raw) == source['source_sha256'] == Path(str(raw) + '.sha256').read_text().strip()
    output = base / source['output_path']
    assert sha(output) == source['output_sha256']
    if source['provider'] == 'CO-OPS':
        original = json.loads(raw.read_text())['data']
    else:
        original = [{'line': line} for line in raw.read_text().splitlines()[4:]]
    n = 0
    timestamps = Counter()
    with gzip.open(output, 'rt', newline='') as handle:
        for n, (row, original_row) in enumerate(zip_longest(csv.DictReader(handle), original), start=1):
            assert row is not None and original_row is not None
            assert json.loads(row['raw_row_json']) == original_row
            assert row['source_id'] == sid and row['event_id'] == source['event_id']
            assert int(row['source_row_number']) == n
            assert row['source_row_id'] == f"{source['event_id']}:{sid}:{n}"
            assert row['units'] == source['units'] and row['vertical_datum'] == source['vertical_datum']
            assert row['physical_site_id'] == row['deployment_id'] == 'unknown'
            if row['value_state'] == 'finite_numeric':
                assert math.isfinite(float(row['numeric_value']))
                assert float(row['raw_value']) == float(row['numeric_value'])
            if row['timestamp_utc'] != 'unknown':
                timestamps[row['timestamp_utc']] += 1
            value_states[row['value_state']] += 1
            timestamp_states[row['timestamp_state']] += 1
            qc_states[row['qc_state']] += 1
    assert n == source['source_rows'] == len(original)
    assert sum(v - 1 for v in timestamps.values()) == source['duplicate_timestamp_excess']
    assert sum(v for v in timestamps.values() if v > 1) == source['duplicate_timestamp_rows']
    counts['source_rows'] += n
    cadences[str(source['declared_cadence_seconds'])] += 1
    units[source['units']] += 1
assert len(seen) == 1902 and counts['source_rows'] == manifest['source_rows']
result = {
    'status': 'pass', 'reviewer': 'root independent raw-record conservation and deterministic replay',
    'manifest_sha256': sha(base / 'manifest.json'), 'files_replayed': len(tree(base)),
    'source_entries': len(seen), 'counts': dict(counts),
    'value_states': dict(value_states), 'timestamp_states': dict(timestamp_states), 'qc_states': dict(qc_states),
    'source_purposes': dict(purposes), 'native_cadence_file_counts': dict(cadences), 'native_unit_file_counts': dict(units),
    'checks': ['Every preview and final file byte-identical', 'Every normalized raw record independently equals its retained CSV raw_row_json in original order',
               'All source-row IDs and counts conserved, including malformed and duplicate rows', 'Finite numeric values preserve source units and values',
               'All raw and normalized hashes match; no deployment or physical-site identity silently inferred in observations'],
}
assert not receipt_path.exists()
receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps(result, indent=2))
