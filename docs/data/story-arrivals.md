# Story reported-times file, schema 1

`<arrivals_bundle_id>/<event_id>.json` holds, for one event, the published
estimates and source-reported arrival times that the app may display, with
their plain differences. One arrivals bundle holds the files of all exported
events and is published with one rename. The first bundle ID is
`story-arrivals-v1`; adding or correcting any event means a new bundle ID and a
rebuilt index, never an overwritten file. It sits beside the
records and map-layers bundles ([demo-bundle.md](demo-bundle.md),
[story-map-layers.md](story-map-layers.md)) and is pinned by the events index.
Like them it is generated, local-only and ignored by Git under
`app/demo-public/data/`.

## What the values are, and are not

- A **published estimate** is the estimated arrival time in an NTWC event
  table. Its method, issue time and origin are unknown.
- A **reported time** is what a source reported: the observed arrival time in
  an NTWC event table, or the travel duration in an NCEI gauge record. It is
  not a validated physical onset and not a measurement made by this project.
- A **difference** is plain subtraction. It does not say which side is off.
- Nothing here is a warning time, a model output or a prediction.
- NTWC and NCEI are separate sources whose lineage is unresolved. One place can
  have a report from each. They are never merged, never differenced and never
  counted as two independent observations.

The file never contains a selection role, model eligibility, cohort, sequence
group, fitted value or predicted range, and never an event outside the reviewed
development list.

## Top level

`{schema_version:"1", exporter_version:"1", evidence_state:"internal_descriptive_only",
event_id, origin_time_utc, release, display_crs, coordinate_order:"x,y", ruler,
places, reports, accounting, input_fingerprints, config_sha256}`

| Field | JSON type and meaning |
| --- | --- |
| `event_id`, `origin_time_utc` | strings; equal to the event's entry in the events index. The origin is the reviewed USGS origin, in the UTC time format of [demo-bundle.md](demo-bundle.md#events-index-eventsjson-schema-1) |
| `release` | the display permission (below) |
| `display_crs` | `"+proj=eqearth +lon_0=-160 +datum=WGS84 +units=m +no_defs +type=crs"`, the display projection of `geometry.json` |
| `ruler` | exactly `{"speed_km_per_h":713, "statement":"Constant long-wave speed over a 4 km deep ocean. A ruler, not a prediction."}` |
| `places` | `Place[]`, sorted by `site_id` in code-point order |
| `reports` | `Report[]`, in the order given under Reports |
| `accounting` | counts that must reconcile with the source tables (below) |
| `input_fingerprints` | `{path:string, sha256:string}[]`, sorted by path; only the allowlisted inputs below |
| `config_sha256` | SHA-256 of the exact config bytes used |

## Release

`release` must be exactly:

```json
{
  "allowed_uses": ["display_source_reported_times", "display_published_estimates", "display_plain_differences"],
  "arrival_comparison_allowed": false,
  "estimate_difference_display_allowed": true,
  "physical_arrival_records_released": 0,
  "prohibited_uses": ["physical_arrival_validation", "modeled_minus_observed_residual", "model_output_display",
                      "actionable_warning_time", "operational_warning", "public_release_before_release_gate"],
  "release_id": "story-reported-times-v1",
  "reported_arrival_display_allowed": true
}
```

The arrays are compared in this order. The exporter copies these values from
the reviewed manifest `artifacts/releases/story-reported-times-v1.json` and
fails when they differ from the literal above. A file whose `release` differs
in any way is invalid: the browser shows the event without reported times or
estimates and says that its reported-times file was rejected.

## `Place`

A place is one geographic site identity from the released `sites` table. A
position does not establish which instrument was deployed there.

| Field | JSON type and meaning |
| --- | --- |
| `site_id` | nonempty string; the released site identity, unique in the file |
| `label` | nonempty string; the `place_text` of the first report at this site, in `reports` order. Never geocoded |
| `position_status` | `"reviewed"` for an NTWC site (identity accepted by independent review), `"source_position"` for an NCEI site (the position NCEI reports). A place used by both sources keeps `"reviewed"` |
| `latitude`, `longitude` | finite numbers as recorded, within ±90 and ±180, datum unknown |
| `x`, `y` | JSON integers; the display projection, whole metres |
| `distance_km` | number ≥ 0; WGS84 geodesic distance from the index epicentre (pyproj `Geod(ellps="WGS84")`), rounded to 0.1 km. A straight path over the globe, not an ocean path |
| `ruler_minutes` | number; `round(distance_km / 713 × 60, 1)` |
| `record` | null, or `{station_id:string, link:"same_provider_id"}` or `{station_id:string, link:"within_1km"}` |

Only places used by at least one report are listed.

`record` links a place to a station in the event's records bundle and is null
when the event has none. `same_provider_id` means the site identity carries that
station's provider ID. `within_1km` means a records station lies within 1 km
(the same geodesic distance); it is not verified to be the same instrument, and
the app must say so. A provider-ID match wins over proximity; among several
stations within 1 km the nearest wins, then the lowest station ID. No other
matching is allowed.

## Reports

One report is one source record: one row of the event's NTWC table, or one NCEI
gauge record. `reports` lists:

- every NTWC row with an exact reported time or an exact estimate, then
- every NCEI record with a positive reported duration,

each part in the row order of the released `source_records` table. Rows with
neither are counted in `accounting`, not listed.

| Field | JSON type and meaning |
| --- | --- |
| `report_id` | nonempty string; the released `source_record_id`, unique in the file |
| `source` | `"ntwc"` or `"ncei"` |
| `site_id` | string naming a listed place, or null when the record's site identity is unresolved. A report without a place is listed but never drawn on the map |
| `place_text` | nonempty string; the source's own place text for this record |
| `gauge_kind` | `"unknown"` for NTWC (the table does not say); `"tide_gauge"` or `"deep_ocean_gauge"` for NCEI, as NCEI states |
| `reported_minutes` | number or null; minutes after the origin named by `reported_origin`, rounded to 0.001 |
| `reported_origin` | `"usgs_reviewed"` for NTWC, `"ncei_native"` for NCEI; null exactly when `reported_minutes` is null |
| `reported_utc` | NTWC: the reported UTC time when exact, else null. NCEI: always null; no arrival date is inferred |
| `reported_text` | NTWC: the raw source cell text, or null when the cell is empty. NCEI: always null (the app formats the minutes) |
| `origin_offset_seconds` | NTWC: always null. NCEI: NCEI's origin minus the reviewed USGS origin, when the source states it, else null. The duration is never shifted by it |
| `estimate_minutes`, `estimate_utc` | NTWC: the exact estimated UTC time, and that time minus the reviewed USGS origin in minutes rounded to 0.001; both null when the estimate is not exact. NCEI: always null. The origin NTWC used is unknown |
| `estimate_text` | NTWC: the raw estimate cell text, or null when the cell is empty. NCEI: always null |
| `reported_minus_estimate_minutes` | number or null; non-null exactly when the row is in the released pair table. Reported minus estimate: positive means the report is later than the estimate |
| `reported_minus_ruler_minutes` | number or null; `round(reported_minutes − ruler_minutes, 1)` using the stored values; null when either is null |
| `source_flags` | string[]; source qualifiers, currently only `"doubtful"` when NCEI marks a record doubtful. Usually empty |
| `source_id`, `source_sha256` | strings; the source snapshot and its 64-hex SHA-256, from `source_records` |

Raw text is the source cell text with leading and trailing whitespace removed
and every internal run of whitespace replaced by one space, for example
`1526 (70)` (time, then the source's Julian day). It is never an empty string:
an empty cell is null. Every UTC string in
the file uses the UTC time format of the events index.

Definitions against the released tables:

- An **exact reported time** is an NTWC `observations` row with
  `duration_state = "exact_reported_timestamp"`.
- An **exact estimate** is a `forecast_instances` row with
  `estimate_state = "exact_reported_timestamp"`.
- A **pair** is a `pair_members` row. On the current release the 388 pairs are
  exactly the NTWC rows with both an exact reported time and an exact estimate.
- A **positive reported duration** is an NCEI `observations` row with
  `duration_state = "complete_positive"`.
- A **resolved site** is a `site_links` row with `decision` `accepted` (NTWC)
  or `source_native_position` (NCEI). Anything else gives `site_id: null`.

## Numbers

All rounding is done once, by the exporter, with Python's built-in `round`
on the value computed in full precision. The browser and other consumers never
recompute a stored value.

- `reported_minutes` (NTWC) and `estimate_minutes` come from exact UTC seconds:
  (time − origin) in seconds ÷ 60.
- `reported_minutes` (NCEI) is NCEI's duration in minutes as released.
- `reported_minus_estimate_minutes` is −`estimated_minus_observed_seconds` ÷ 60
  from the pair table, rounded to 0.001. The pair table stores estimated minus
  observed; the exporter reverses the sign here and nowhere else, and a test
  fixes that rule.
- `x`, `y`, `speed_km_per_h` and every count are JSON integers. Other numbers
  are written as Python writes a float (for example `135.0`).

One-minute source resolution is not one-minute accuracy.

## Ruler

713 km/h is the long-wave speed over a constant 4 km depth (√(9.80665 × 4000)
m/s ≈ 712.98 km/h, rounded). It is a ruler for reading the ladder, not a
prediction and not a model. It ignores the real sea floor and the real path.
The Bayesian paper uses the same speed as its reference scale; whether the app
keeps the ruler is an owner decision at the design pick (T-SV-01C).

## Accounting

`accounting` is an object of JSON integers:

| Field | Meaning |
| --- | --- |
| `ntwc_table_rows` | all NTWC rows of the event in `source_records` |
| `ntwc_rows_with_reported_time` | rows with an exact reported time |
| `ntwc_rows_with_estimate` | rows with an exact estimate |
| `ntwc_rows_with_both_times` | the event's rows in the pair table |
| `ntwc_pairs_with_position` | of those, rows with a resolved site; NTWC places are always reviewed, so this is the count of pairs with a reviewed position |
| `ntwc_reported_with_position` | rows with an exact reported time and a resolved site |
| `ncei_records` | all NCEI records of the event in `source_records` |
| `ncei_reported_durations` | NCEI records with a positive reported duration |
| `ncei_durations_with_position` | of those, records with a resolved site |
| `reports` | length of `reports` |
| `places` | length of `places` |

Every count must equal the same count taken from the released tables; the
exporter fails otherwise.

## Inputs and fences

The exporter reads only these files. `input_fingerprints` lists the data
inputs (the first three items); the exporter's own config is pinned by
`config_sha256`:

- under `data/processed/arrival-evidence/foundation-v1/`: `manifest.json`,
  `source_records.csv.gz`, `observations.csv.gz`, `forecast_instances.csv.gz`,
  `pair_members.csv.gz`, `sites.csv.gz`, `site_links.csv.gz`;
- `artifacts/releases/story-reported-times-v1.json`;
- the event's records manifest, `app/demo-public/data/<bundle_id>/manifest.json`
  (or the same path under the given bundles root), for the `record` links;
- its own config, `config/story-arrivals.toml`.

Paths are repository-relative, with no leading `/` and no `..`. The paper's
target views (`T-OBS`, `T-CAL`, `NCEI-native-duration`), any model output and
any selection file are not inputs.

The lane fence is tested two ways:

1. a static test parses every module under `analysis/story/` and
   `scripts/story/` with `ast` and fails on any import from `analysis.arrival`
   or any module whose name contains `models`;
2. a runtime test runs a full export with `builtins.open`, `io.open`,
   `gzip.open` and `pathlib.Path.open` wrapped by a recorder, and fails when any
   path opened for reading has a component named `models` or is not on the
   allowlist above. Writes into the output and temporary directories are not
   reads and are ignored. The recorder cannot see native readers; the exporter
   uses only the standard library and pyproj for its inputs.

At run time the exporter refuses an event ID that does not occur in the
released `source_records` table, which holds development events only. It reads
no selection or role file. A test, not the exporter, checks that every event ID
in `config/story-arrivals.toml` is a development entry of
`config/ntwc-archive-batch-v2.toml`, with a mutation case that must fail; the
test never prints the other entries. A test also checks that no `reported_minus_*` field ever combines an NTWC
value with an NCEI value.

## Files, validators and the shared example

JSON rules are those of the other bundles: UTF-8, compact, sorted keys, one
final newline, finite numbers only, no wall clock or machine path. Every file
is at most 2,097,152 bytes. Files are written to a temporary directory and
published with one rename; an existing output bundle is never overwritten.

`analysis/story/arrivals_export.py` exposes a pure `validate_arrivals(value)`
that takes the parsed JSON value and touches no file; the browser loader has the
equivalent and also checks the cross-field rules above.
[`examples/story-arrivals.example.json`](examples/story-arrivals.example.json)
is a synthetic, test-only file, pretty-printed for reading. Tests on both sides
parse it and pass the value through their validator; nobody compares its bytes.
Its distances and projected coordinates were computed once with pyproj (already a
project dependency) and are not recomputed by tests.

Source credit: NOAA National Tsunami Warning Center event archive; NOAA
National Centers for Environmental Information / World Data Service tsunami
database; USGS earthquake catalog. Original-provider terms apply. Nothing here
is public before the project's release gate.
