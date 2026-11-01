"""Read-only independent data-grain and viewer-boundary acceptance checks."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import csv
import gzip
import hashlib
import json
import sys

root = Path('/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times')
package = Path(sys.argv[1])
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read = lambda path: json.loads(path.read_text())
for name, digest in {
    'data/processed/arrival-waveforms/foundation-v2/manifest.json': '3050b2c73049a4db6178c10ac0fecb9b2cd33dbbe7ebcc71177ca2b777c69490',
    'data/processed/arrival-audit/foundation-v2/manifest.json': 'd8f19d8a018ef638883de4ae57119ed2701e3019e5e5c778acb6c8229354654d',
    'data/processed/arrival-audit/comparison-v1/manifest.json': '0983c070124ce5365872a5525afbbfb99b893521c19a5a4d3a8522833e7276c3',
}.items():
    assert sha(root / name) == digest, name
def rows(path):
    with (gzip.open(path, 'rt', newline='') if path.suffix == '.gz' else path.open(newline='')) as f:
        return list(csv.DictReader(f))

manifest = read(package / 'manifest.json')
for name, digest in manifest['input_sha256'].items():
    assert sha(root / name) == digest, name
for name, digest in manifest['output_sha256'].items():
    assert sha(package / name) == digest, name
assert len(list(p for p in package.rglob('*') if p.is_file())) == len(manifest['output_sha256']) + 1
assert {k: manifest[k] for k in ('archive_entries', 'selected_entries', 'development_entries',
        'sealed_entries', 'source_reports', 'event_station_rows', 'model_eligible_events')} == dict(
    archive_entries=118, selected_entries=75, development_entries=57, sealed_entries=18,
    source_reports=1177, event_station_rows=1182, model_eligible_events=0)
dictionary = read(package / 'data_dictionary.json')
for name, schema in dictionary['tables'].items():
    records = rows(package / name)
    keys = schema['primary_key']
    assert len({tuple(row[k] for k in keys) for row in records}) == len(records), name
catalog = read(package / 'catalog.json')['entries']
event_index = rows(package / 'paper/event_index.csv')
assert [r['archive_key'] for r in catalog] == [r['archive_key'] for r in event_index]
order = lambda r: (r['origin_utc'] == 'unknown',
    datetime.fromisoformat(r['origin_utc']).isoformat(timespec='microseconds')
    if r['origin_utc'] != 'unknown' else '', r['event_id'], r['archive_key'])
assert event_index == sorted(event_index, key=order)
assert all(not r['model_eligible'] for r in catalog)
for entry in catalog:
    if entry['role'] != 'development':
        assert entry['source_reports'] == 'unknown' and entry['waveform_source_ids'] == []
        assert entry['exact_reported_clock_pairs'] == 'unknown' and not entry['viewer_ready']
reports = rows(package / 'paper/report_index.csv')
assert reports == sorted(reports, key=lambda r: (r['event_id'], int(r['table_index']), int(r['row_index'])))
census = read(root / 'artifacts/generated/ntwc-batch/census-v4/rows.json')
assert {r['report_id'] for r in reports} == {
    f"{r['event_id']}:{r['table_index']}:{r['row_index']}" for r in census}

waves_dir = root / 'data/processed/arrival-waveforms/foundation-v4'
waves = read(waves_dir / 'manifest.json')
sources = {r['source_id']: r for r in waves['sources']}
source_index = rows(package / 'paper/source_index.csv')
assert {r['source_id'] for r in source_index} == set(sources)
assert len(source_index) == 1902
assert sum(int(r['source_rows']) for r in source_index) == waves['source_rows'] == 3688140
fields = ('purpose', 'provider', 'sensor', 'provider_station_id', 'display_station_key',
          'window_start_utc', 'window_stop_utc', 'qc_states', 'value_states', 'timestamp_states',
          'source_url', 'source_sha256', 'output_sha256', 'units', 'vertical_datum', 'source_rows')
for row in source_index:
    original = sources[row['source_id']]
    for field in fields:
        value = original.get(field, 'unknown')
        expected = json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else str(value)
        assert row[field] == expected, (row['source_id'], field)
header_rows = [r for r in source_index if r['purpose'] == 'header_evidence']
assert len(header_rows) == 61
assert all(r['source_rows'] == '0' and r['normalized_path'] == 'unknown' for r in header_rows)
coverage = rows(package / 'paper/series_coverage.csv')
assert len(coverage) == len(waves['series_coverage']) == 1168
url_groups = defaultdict(list)
for row in source_index:
    if row['source_url'] not in ('', 'unknown'):
        url_groups[row['source_url']].append(row)
expected_overlap = [(u, r['source_id']) for u, members in sorted(url_groups.items())
    if len(members) > 1 for r in sorted(members, key=lambda r: r['source_id'])]
overlap = rows(package / 'paper/source_url_overlaps.csv')
assert [(r['source_url'], r['source_id']) for r in overlap] == expected_overlap
for row in overlap:
    assert int(row['group_source_count']) == len(url_groups[row['source_url']])
    original = next(r for r in source_index if r['source_id'] == row['source_id'])
    assert all(row[k] == original[k] for k in row if k != 'group_source_count')

selection = read(root / 'artifacts/generated/ntwc-batch/screen-v1/selection-v2.json')
events = {r['event_id']: r for r in selection['events']}
sealed = {r['event_id'] for r in selection['events'] if r['role'] == 'sealed_evaluation'}
viewer = read(package / 'viewer/catalog.json')
assert [datetime.fromisoformat(e['origin_utc']) for e in viewer['events']] == sorted(
    datetime.fromisoformat(e['origin_utc']) for e in viewer['events'])
contours = read(root / 'data/processed/arrival-contours/foundation-v2/manifest.json')
allowed_columns = {'event_id', 'source_id', 'station_key', 'sensor', 'timestamp_utc', 'numeric_value',
    'value_state', 'timestamp_state', 'duplicate_timestamp', 'units', 'vertical_datum', 'qc_state', 'qc_json'}
valid_time = {'reported_utc', 'epoch_calendar_agree', 'epoch_calendar_minute_agree', 'header_day_end_boundary'}
wave_rows = contour_features = wave_assets = contour_assets = 0
for event in viewer['events']:
    eid = event['event_id']
    assert events[eid]['role'] == 'development' and eid not in sealed
    origin = datetime.fromisoformat(events[eid]['usgs_time'])
    station_ids = set()
    for asset in event['waveforms']:
        path = package / 'viewer' / asset['path']
        payload = path.read_bytes()
        data = gzip.decompress(payload)
        assert len(payload) == asset['compressed_bytes'] <= 2_000_000
        assert len(data) == asset['uncompressed_bytes'] and sha(path) == asset['sha256']
        actual = rows(path)
        assert len(actual) == asset['rows']
        source = sources[asset['source_id']]
        assert source['purpose'] == 'event_window' and source['event_id'] == eid
        assert source['provider'] in {'CO-OPS', 'NOS', 'NOAA'}
        assert source['display_station_key'] == asset['display_station_key'] == 'coops:' + source['provider_station_id']
        station_ids.add(asset['display_station_key'])
        native = rows(waves_dir / source['output_path'])
        expected = [{k: r[k] for k in allowed_columns} for r in native if
            r['timestamp_state'] in valid_time and
            origin-timedelta(hours=6) <= datetime.fromisoformat(r['timestamp_utc']) < origin+timedelta(hours=30)]
        assert actual == expected, asset['source_id']
        assert all(set(r) == allowed_columns and r['event_id'] == eid and r['source_id'] == asset['source_id'] for r in actual)
        wave_rows += len(actual)
        wave_assets += 1
    assert len(station_ids) == event['usable_station_count'] >= 3
    for asset in event['published_travel_time_contours']:
        path = package / 'viewer' / asset['path']
        payload = path.read_bytes()
        data = gzip.decompress(payload) if asset['content_encoding'] == 'gzip' else payload
        assert len(payload) == asset['compressed_bytes'] <= 2_000_000
        assert len(data) == asset['uncompressed_bytes'] and sha(path) == asset['sha256']
        layer = json.loads(data)
        source = next(c for c in contours if c['event_id'] == eid and c['source_url'] == asset['source_url'])
        original = read(root / source['processed_path'])
        assert len(layer['features']) == len(original['features'])
        for actual, expected in zip(layer['features'], original['features'], strict=True):
            assert actual['geometry'] == expected['geometry']
            assert actual['properties'] == {k: expected['properties'][k] for k in ('HOURS', 'Name')}
        assert asset['ntwc_prediction_equivalence_verified'] is False
        contour_features += len(layer['features'])
        contour_assets += 1
for path in (package / 'viewer').rglob('*'):
    if not path.is_file():
        continue
    assert path.stat().st_size <= 2_000_000
    text = (gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()).decode()
    assert all(eid not in text for eid in sealed), path

result = dict(status='PASS', manifest_sha256=sha(package / 'manifest.json'),
    files_including_manifest=len(manifest['output_sha256'])+1,
    private_event_origins_known=sum(r['origin_utc'] != 'unknown' for r in event_index),
    archive_entries=len(catalog), reports=len(reports), source_entries=len(source_index),
    retained_source_rows=waves['source_rows'], header_only_entries=len(header_rows),
    series_coverage_rows=len(coverage), repeated_url_groups=len(set(r['source_url'] for r in overlap)),
    overlap_members=len(overlap), viewer_events=len(viewer['events']), viewer_waveform_assets=wave_assets,
    viewer_waveform_rows=wave_rows, viewer_contour_assets=contour_assets,
    lossless_contour_features=contour_features,
    max_viewer_asset_bytes=max(p.stat().st_size for p in (package / 'viewer').rglob('*') if p.is_file()),
    purpose_counts=dict(Counter(r['purpose'] for r in source_index)))
print(json.dumps(result, indent=2, sort_keys=True))
