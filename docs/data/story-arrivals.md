# Story reported-times file, schema 1

`arrivals/<event_id>.json` holds, for one event, the published estimates and
source-reported arrival times that the app may display, with their plain
differences. It sits beside the records and map-layers bundles
([demo-bundle.md](demo-bundle.md), [story-map-layers.md](story-map-layers.md))
and is pinned by the events index. Like them it is generated, local-only and
ignored by Git under `app/demo-public/data/`.

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
| `event_id`, `origin_time_utc` | strings; equal to the event's entry in the events index. The origin is the reviewed USGS origin |
| `release` | the display permission, copied from the reviewed release manifest (below) |
| `display_crs` | string; the display projection of `geometry.json` (`+proj=eqearth +lon_0=-160 …`) |
| `ruler` | `{speed_km_per_h:number, statement:string}`; see Ruler |
| `places` | `Place[]`, sorted by `site_id` |
| `reports` | `Report[]`, in the order of the source tables |
| `accounting` | counts that must reconcile with the source tables (below) |
| `input_fingerprints` | `{path:string, sha256:string}[]`; every released table and manifest read |
| `config_sha256` | SHA-256 of the exact config bytes used |

`release` is `{release_id:string, reported_arrival_display_allowed:true,
estimate_difference_display_allowed:true, physical_arrival_records_released:0,
arrival_comparison_allowed:false, allowed_uses:string[], prohibited_uses:string[]}`.
The browser draws a reported time only when `reported_arrival_display_allowed`
is `true`, and an estimate or a difference only when
`estimate_difference_display_allowed` is `true`.

## `Place`

A place is one geographic site identity from the released `sites` table. A
position does not establish which instrument was deployed there.

| Field | JSON type and meaning |
| --- | --- |
| `site_id` | nonempty string; the released site identity, unique in the file |
| `label` | nonempty string; the source's own place text from the first report at this site. Never geocoded |
| `position_status` | `"reviewed"` (an accepted site identity) or `"source_position"` (the position the source itself reports) |
| `latitude`, `longitude` | finite numbers as recorded, EPSG:4326 order, datum unknown |
| `x`, `y` | integers; the display projection, whole metres |
| `distance_km` | number ≥ 0; WGS84 geodesic distance from the index epicentre, rounded to 0.1 km. A straight path over the globe, not an ocean path |
| `ruler_minutes` | number; `distance_km / ruler.speed_km_per_h × 60`, rounded to 0.1 |
| `record` | null, or `{station_id:string, link:"same_provider_id" or "within_1km"}` |

`record` links a place to a station in the event's records bundle.
`same_provider_id` means the site identity carries that station's provider ID.
`within_1km` means a records station lies within 1 km; it is not verified to be
the same instrument, and the app must say so. A provider-ID match wins over
proximity. No other matching is allowed.

## `Report`

One report is one source record: one row of the event's NTWC table, or one NCEI
gauge record.

| Field | JSON type and meaning |
| --- | --- |
| `report_id` | nonempty string; the released source record ID, unique in the file |
| `source` | `"ntwc"` or `"ncei"` |
| `site_id` | string naming a listed place, or null when the record has no usable position. A report without a place is listed but never drawn on the map |
| `place_text` | string; the source's own place text for this record |
| `gauge_kind` | `"tide_gauge"`, `"deep_ocean_gauge"` or `"unknown"`, as the source states |
| `reported_minutes` | number or null; minutes after `reported_origin`, rounded to 0.001 |
| `reported_origin` | `"usgs_reviewed"` for NTWC (reported UTC time minus the reviewed USGS origin), `"ncei_native"` for NCEI (the duration NCEI reports from its own origin), or null |
| `reported_utc` | string or null. NTWC only. NCEI records carry no arrival date and none is inferred |
| `reported_text` | string or null; the raw source text of the reported time |
| `origin_offset_seconds` | number or null. NCEI only: NCEI's origin minus the reviewed USGS origin, when the source states it. The duration is never shifted by it |
| `estimate_minutes` | number or null. NTWC only: estimated UTC time minus the reviewed USGS origin, rounded to 0.001. This places the estimate on the app's clock; the origin NTWC used is unknown |
| `estimate_utc`, `estimate_text` | strings or null. NTWC only |
| `reported_minus_estimate_minutes` | number or null; present only when one NTWC row has both exact times. Reported minus estimate: positive means the report is later than the estimate |
| `reported_minus_ruler_minutes` | number or null; `reported_minutes` minus the place's `ruler_minutes`, rounded to 0.1 |
| `source_flags` | string[]; source qualifiers kept verbatim in meaning, for example `"doubtful"`. Usually empty |
| `source_id`, `source_sha256` | strings; the source page or record snapshot and its hash |

The released pair table stores estimated minus observed, in seconds. The
exporter reverses the sign once, and a test fixes that rule. One-minute source
resolution is not one-minute accuracy.

## Ruler

`ruler.speed_km_per_h` is 713: the long-wave speed over a constant 4 km depth.
It is a ruler for reading the ladder, not a prediction and not a model. It
ignores the real sea floor and the real path. The Bayesian paper uses the same
speed as its reference scale; the app shows no fitted curve around it.

## Accounting

`accounting` is an object of nonnegative integers:

| Field | Meaning |
| --- | --- |
| `ntwc_table_rows` | all rows of the event's NTWC table or tables |
| `ntwc_rows_with_reported_time` | rows with an exact reported time |
| `ntwc_rows_with_estimate` | rows with an exact estimate |
| `ntwc_rows_with_both_times` | rows with both; equals the event's rows in the released pair table |
| `ntwc_pairs_with_position` | of those, rows at a listed place |
| `ntwc_reported_with_position` | rows with a reported time at a listed place |
| `ncei_records` | all NCEI gauge records for the event |
| `ncei_reported_durations` | NCEI records with a positive reported duration |
| `ncei_durations_with_position` | of those, records at a listed place |
| `reports` | length of `reports` |
| `places` | length of `places` |

`reports` contains every NTWC row with at least one exact time and every NCEI
record with a positive reported duration. Rows with neither are counted, not
listed. Every count must equal the same count taken from the released tables;
the exporter fails otherwise.

## Sources

The exporter reads only the reviewed release
`data/processed/arrival-evidence/foundation-v1/` and the reviewed display
release manifest under `artifacts/releases/`. It lives in `analysis/story/`,
imports nothing from `analysis/arrival/` and reads nothing under any `models/`
directory. Tests enforce both. Event IDs come from the exporter's config; an ID
that is not a development event in the release is refused.

JSON rules are those of the other bundles: UTF-8, compact, sorted keys, one
final newline, finite numbers only, no wall clock or machine path. An existing
output is never overwritten. Every file is at most 2 MB.

[`examples/story-arrivals.example.json`](examples/story-arrivals.example.json)
is a synthetic, test-only file. The exporter's tests and the browser loader's
tests must both accept it.

Source credit: NOAA National Tsunami Warning Center event archive; NOAA
National Centers for Environmental Information / World Data Service tsunami
database; USGS earthquake catalog. Original-provider terms apply. Nothing here
is public before the project's release gate.
