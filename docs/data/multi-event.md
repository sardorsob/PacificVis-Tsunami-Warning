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
Of those, 314 have parseable paired reported times under the current clock
rules; the other 863 remain present with their uncertainty or rejection reason.
These are reported times, not independently validated physical onsets.

The observation snapshot contains **3,688,140 retained source rows** in 1,768
normalized files. Its 1,902 source entries also retain failed or unsupported
requests, controls and 61 metadata-only headers; those headers contribute no
observation rows. The broader source ledger covers 2,253 source IDs and 2,124
distinct retained raw paths (185,057,552 bytes) across 31 acquisition runs.
These totals count different layers, not independent measurements.

## Where to start

The local `data/processed/multi-event/foundation-v1/` package is the entry
point. Its manifest records input and output checksums and row counts. Its
private catalog covers all 118 entries. Paper tables retain source report IDs,
station-match evidence and exclusions. The viewer catalog contains only
eligible development records and separately attributed published contours.
The generated dictionary defines the files, schemas and joins. The package
pins the versions below.

| Layer | Location | Purpose |
| --- | --- | --- |
| Immutable source evidence | `data/raw/ntwc/`, `data/raw/usgs/`, `data/raw/ia/`, `data/raw/coops/`, `data/raw/ncei/`, `data/raw/registries/` | Original responses and SHA-256 sidecars |
| Source inventory | `artifacts/provenance/paper-source-manifest.csv` | URLs, publishers, retrieval evidence, units, time basis, missingness and failed attempts |
| Archive inventory | `artifacts/generated/ntwc-batch/` | Frozen selection, report inventory and acquisition dispositions |
| Station identities | `artifacts/generated/ntwc-batch/crosswalk-reviewed-v3/` | Report-to-site matches and identity evidence |
| Observing-network support | `artifacts/generated/ntwc-batch/design-reviewed-v3/` | Site reuse, connected components and design rank |
| Reported arrival tables | `data/processed/arrival-corpus/foundation-v4/` | Per-event compressed tables; every source report accounted for |
| Observation records | `data/processed/arrival-waveforms/foundation-v4/` | Native observations, quality flags, source-window purposes and coverage |
| Published contour geometry | `data/processed/arrival-contours/foundation-v2/` | NCEI linework, hours, source URLs and geometry checks |
| Consumer package | `data/processed/multi-event/foundation-v1/` | Ordered catalogs and separate paper/viewer entry points |

Build directories are immutable snapshots. Use the input paths in the latest
package manifest rather than combining files from different snapshots. Raw
data, generated datasets and local research context are excluded from Git.
Portable acquisition receipts under `artifacts/logs/runs/` preserve the exact
request contracts and outcomes.

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

NCEI contour layers remain published travel-time linework. Feature ordering is
deterministic; coordinates are not repaired or interpolated into a field.
Antimeridian crossings and tiny source boundary-precision excursions are
counted. These contours are not assumed to be the predictions used in NTWC's
arrival tables. See [NCEI's travel-time collection](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis/travel-time-maps).

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
Tōhoku story files remain unchanged.

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
`generate_waveform_contracts.py`, `acquire_tohoku.py`,
`build_waveform_foundation.py`, `normalize_audit_waveforms.py`,
`normalize_development_contours.py` and
`build_multi_event_catalog.py`, all under `scripts/`. Run them with the project
environment. Exact input paths, options, hashes and acquisition receipts are
saved in the portable acquisition and foundation run bundles under
`artifacts/logs/runs/`.

The final consolidation run is
[`2026-10-31__231956__ntwc-foundation-final__c4d5044`](../../artifacts/logs/runs/2026-10-31__231956__ntwc-foundation-final__c4d5044/meta.json).
Its input/output inventories bind the data versions above; its verification
record and retained review tools support independent replay. The paired
project-local MLflow run is `88afa5ae27c54659bf6dedb59fc52432`. The final Python gate passed 614 tests
and static checks; unchanged frontend tests/build and Tōhoku source hashes
were also verified.

The final waveform driver uses
[`config/arrival-waveforms-foundation-v4.toml`](../../config/arrival-waveforms-foundation-v4.toml)
to bind source contracts to their completed receipts. Check inputs before
building into a new output directory:

```bash
uv run python scripts/build_waveform_foundation.py \
  --recipe config/arrival-waveforms-foundation-v4.toml --check-only
uv run python scripts/build_waveform_foundation.py \
  --recipe config/arrival-waveforms-foundation-v4.toml \
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
  --corpus data/processed/arrival-corpus/foundation-v4 \
  --waveforms data/processed/arrival-waveforms/foundation-v4 \
  --contours data/processed/arrival-contours/foundation-v2/manifest.json \
  --output data/processed/multi-event/YOUR_NEW_BUILD
```

Acquisition uses explicit source contracts, bounded streaming, provider error
limits and checksum-based caching. An offline replay verifies retained files
without requesting them again. It does not turn failed or withheld requests
into acquired data.
