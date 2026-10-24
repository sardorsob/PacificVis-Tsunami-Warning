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
| `default_state` | `{selectedStationId,pinnedStationId,windowId,productKey}` strings; Hilo / Saipan / common_day / raw_value |
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
