# Local descriptive demo bundle, schema 1

This internal-only static export supplies the same evidence to the paired and
station-lens demos. It is not permission to publish the scientific assets.
Current bundle ID is `tohoku-descriptive-demo-v2` (schema/exporter version `1`).
The prior v1 bundle is retained as rejected integrity-check provenance, not the
current demo source. Arrival comparison remains false, physical arrivals released remain zero, and
the continuous NCTR field remains blocked. No arrival pick, warning-time claim,
interpolated ocean field, imputation, smoothing or timestamp snapping is added.

## Rebuild

From the code checkout, using the existing project Python environment:

```sh
python scripts/story/build_demo_data.py \
  --source-root /absolute/path/to/checkout-with-accepted-cache \
  --output-root /absolute/path/to/code-checkout/app/demo-public/data \
  --config config/story-demo.toml
```

All three arguments are required. `source-root` must be absolute and contains
the real accepted cache, release, provenance manifest and historical receipts;
no cache is copied into the code checkout. Configuration has repository-relative
paths and checked SHA-256 anchors, not a personal absolute path. Missing inputs,
changed hashes, incompatible schema/identity/semantics and unreviewed support
fail; there is no invented fixture fallback or acquisition.

The public Python interface is:

```python
export_demo_bundle(*, source_root: Path, output_root: Path, config_path: Path) -> Path
```

The return value is the newly published `output_root/<bundle_id>/` directory.
An existing destination is refused, including a dangling symlink. A per-bundle
exclusive lock serializes exporter writers. Files are written in a temporary
sibling directory, source fingerprints are checked again, and a single rename
publishes the complete bundle. Exceptions remove staging/lock, never overwrite
an existing bundle, and never publish partial output. Do not remove a lock owned
by another process; investigate an interrupted export before retrying.

Generated `app/demo-public/` is ignored and is served only by the sample/demo
configuration. Do not commit or deploy it. Choose a fresh output root for replay;
the exporter intentionally has no overwrite switch. Publication/terms review is
a separate gate.

## JSON contract

UTF-8, compact JSON, sorted object keys, deterministic row/asset/station order,
one final newline. No wall clock, machine path or build-host identity is emitted.
Only JSON finite numbers are allowed. All numeric missing values are `null`;
zero is a measurement. Consumers must validate schema and restrictions before
rendering, validate asset paths under the bundle, fetch bytes, verify byte count
and SHA-256, then decode. A missing or corrupt asset is an error, not an empty
station. SHA-256 protects integrity relative to the manifest, not a maliciously
replaced whole bundle; the local checked configuration is the upstream anchor.

### `manifest.json`

Required members:

| Field | JSON type and meaning |
| --- | --- |
| `schema_version`, `exporter_version` | string, both `"1"` |
| `bundle_id` | safe directory identifier matching `[a-zA-Z0-9_-]+` |
| `evidence_state` | `"internal_descriptive_only"` |
| `event` | `{event_id:string, origin_time_utc:string, latitude:number, longitude:number}`; source origin precision retained |
| `release` | `{release_id:string, arrival_comparison_allowed:false, physical_arrival_records_released:0, continuous_nctr_field:"blocked_no_proxy", allowed_uses:string[], prohibited_uses:string[]}` |
| `windows` | array of `{id,label,start_utc,end_utc_exclusive}` strings; final `source_full` entry has only `id,label`, because bounds are station-specific |
| `default_state` | `{selectedStationId,pinnedStationId,windowId,productKey}`; strings, except that `pinnedStationId` may be null (a one-station bundle). It names listed stations, never the same station twice, a listed window and a product key. Tōhoku: Hilo / Saipan / common_day / raw_value |
| `stations` | `StationMetadata[]`, ordered by station ID |
| `assets` | `{path:string,sha256:string,bytes:integer}[]`; all geometry/chunks, excluding manifest itself |
| `geometry_path` | `"geometry.json"` |
| `input_fingerprints` | `{path:string,sha256:string}[]`; de-duplicated source-root-relative checked inputs, every accepted follow-up output, anchor manifests, and release-bound review/input/output receipts |
| `config_sha256` | SHA-256 of exact initial config bytes used to parse settings; late mutation is rejected |
| `accounting` | `{source_observation_count,exported_observation_count,station_count,rejected_observation_count}` nonnegative integers |

`StationMetadata` contains `station_id`, `source_id`, `station_type`
(`coastal` or `dart`), `name`, `units`, `vertical_reference`, `horizontal_datum`,
`coordinate_order`, `time_basis`, original `latitude`/`longitude` finite numbers,
`observation_count`, `source`, and `products`.

`source` is an explicit allowlist: `source_id,title,publisher,accessed_on,
version_or_date,license_or_terms,processing_level,sha256` strings and `url` string
or null. Empty metadata becomes `unknown`. Only HTTPS URLs without userinfo,
query, fragment or whitespace are retained; even harmless query-based source
URLs are conservatively omitted, not rewritten. Source IDs/hashes still identify
their provenance. No arbitrary source notes, local paths, raw logs, or unrestricted
`source_extra` enter the bundle.

`products` has `{key,label,units,available}` with keys `raw_value`,
`residual_value`, `fitted_value`; `available` is boolean over the full source
record, not a claim of availability in every selected window. Coastal raw level,
DART water column and publisher retrospective residual/fitted products remain
distinct. Source units/datums are retained, including `unknown`; no common
amplitude scale or datum correction is authorized. Use station-local y-scales.

### `stations/<station_id>.json`

Required: `{schema_version:"1",station_id:string,columns:string[],rows:array[],
support:object[],coverage_spans:object[],gap_blocks:object[]}`.

`columns` is exactly this ordered schema; each row has exactly 15 cells:

```json
["observation_id","source_id","station_id","source_time","observed_at_utc",
 "raw_value","fitted_value","residual_value","units","vertical_reference",
 "raw_status","residual_status","grid_status","qc_flags","source_qc_status"]
```

Cells 0–4 and 8–12/14 are strings; 5–7 are finite numbers or null; 13 is an
object whose keys are the publisher's known IOC QC flags and values retain their
source encodings. Rows sort by UTC then observation ID. IDs and original
`source_time` strings are preserved. `observed_at_utc` is the verified normalized
UTC timestamp, not a new inferred time.

- `raw_status`: `observed` or `source_blank`; a raw blank still has its source row.
- `residual_status`: `available`, `source_blank` for missing DART residual, or
  `structurally_not_applicable` for coastal products without residual support.
- `grid_status`: `on_grid` / `off_grid` for coastal rows relative to the reviewed
  source anchor/cadence; `not_applicable` for DART. Off-grid rows remain at their
  actual timestamps and do not fill an absent exact-grid position.
- `source_qc_status`: `flagged`, `not_flagged`, or `not_reported`. A flagged zero
  remains zero; this export does not filter source QC. Empty `qc_flags` does not
  mean publisher QC passed. DART's unstructured extra numeric field is not
  silently promoted into a QC interpretation.

An absent timestamp is *not* a synthetic all-null measurement row. It is recorded
in the reviewed support/span/gap objects. Render points or only explicitly
supported segments; never connect across absent timestamps, raw blanks or
unsupported intervals. DART variable cadence is not a regular coastal grid.

### Windows and support

All windows are half-open `[start_utc,end_utc_exclusive)`. Five comparison
windows are reviewed: `common_day` is 2011-03-11 00:00 to 2011-03-12 00:00 UTC;
four event-relative intervals are −4→0, 0→6, 6→12 and 12→18 hours from the exact
source origin. `source_full` is evidence context, *not* a common comparison
period. Always show its bounds per station. Coastal full bounds come from the
reviewed publisher-supported coverage table; DART full bounds run from the first
actual observation through one microsecond after the last (a containing interval,
not inferred expected coverage).

Every support object has `station_id,window_id,start_utc,end_utc_exclusive,
support_kind,accepted_sample_n,valid_sample_n,source_blank_n,product_valid_n`.
`product_valid_n` maps all three product keys to counts of non-null source values
inside that same support interval. Full-source coastal counts reconcile all
station source rows; comparison counts reconcile the exact half-open selection.

Coastal `support_kind` is `coastal_exact_grid`. The allowlisted, already-reviewed
coverage table fields retain names and definitions:

```text
expected_n cadence_seconds source_grid_anchor_utc absent_n source_blank_n
off_grid_n off_grid_valid_n strict_numerator_n strict_denominator_n strict_percent
sample_density_numerator_n sample_density_denominator_n sample_density_percent
supported_start_utc supported_end_utc_exclusive first_grid_utc last_grid_utc
first_valid_raw_utc last_valid_raw_utc exact_valid_n
```

Counts and cadence are integers (or null for explicitly unavailable entries),
percentages are numbers/null, times are source strings including explicit
`unknown`. Strict coverage uses valid exact-grid positions / expected supported
positions. Sample density is a separate accepted capped valid-sample numerator
over the reviewed denominator; off-grid samples never improve strict coverage.
Percentages retain reviewed rounding; do not silently recompute them.

DART `support_kind` is `dart_actual_timestamps`; `strict_percent`,
`strict_numerator_n`, `strict_denominator_n` are null/not applicable. No expected
cadence or coastal completeness is invented. `cadence_seconds_counts` is a sorted
array of `{seconds:number,count:integer}` for successive actual sample deltas
within that window; it describes source support, not detected outages/arrivals.

`coverage_spans` / `gap_blocks` are allowlisted copies of reviewed coastal tables:
`station_id,window_id,start_utc,end_utc_exclusive,status,absent_n,source_blank_n,
affected_position_n,classification,classification_semantics,endpoint_semantics,
left_observed_utc,right_observed_utc,within_block_valid_raw_n`.
Counts are integers, remaining fields strings. Preserve classifications and
endpoint definitions. DART has empty coastal span/gap arrays, not zero missingness.

### `geometry.json`

`{schema_version:"1",source_crs:"EPSG:4326",display_crs:string,
coordinate_order:"x,y",central_meridian:-160,coastline:number[][][],
points:{id:string,x:number,y:number}[],bounds:[xmin,ymin,xmax,ymax]}`.
Natural Earth 1:110m v4.1.0 context passes the existing EPSG:4326/line validation;
reviewed helpers split the Pacific display seam at 20°E and use Equal Earth
centered on −160°. Points include the event and all stations. Projected metres
are for display, not certified station datums or an arrival surface. Original
station coordinates and unknown horizontal/vertical datum metadata remain in
the manifest. No modeled field/contour substitute is supplied.

## Events index (`events.json`), schema 1

`<bundles-root>/events.json` lists the events the app may open and pins each
event's bundles. The app loads it first. It is the browser's upstream anchor:
every bundle manifest is fetched, checked against the byte count and SHA-256
recorded here, and only then parsed. The index itself is not hash-checked.

The index may list more than one event. It never lists a reserved or excluded
archive entry, and it carries no selection role, model eligibility or model
output.

`{schema_version:"1", evidence_state:"internal_descriptive_only",
default_event_id:string, events:Event[]}`

| `Event` field | JSON type and meaning |
| --- | --- |
| `event_id` | string matching `[a-zA-Z0-9_-]+`; the reviewed USGS event ID; unique in the index |
| `label` | nonempty string; the reviewed short display name, for example `Tōhoku, Japan` |
| `origin_time_utc` | UTC time string (format below); the reviewed USGS origin, source precision retained |
| `latitude`, `longitude` | finite numbers, EPSG:4326, within ±90 and ±180; the reviewed USGS epicentre |
| `magnitude`, `magnitude_type` | finite number and nonempty string; the USGS preferred magnitude and its subtype, for display only |
| `records` | `BundleRef` or null; the descriptive records bundle described above |
| `layers` | `BundleRef` or null; the map-layers bundle ([story-map-layers.md](story-map-layers.md)) |
| `arrivals` | `AssetRef` or null; the reported-times file ([story-arrivals.md](story-arrivals.md)) |

- `BundleRef` is `{bundle_id:string, manifest_sha256:string, manifest_bytes:integer}`.
  `bundle_id` matches `[a-zA-Z0-9_-]+` and is used by one event only. The
  manifest is `<bundle_id>/manifest.json` under the bundles root.
- `AssetRef` is `{path:string, sha256:string, bytes:integer}`. `path` is relative
  to the bundles root, matches `[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\.json`, and its
  file name is `<event_id>.json`. `bytes` is at most 2,097,152.
- Every SHA-256 is 64 lowercase hexadecimal characters. Every byte count is a
  positive integer.
- A UTC time string is `YYYY-MM-DDTHH:MM:SS` with an optional fraction of one
  to six digits and a final `Z`, for example `2011-03-11T05:46:24.120Z`. The
  source's digits are kept as given.

Rules:

- Events sort by the origin instant (not the string), then by `event_id` in
  code-point order. `default_event_id` names a listed event. A link with no
  `event` field opens the default event.
- A records manifest's `event` must equal the entry's `event_id`,
  `origin_time_utc`, `latitude` and `longitude` exactly. A layers manifest's
  `origin_time_utc` must equal the entry's.
- `records: null` means the event has no station records. `layers: null` means
  it has no published contours. Neither is an error.
- The JSON rules are the bundle rules above: UTF-8, compact, sorted keys, one
  final newline, no wall clock or machine path. Number text is whatever the
  Python exporter writes; a consumer never rebuilds the bytes.

### What the browser checks

The browser validates a records manifest against its index entry and against
its own structure:

- bundle ID and event identity equal the index entry;
- unique stations in station-ID order, unique windows and assets;
- each comparison window is a valid half-open interval;
- defaults name a listed station, window and product;
- assets are `geometry.json` plus one chunk per listed station;
- the accounting adds up (station count, and total observations equal to the
  sum over stations).

It no longer compares a manifest with fixed Tōhoku values, because the index
pins the exact manifest bytes. Station types, window IDs and window bounds come
from the pinned manifest; there is no fixed list. These stay literal checks in
the browser for every records bundle:

- `schema_version` and `exporter_version` `"1"`, `evidence_state`
  `"internal_descriptive_only"`;
- `release.arrival_comparison_allowed` `false`,
  `release.physical_arrival_records_released` `0`,
  `release.continuous_nctr_field` `"blocked_no_proxy"`;
- `release.allowed_uses` exactly
  `["descriptive_data_quality","preliminary_story_diagnostics"]`;
- `release.prohibited_uses` exactly
  `["physical_arrival_comparison","modeled_minus_observed_residual","community_timing_selection","actionable_warning_time","operational_warning","public_story_scene_promotion"]`.

`release.release_id` is a nonempty string, so each event can have its own
descriptive release.

For a layers manifest the browser also requires `contour_source_id` to match
`ncei-ttt-[a-z0-9-]+` and `coastline_source_id` to be
`natural-earth-50m-coastline`, so that nothing else can be drawn as published
contours.

The index is the one unpinned file. A real-bundle test therefore pins the
Tōhoku entry's `event_id`, origin, latitude and longitude, and the builder's
tests pin the whole Tōhoku index by SHA-256.

### Building the index

Build the index after the bundles it lists:

```sh
uv run python scripts/story/build_events_index.py \
  --bundles-root /absolute/path/to/this-checkout/app/demo-public/data \
  --config config/story-events.toml
```

`config/story-events.toml` gives `default_event_id` and, for each event,
`event_id`, `label`, `origin_time_utc`, `latitude`, `longitude`, `magnitude`,
`magnitude_type` and the optional `records_bundle`, `layers_bundle` and
`arrivals` names. The builder:

- checks every file of every listed bundle against that bundle's manifest
  (byte count and SHA-256), and refuses a path that leaves the bundles root;
- applies the identity rules above;
- validates a listed reported-times file with the arrivals validator, requires
  its `event_id` and `origin_time_utc` to equal the entry's, and requires every
  `record.station_id` in it to be a station of that event's records manifest
  (and every `record` to be null when the event has no records bundle);
- writes one file through a temporary file and an atomic rename. An identical
  existing index is left alone. A different one is refused unless `--replace`
  is given; `--replace` replaces `events.json` and touches nothing else. An
  existing `events.json` that is a symbolic link is always refused.

Every event ID in `config/story-events.toml` must be a development entry of the
frozen selection in `config/ntwc-archive-batch-v2.toml`. A test enforces this,
with a mutation case that inserts another entry's ID and must fail. The builder
itself reads no selection role.

### Validators and the shared example

`analysis/story/events_index.py` exposes a pure `validate_events_index(value)`
that takes the parsed JSON value and touches no file. The browser loader has
the equivalent. [`examples/story-events.example.json`](examples/story-events.example.json)
is a synthetic, test-only index, pretty-printed for reading (so not in the
compact form). Tests on both sides parse it and pass the value through their
validator; nobody compares its bytes.

Planned, not in schema 1: per-event evidence counts for the all-events screen,
and the rules for events exported from the multi-event foundation (one record
product per station, one-minute preferred; display slice from 6 hours before to
30 hours after the origin; every asset at most 2 MB). Their task plans fix
those details. The Tōhoku records assets predate the 2 MB limit.

## Verification and limitations

The export checks all accepted follow-up input fingerprints and all 36 output
fingerprints, the anchored release/provenance bytes, release-bound review/input/
output manifests, cohort/event/count, observation ID and station/UTC uniqueness,
finite values, source/product/unit/datum consistency, known QC flags, original
coastal grid phase, and reviewed window source/valid counts. A final input
and follow-up output/anchor/release-receipt recheck precedes publication; the config must still match
the initial bytes used to parse settings. This is evidence integrity, not onset validation.

The accepted configuration yields 143,655 observations across all ten stations.
Full assets are approximately 33.7 MB (uncompressed); station 46411 dominates
at approximately 24.7 MB. Load manifest/geometry first, then selected/pinned
station chunks on demand. No source-preserving performance remedy beyond this
chunking has been approved. Independent browser performance/accessibility checks
belong to the consuming demos; this exporter makes no measured UI claim.

The [demo guide](../../app/src/demos/README.md) documents the paired/radial
consumers, local static preview and verification boundaries. Portable frontend
checks do not require ignored data; `npm --workspace app run test:demos` explicitly
tests the accepted local bundle and fails clearly when it is absent.
