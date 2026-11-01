# Multi-event tsunami data

This dataset preserves all 118 entries in the frozen snapshot of NOAA's National
Tsunami Warning Center event archive for a Bayesian study of reported coastal
arrival times and a descriptive visual story.
Archive entries are not necessarily independent earthquakes or usable tsunami
records. Some pages concern multiple earthquakes; for some, no observations
were recovered in this bounded acquisition.

The frozen metadata screen retains 75 candidate entries: 57 for development
and 18 reserved for later evaluation. The other 43 retain explicit exclusion
or uncertainty reasons. The development tables contain 1,177 source reports.
Of those, **388 have source-supported paired reported timestamps**; the other
789 remain present with their uncertainty or rejection reason. An exact
observed timestamp is available for 578 reports, including reports without a
resolved estimate. Only 159 paired reports also have reviewed geographic-site
identity in the earlier release. The reviewed evidence release raises that to
**169 pairs at 98 geographic sites across 18 events**, and supplies **258
observed-arrival candidates at 166 sites across 20 events**. These are reported
times, not independently validated physical onsets.

The observation snapshot contains **3,756,344 retained source rows** in 1,783
normalized files. Its 1,902 source entries also retain failed or unsupported
requests, controls and 61 metadata-only headers; those headers contribute no
observation rows. Twenty-one sources remain explicitly unparsed.
The foundation source ledger covers **2,408 source IDs and 2,279 distinct retained
raw paths** (192,447,446 bytes). It preserves every record from the earlier
2,388-source ledger and adds the 20-contract reference/metadata pilot. These totals count different layers,
not independent measurements.

## Where to start

For research, start with **`data/processed/arrival-evidence/foundation-v1/`**.
It retains all 3,401 individual source records and separates original pairs,
reported durations, geography, source ancestry and calendar evidence. Read its
`schema.json`, `design_summary.json` and `manifest.json` before joining tables.

The unchanged `data/processed/multi-event/foundation-v2/` package remains the
viewer entry point. Its manifest records input and output checksums and row counts. Its
private catalog covers all 118 entries. Paper tables retain source report IDs,
station-match evidence and exclusions. The viewer catalog contains only
eligible development records and separately attributed published contours.
The generated dictionary defines the files, schemas and joins. The package
pins the versions below.

| Layer | Location | Purpose |
| --- | --- | --- |
| Immutable source evidence | `data/raw/ntwc/`, `data/raw/usgs/`, `data/raw/ia/`, `data/raw/coops/`, `data/raw/ncei/`, `data/raw/registries/`, `data/raw/arrival-recovery/` | Original responses and SHA-256 sidecars |
| Source inventory | `artifacts/provenance/paper-source-manifest-v3.csv` | Appended provenance ledger; earlier versions remain immutable |
| Documentary source inventory | `artifacts/provenance/paper-source-manifest-v4.csv` | Preserves all v3 records and adds 304 original-document/search identities |
| Archive inventory | `artifacts/generated/ntwc-batch/` | Frozen selection, report inventory and acquisition dispositions |
| Station identities | `artifacts/generated/ntwc-batch/data-completion-v1/sites-reviewed/` | 571 reviewed report identities, including 38 new approvals; geography does not prove deployment continuity |
| Earlier observing-network support | `artifacts/generated/ntwc-batch/design-reviewed-v3/` | Preserved source-pair support fields; not replaced by the target-specific views |
| Reported arrival tables | `data/processed/arrival-corpus/foundation-v6/` | Same original source rows and timestamps as v5, with reviewed geography eligibility |
| Research evidence package | `data/processed/arrival-evidence/foundation-v1/` | Source records, individual observations, original pairs, native durations, calendar evidence, ancestry, opportunities and integrity diagnostics |
| Documentary supplement | `data/processed/arrival-evidence/documentary-v1/` | Separate dated forecast products, first-wave reports, source copies, unresolved clocks and unapproved linkage candidates |
| Observation records | `data/processed/arrival-waveforms/foundation-v5/` | Native observations, quality flags, source-window purposes and coverage |
| Additional reported observations | `data/processed/ncei-arrivals/foundation-v1/` | Separate NCEI gauge reports and explicit travel-duration candidates; native fields and source lineage retained |
| Published contour geometry | `data/processed/arrival-contours/foundation-v2/` | NCEI linework, hours, source URLs and geometry checks |
| Consumer package | `data/processed/multi-event/foundation-v2/` | Ordered catalogs and separate paper/viewer entry points; all 16 recovery files are under `paper/recovery/` |

Build directories are immutable snapshots. Use the input paths in the latest
package manifest rather than combining files from different snapshots. Raw
data, generated datasets and local research context are excluded from Git.
Portable acquisition receipts under `artifacts/logs/runs/` preserve the exact
request contracts and outcomes.

Corpus and waveform `foundation-v4`, and consumer package `foundation-v1`,
remain frozen comparison products. The current recovery preserves all 1,177
report IDs and raw cells, the earlier 314 paired timestamps, and all earlier
1,768 normalized waveform files. Source-aware clock rules add 74 pairs;
explicit format support adds 15 waveform files and 68,204 native rows. Recovery
uses literal source dates and reviewed, checksum-bound calendar evidence.
It does not infer missing dates from forecasts, distance or waveform features.

## Using the reviewed research tables

Join `source_records.csv.gz`, `site_links.csv.gz`, `observations.csv.gz` and
`lineage_members.csv.gz` on `source_record_id`. NTWC IDs are the original
`report_id`; NCEI IDs preserve the acquired record occurrence. The complete
earlier parsed record remains in `native_record_json`, including raw text and
source locators. No incomplete record was discarded to create these tables.

| Table or view | Records | Meaning |
| --- | ---: | --- |
| `source_records.csv.gz`, `observations.csv.gz` | 3,401 each | 1,177 NTWC and 2,224 NCEI records; individual measurements retained |
| `pair_members.csv.gz` | 388 | All original exact NTWC comparisons; join the original estimate cell through `forecast_instance_id` |
| `T-CAL.csv.gz` | 169 | Original pairs with reviewed geography; signed **estimated minus observed**, in seconds; positive means the estimate is late |
| `T-OBS.csv.gz` | 258 | Observed UTC minus the reviewed USGS reference origin; this is not necessarily the origin used by the original forecast |
| `NCEI-native-duration.csv.gz` | 1,221 | Reported duration from the NCEI-native origin; 1,141 coastal and 80 deep-ocean records, requiring separate scientific treatment |
| `calendar_evidence.csv.gz` | 17,925 | Native components, accepted earlier evidence and separately attributed documentary statements |
| `forecast_instances.csv.gz` | 1,177 | Every original estimate-cell instance, including missing estimates; original issue time/version/origin remain unresolved |

The 57/18 development/evaluation reservation is unchanged. Geographic identity
does not establish historical instrument continuity or interchangeable arrival
definitions. NCEI geographic repeats are source-qualified positions, not verified
deployment repeats. Target eligibility is a data-candidate status; every model
and physical-onset approval remains false.

The source pilot retained eight reference lists and eight information objects.
All eight lists contained references, but only two records contained
arrival-specific attribution: **2/8**, below the route's 50% expansion threshold.
No additional reference-route expansion was attempted. Listed citations do not
establish independent arrival picking. One NCEI comment gives separately
attributed Papeete times of 21:00 and 21:02 UTC; they remain separate statements,
and neither replaces the primary catalog measurement. Original citation
documents were not newly fetched by this pilot.

The first-future-clock diagnostic contradicted six of 578 dated NTWC reports
across 34 events. It remains a sensitivity result, never an automatic calendar
repair. NCEI arrival year/month remain unresolved in the primary record even
when native day/hour/minute and travel duration are present. Missingness tables
describe source and event associations; they do not identify MCAR, MAR or MNAR.

`waveform_coverage.csv.gz` audits all 1,783 normalized files. Of 3,756,344 native
rows, 48,151 lack a finite numeric value and 1,912 have unusable timestamps;
these categories can overlap. There are 1,481 excess duplicate timestamp rows,
including 223 conflicting timestamps within files. All remain in the native
data. Absent QC is unknown QC, not passed QC. Grid gaps are counted only where
timestamps align to a declared cadence, between the first and last valid sample.
No interpolation, tide removal or validated onset detection was performed.

The `audit/` packet contains 60 event cases across 31 events and nine quiet
controls from the two available control events, totaling 98 stripped traces.
Selection balances metadata and structural coverage without report or ETA
agreement. It supports nonexpert descriptive review; no blindness or expert
ground-truth claim is made. The older 69-case audit remains immutable.

`metadata/expansion-candidates.csv.gz` contains six native event identities from
four frozen queries. These are deferred candidates, not newly acquired outcome
datasets. A coordinator diagnostic accidentally displayed embedded outcome
fields from those metadata responses after query selection was frozen. No
outcomes entered selection or modeling, and the independent reviewer inspected
only whitelisted metadata. This exposure must be considered before any later
evaluation protocol; the coordinator cannot claim blindness to those fields.
The 18 reserved NTWC outcome files were not opened.

## Additional original documents

The separate `documentary-v1` supplement adds **1,287 dated forecast instances
across 75 products and nine development events**. It preserves all 108 message
versions discovered in the current warning-center search archive for those
development events, alongside original NOAA and JMA collections. Multiple copies
of the same product-point-time instance have supporting membership records;
different versions and issuing centers remain separate. Of the 75 products,
74 have documented issue times. The Kuril 2007 forecast table has dated forecasts
but an unknown issue time and version.

These additions do **not** replace the original table cells or increase the
388 original exact pairs. They recover original forecast information that the
summary tables did not fully identify. The 592 normalized-name linkage candidates
still need station/forecast-point and arrival-definition review; none is an
approved new pair. A community forecast point is not automatically the gauge
deployment that shares its name. Repeated forecasts are not independent events.

The supplement also retains 87 observation-table rows. Rabinovich et al.'s
Kuril 2006/2007 first-wave tables supply **22 dated arrivals** and two explicit
missing arrivals. Their published clocks and native travel times agree on the
calendar; maximum-wave columns are excluded. A separate PTWC compilation supplies
19 additional arrival clocks in HST, whose individual arrival dates remain
unknown, and 44 blank arrival cells. Peak-amplitude times remain separate.
Five possible links between the paper and the NTWC tables disagree by one to
seven minutes, so none repairs an original date. These are different reported
picks, not evidence that either source should be overwritten.

Forecast semantics remain explicit: 1,033 instances are estimated initial
arrivals, 206 are forecasts of the start of tsunami activity, and 48 are JMA
estimated tsunami arrivals. All clocks have minute reporting resolution; this
does not establish minute accuracy or pick uncertainty. Paper instrument markers
distinguish analog digitized tide gauges, digital bottom-pressure stations and
digital tide gauges. Historical deployment identity, shared ancestry and
physical-onset validity still require scientific review.

Search coverage was checked against all 57 development entries. Extending the
search end date by one day recovered messages missed by shorter queries, and
returned product codes did not reliably follow the requested filter. The retained
search results and message identities therefore govern coverage. No search hit
the 100-result cap. Advertised historical TEX links returned 404; an observation
endpoint silently returned current-event metadata and was excluded. Two linked
documents were inaccessible. Empty searches and inaccessible sources do not prove
that no historical record exists. Further observation recovery requires additional
dated primary reports or independently validated waveform picks.

Start with `summary.json` and `schema.json`. Use `forecast_instances.csv.gz` for
distinct product instances, `forecast_evidence.csv.gz` and `forecast_members.csv.gz`
for source copies, and `first_wave_observations.csv.gz` for reported observations.
Raw sources, failures and candidate links remain available. The v4 ledger retains
299 additional raw snapshots (9,920,310 bytes), including two wrong-event responses
that are excluded from scientific extraction. Raw files and processed tables stay
local and Git-ignored.

Reproduce the supplement offline after acquiring the explicit contracts in
`config/arrival-documentary-b01.toml` through `b21.toml`. Document extraction uses
the pinned optional `pypdf` runtime and macOS `textutil`; the portable run records
its versions and extraction recipe. These tools are not new project dependencies.

```bash
python artifacts/logs/runs/2026-11-01__1708__documentary-recovery__08ca9a1/extract_documents.py \
  . artifacts/generated/ntwc-batch/documentary-recovery-v1/extracted-8.json
.venv/bin/python scripts/build_documentary_recovery.py \
  --inputs artifacts/generated/ntwc-batch/data-completion-v1/snapshot/inputs.json \
  --extracted artifacts/generated/ntwc-batch/documentary-recovery-v1/extracted-8.json \
  --output data/processed/arrival-evidence/documentary-v1
```

Use a fresh output path for replay. Source credit: NOAA NWS/PTWC/NTWC,
JMA/NWPTAC and the UNESCO-IOC ITIC document archive;
[Rabinovich et al. (2008), doi:10.5194/adgeo-14-105-2008](https://adgeo.copernicus.org/articles/14/105/2008/).
Original-provider terms remain applicable; this repository does not redistribute
the source documents.

## Reproducing and checking the evidence release

Generated data remain local and Git-ignored; public-source acquisition contracts,
source ledgers, scripts, tests and compact run receipts are tracked. Reproduction
requires the pinned cached inputs; a Git checkout alone does not contain the
downloaded data. Raw NCEI evidence retains NOAA/WDS credit and original-provider
reference information; third-party references may have separate terms.

The stage scripts run in this order with fresh output directories:
`prepare_arrival_data_completion.py`, `build_arrival_site_registry.py` (using
`config/ntwc-station-review-v4.csv`), `build_arrival_lineage.py`,
`build_arrival_calendar_evidence.py`, `build_arrival_observations.py`,
`build_arrival_waveform_quality.py`, and `prepare_arrival_expansion.py`.
Each CLI's `--help` describes its input manifest and paths. Source lineage uses
the already downloaded receipt directory
`artifacts/logs/runs/2026-11-01__0615__arrival-completion-pilot-v1__e263bb7/`.
No new network access is needed to replay those stages.

To verify the assembled release against source records and protected inputs:

```bash
.venv/bin/python scripts/check_arrival_data_completion.py \
  --inputs artifacts/generated/ntwc-batch/data-completion-v1/snapshot/inputs.json \
  --release data/processed/arrival-evidence/foundation-v1 \
  --output artifacts/generated/ntwc-batch/data-completion-v1/release-check
```

The same CLI can assemble a fresh release using `--assemble-from` and `--receipts`.
Its report checks exact source IDs/payloads, original signed pairs, reviewed
geography, target membership, calendar restrictions, source hashes, failure
dispositions and protected bytes. Deterministic independent stage replays are
recorded in the portable scientific run receipts under `artifacts/logs/runs/`.
Unattended-worker readiness is a separate unresolved runtime limitation; this
release was produced under foreground supervision.

## Additional reported observations from NCEI

The separate NCEI collection covers all 57 development-event identities and all
60 required response pages. It retains **2,224 unique source records**: 2,082 tide
gauge and 142 deep-ocean gauge reports. One event has no gauge records. The
`reported_duration_candidates.csv.gz` table contains **1,221 explicit positive
reported travel durations across 47 events**, comprising 1,141 tide-gauge and 80
deep-ocean reports. Its target version is
`ncei_reported_initial_wave_travel_minutes_v1`; values are native reported hours
and minutes converted to minutes. They are not waveform-derived onset labels.

The six-file package includes all observations, the duration-candidate subset,
a page ledger, summary, manifest and data dictionary. Events sort by frozen UTC
origin, then event ID; records sort by numeric NCEI runup ID and source row.
`source_record_id` identifies an acquired record occurrence. Retain
`ncei_runup_id`, `development_event_id`, `source_id` and source hashes when joining.
The full original object remains in `raw_record_json`.

There are 984 records with no travel-duration components, 18 with partial
components, and one with a zero duration. Initial-wave clock components are
complete for 1,408 records, partial for 13 and absent for 803. Arrival month/year
are unresolved: **no absolute arrival date is inferred**, even where a duration
is usable. Three records lack coordinates and one is marked doubtful; all remain
in the observations table with explicit states. No missing component is filled
with zero. These are source-report availability rates, not sensor failure rates;
MCAR, MAR or MNAR cannot be established from them alone.

NCEI metadata matches and native revisions remain separate from USGS and NTWC.
For example, one NCEI origin differs from the frozen USGS reference by 80.19
seconds; another event has a materially different source location and an
earthquake-plus-landslide cause. Native source durations are not transferred to
a different origin. Geographic coordinates retain unknown datum and accuracy;
a reported location does not establish a historical instrument deployment.

Keep this source family separate from NTWC calibration pairs. Original-reference
lineage has not been independently resolved, so matching records may repeat the
same underlying report. Do not add their counts as independent observations or
merge them into the NTWC target tables without further review. All model and
physical-onset approval flags remain false. The viewer export is unchanged.

## Ordering and joins

Event catalogs sort by reviewed UTC origin, with unknown origins last. Reports
sort by event, source table and numeric source row. Waveform exports preserve
native row order and duplicate timestamps.

| Key | Meaning |
| --- | --- |
| `archive_key` | One archive entry, including entries without a resolved earthquake identity |
| `event_id` | A reviewed canonical metadata key; compound pages can involve other earthquakes, so the key alone does not establish arrival attribution |
| `report_id` | One original arrival-table row; joins the report index to its station evidence |
| `physical_site_id` | A reviewed geographic-site identity within its stated scope; it does not establish deployment continuity |
| `source_id` | In the source index, one acquisition contract/snapshot; in the report index, the original NTWC page. Follow each table's documented namespace |

Never join unresolved IDs as if they represented one shared event or station.
The generated dictionary defines each table's grain, keys, units and missing
states. Waveform counts are retained source rows, not independent measurements.
`paper/source_url_overlaps.csv` lists 89 repeated exact request/capture URL groups
with 178 source entries, without choosing a preferred snapshot. Of these groups,
24 pair observation acquisitions, 61 pair a header with an observation source,
and four pair an availability response with an observation request. Different
URLs can also overlap. Timestamp equality alone cannot resolve different
providers, stations, sensors, units or datums. Successful source snapshots have
checksums; failed requests retain their outcomes. Metadata-only evidence need
not have an observation window.

Paper tables and observations use gzip CSV where indicated. Oversized viewer
contours use lossless gzip with explicit encoding and decoded-size metadata.
Consumers must decode these assets explicitly; the file extension does not
guarantee that a web server will do it. Each viewer asset is at most 2 MB.

## What was collected

The archive pages and USGS metadata establish event identity and source-table
structure. Internet Archive capture indexes locate archived station files
linked by development pages. NOAA CO-OPS supplies separately identified water
level products. Historical file headers, provider station IDs, coordinates and
independent review support 533 report-to-site matches across 236 distinct sites.
Matches retain their provider or source-qualified geographic scope; a current
station registry alone does not establish a historical deployment.

Requested observation windows span four UTC calendar days: the day before the
earthquake through two days after it. This is a bounded acquisition unit.
NOAA's API limits one-minute requests to four days; six-minute requests may be
longer. Archive files retain their actual linked-day coverage, which can be
shorter than the requested window. See the [CO-OPS API documentation](https://api.tidesandcurrents.noaa.gov/api/prod/).

One-minute and six-minute products remain separate. No samples are interpolated
to manufacture finer cadence. Missing values, duplicate timestamps, malformed
rows, unsupported formats and provider errors remain explicit. An unavailable
request does not prove that no historical record exists elsewhere. Legacy
files whose time or unit documentation conflicts with their contents remain
raw evidence with no invented UTC or metric conversion.

Across the 3,756,344 retained rows, 48,151 water-level values are blank
(1.281858%). Provider quality flags were not supplied for 3,526,904 rows
(93.891933%); absent flags do not mean failed quality control. These fractions
describe retained source rows, including overlapping products and duplicate
timestamps. They do not measure all missing station-time observations or
unavailable records. Providers, products, eras, sampling cadence and quality
fields differ. Missing completely at random (MCAR) is not established, and the
observed snapshot alone cannot distinguish missing at random from missing not
at random. The newly supported formats retain unknown nominal cadence and are
excluded from cadence-dependent display coverage checks.

NCEI contour layers remain published travel-time linework. Feature ordering is
deterministic; coordinates are not repaired or interpolated into a field.
Antimeridian crossings and tiny source boundary-precision excursions are
counted. These contours are not assumed to be the predictions used in NTWC's
arrival tables. See [NCEI's travel-time collection](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis/travel-time-maps).

## Reported targets and network support

Two separate candidate views use reviewed event attribution and geographic-site
identity. T-OBS is the reported observed timestamp minus the reviewed USGS
reference origin, in seconds. It does not establish the origin used in the
historical NTWC prediction. T-CAL is the signed estimated UTC timestamp minus
the observed UTC timestamp, in seconds: a positive value means the published
estimate is later. It does not establish that the estimate was available before
arrival or that the historical prediction used the same origin. A log-duration
calibration target still needs a separate source-origin and product contract.

| View | Version | Eligible reports | Events | Geographic sites | Connected components | Event/site indicator rank / columns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| T-OBS | `reported_duration_from_reviewed_reference_v1` | 241 | 20 | 159 | 3 | 176 / 179 |
| T-CAL | `reported_absolute_difference_v1` | 159 | 17 | 94 | 3 | 108 / 111 |

Reports form the candidate tables; graph edges collapse repeated event/site
pairs. Only 48 T-OBS sites and 36 T-CAL sites appear in multiple events; the
median site appears in one event in each view. The support files include
leave-one-event-out and leave-one-site-out summaries for later evaluation
design. Network rank describes the additive event/site structure, not whether
Bayesian variance components can be estimated reliably. The three disconnected
components and limited site reuse need explicit treatment before modeling.

All 16 recovery products, including these views, per-report changes and support
summaries, are copied only into `paper/recovery/` in the consumer package. The
earlier `design-reviewed-v3` source-pair fields retain their original meaning.
Every candidate remains `model_eligible=false` and
`physical_onset_validated=false`; no reserved outcome is included.

## Eligibility and limits

Acquisition eligibility, display readiness and scientific modeling eligibility
are different fields. A verified provider-site identity can coexist with
unknown deployment continuity. A readable waveform can still lack enough
baseline, cadence or tidal information for an onset estimate.

The support gate passed with ten single-source thrust-cohort development
events, each with at least five distinct reviewed sites carrying both reported
values. This enabled the broader bounded waveform acquisition. It does not
validate historical deployment continuity or physical arrivals. The inventory
retains missing, blocked and withheld cases, including reserved-window overlaps.
Quiet-control candidates are screened against the pinned earthquake catalog,
whose magnitude and coverage limits remain explicit.

The viewer export contains **13 development events**, 755 waveform assets with
826,316 retained rows, and seven contour assets with 306 features. This is a
display subset, not the number of events collected or physically validated.
Each displayed event has at least three distinct supported station IDs. A
station series must cover at least 80% of nominal cadence bins in the 36-hour
slice from six hours before to 30 hours after the reviewed origin, with at least
60 consecutive supported minutes. Finite, time-valid, nonduplicate samples
support this operational coverage rule; it does not establish physical onsets.

Viewer exports exclude the paper's timing labels, selection roles, validation
results and fitted model outputs. Provider quality information remains part of
the observations. Published observations and contours are shared source products.
The current viewer export requires a verified CO-OPS/NOS/NOAA station ID and
sufficient coverage in the fixed display slice. Other providers and
source-qualified geographic matches remain in the full observation and paper
layers; extending the viewer to those records requires an explicit display
identity mapping.
The current browser demos do not yet load this multi-event catalog. Existing
Tōhoku story files remain unchanged. All 763 files under the viewer directory
are byte-identical to consumer `foundation-v1`; the recovery changes only the
paper and full-data layers.

The separate frozen audit has 69 cases: 60 event/station/source cases across 24
events and nine candidate quiet controls. Two fresh AI-assisted reviewers
recorded 90 opinions, with 21 cases reviewed by both. Their status judgments
agree on 20 of those 21 cases. Some judgments include provisional disturbance
brackets; others are ambiguous or
unreviewable. None is expert ground truth. The reviewers share a model family,
and the sample does not represent archive-wide error rates.
The eight-setting automated diagnostic remains separate and uses raw water
levels; its crossings can reflect tides and other background variation. This
audit remains bound to waveform `foundation-v2`; expanded coverage did not
change its sample or judgments.

No physical-arrival, warning-lead-time or predictive-performance claim follows
from this data preparation. Expert onset review, tidal treatment, target
definition and grouped evaluation remain scientific requirements. Local source
preservation does not establish redistribution rights for every provider;
publication must retain the source-specific terms and attribution.

## Reproduction

The main scripts are `inventory_ntwc_pilot.py`, `build_station_crosswalk.py`,
`build_arrival_design.py`, `build_arrival_corpus.py`,
`check_arrival_recovery.py`, `generate_waveform_contracts.py`, `acquire_tohoku.py`,
`build_waveform_foundation.py`, `normalize_audit_waveforms.py`,
`normalize_development_contours.py`, `build_multi_event_catalog.py` and
`build_ncei_observations.py`, all under `scripts/`. Run them with the project
environment. Exact input paths, options, hashes and acquisition receipts are
saved in the portable acquisition and foundation run bundles under
`artifacts/logs/runs/`.

The current recovery release is
[`2026-11-01__033144__recovery-final-data-release__8d19ba7`](../../artifacts/logs/runs/2026-11-01__033144__recovery-final-data-release__8d19ba7/meta.json).
Its portable bundle pins source/data versions, review receipts and the final
verification. The project-local MLflow run is `ea1886e44fec4461af972707a2d5e86d`. The full Python suite
passed **761 tests**; Ruff and Pyright pass. Frontend type checking, **178 tests**
and the production build pass. All 3,143 frozen foundation/audit files and 72
original story inputs retain their prior checksums.

The [saved NCEI command](../../artifacts/logs/runs/2026-11-01__033144__recovery-final-data-release__8d19ba7/reproduction/ncei-final-build-command.json)
records every contract, receipt, event match and semantics proof used for the
six-file build. Reproduction tools retain the reviewed mapping and source-definition
evidence. Supply a new output directory for any replay. Acquisition contracts
and raw responses are required local inputs; a manifest alone cannot recreate
unavailable provider bytes. The bundle's
[stage index](../../artifacts/logs/runs/2026-11-01__033144__recovery-final-data-release__8d19ba7/reproduction/mlflow-stage-index.json)
links ten logical recovery stages to portable evidence and local MLflow records.
These checks establish reproducible data preparation, not model approval.

Rebuild the reported-time corpus with the reviewed calendar and table-specific
time evidence into a fresh directory:

```bash
uv run python scripts/build_arrival_corpus.py \
  --config config/ntwc-archive-batch-v2.toml \
  --census artifacts/generated/ntwc-batch/census-v4 \
  --time-context config/ntwc-reported-clock-context-v2.csv \
  --time-evidence config/ntwc-time-evidence-v1.csv \
  --crosswalk artifacts/generated/ntwc-batch/crosswalk-reviewed-v3/unique_report_crosswalk.csv \
  --output data/processed/arrival-corpus/YOUR_NEW_BUILD
```

To replay the accepted target-support assessment using the pinned corpus:

```bash
uv run python scripts/check_arrival_recovery.py \
  --root . \
  --corpus data/processed/arrival-corpus/foundation-v5 \
  --baseline data/processed/arrival-corpus/foundation-v4 \
  --events-config config/ntwc-archive-batch-v2.toml \
  --time-context config/ntwc-reported-clock-context-v2.csv \
  --time-evidence config/ntwc-time-evidence-v1.csv \
  --crosswalk artifacts/generated/ntwc-batch/crosswalk-reviewed-v3/unique_report_crosswalk.csv \
  --output artifacts/generated/ntwc-batch/YOUR_NEW_RECOVERY_DESIGN
```

The waveform driver uses
[`config/arrival-waveforms-foundation-v5.toml`](../../config/arrival-waveforms-foundation-v5.toml)
to bind source contracts to their completed receipts. Check inputs before
building into a new output directory:

```bash
uv run python scripts/build_waveform_foundation.py \
  --recipe config/arrival-waveforms-foundation-v5.toml --check-only
uv run python scripts/build_waveform_foundation.py \
  --recipe config/arrival-waveforms-foundation-v5.toml \
  --output data/processed/arrival-waveforms/YOUR_NEW_BUILD
```

With the pinned local inputs present, rebuild the consumer package into a new
directory. Existing output directories are refused:

```bash
uv run python scripts/build_multi_event_catalog.py \
  --root . \
  --screen artifacts/generated/ntwc-batch/screen-v1/screen.json \
  --selection artifacts/generated/ntwc-batch/screen-v1/selection-v2.json \
  --census artifacts/generated/ntwc-batch/census-v4 \
  --design artifacts/generated/ntwc-batch/design-reviewed-v3 \
  --crosswalk artifacts/generated/ntwc-batch/crosswalk-reviewed-v3 \
  --corpus data/processed/arrival-corpus/foundation-v5 \
  --waveforms data/processed/arrival-waveforms/foundation-v5 \
  --contours data/processed/arrival-contours/foundation-v2/manifest.json \
  --recovery-design artifacts/generated/ntwc-batch/recovery-design-v1 \
  --output data/processed/multi-event/YOUR_NEW_BUILD
```

Acquisition uses explicit source contracts, bounded streaming, provider error
limits and checksum-based caching. An offline replay verifies retained files
without requesting them again. It does not turn failed or withheld requests
into acquired data.

## Collection and reporting process evidence

The [source-process supplement](source-process.md) records original provider
policies, station incidents, archive failures and source-definition conflicts.
It links four absent NTWC observations to explicit near-arrival gaps, flags four
NCEI definition comparisons and retains one additional approximate national
observation. It adds no exact pair and leaves earlier releases unchanged.
