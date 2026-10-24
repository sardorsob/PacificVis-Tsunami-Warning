# Pacific Tsunami Warning Time

## PacificVis 2027 — Conference Paper + Visual Data Storytelling Contest

One tsunami crosses a shared ocean, but bathymetry, geography, observation
coverage, and warning systems leave Pacific communities with very different
timing experiences.

This repository is a reproducible research and communication workspace for two
related—but materially different—PacificVis 2027 submissions:

1. a **Conference Paper** investigating discrepancies among modeled and
   observed tsunami arrival times with uncertainty-aware visual analytics and
   statistical or machine-learning methods; and
2. an **interactive visual data story** that uses one historical event to
   explain why distance alone is a poor account of when a tsunami arrives.

Both products share a governed scientific data foundation. They do not share a
thesis, fitted-model result, final figure, narrative sequence, interaction
design, or submission claim.

## Project at a glance

| Lane | Main question | Intended output | Current state |
| --- | --- | --- | --- |
| Shared scientific foundation | What source data can be acquired, normalized, and interpreted defensibly? | Versioned source contracts, checksums, tables, quality evidence, and release manifests | Descriptive EDA accepted; arrival comparisons require revision |
| Conference Paper | How can uncertainty-aware visual analytics and statistical learning reveal systematic modeled-versus-observed timing discrepancies? | Multi-event research corpus, methods, evaluation, figures, and manuscript | Dual-track direction approved; paper-specific analysis not started |
| Visual Data Story | How did one tsunami produce different arrival-time experiences around the Pacific, and why is distance alone misleading? | Guided browser story in `app/` | Data proof in progress; production story not started |

The **2011 Tōhoku earthquake and tsunami** is the provisional source event for
the current data proof. “Tōhoku” names the event and its source region in Japan;
it does not limit the dataset to northeastern Japan. The observational chain
extends across the Pacific to DART stations and coastal gauges in Alaska,
Hawaiʻi, California, American Samoa, Saipan, and Chile.

## Current status

The repository is in the **data-proof and adaptive exploratory-analysis phase**.
The source inventory, acquisition, and normalization have passed review; the
first missingness slice is implemented and verified. Tōhoku is still
provisional until the remaining arrival, spatial, join, NCTR-structure, and
distance-versus-arrival checks pass the final data-proof review.

The current local evidence contains:

- 18 exact source contracts: 17 acquired and checksummed, 1 explicitly blocked;
- 1 reviewed USGS event record;
- 4,380 normalized NCEI travel-time contour parts containing 62,988 vertices;
- 10 observation stations: 4 DART stations and 6 coastal gauges;
- 143,655 accepted water-level observations; and
- 107 quarantined or rejected records retained in the accounting.

The blocked asset is the requested continuous NCTR modeled field. No stable,
event-specific machine-readable field with sufficient grid, time, unit, and
source metadata was verified, so images and shifted comparison plots are not
used as substitutes. The published NCTR source coefficients are retained as
separate source evidence.

The browser shell does not yet contain a simulated wave, operational warning
information, or an accepted scientific story claim.

## Dataset gathering

The data workflow follows the same principle used throughout the repository:
**contract first, bytes second, interpretation last**. A file is not considered
usable merely because it can be downloaded.

### Source inventory

| Source class | Publisher and assets | Role | Status |
| --- | --- | --- | --- |
| Earthquake metadata | USGS FDSN event record for `official20110311054624120_30` | Origin time, location, depth, magnitude, and event identity | 1 approved asset |
| Modeled travel time | NOAA NCEI TTT layer 17 metadata and ordered GeoJSON | Source-published first-arrival contours in hours | 2 approved assets |
| NCTR source description | NOAA PMEL/NCTR event page | Six published unit-source coefficients | 1 approved asset |
| NCTR continuous field | NOAA PMEL/NCTR model-data pages | Requested continuous modeled field | 1 blocked asset; no proxy used |
| Deep-ocean observations | NOAA NCEI/NDBC DART records 21418, 21413, 46411, and 32401 | Two near-field and two far-field water-column series chosen before residual inspection | 4 approved assets |
| U.S. coastal observations | NOAA CO-OPS gauges at Adak, Hilo, Crescent City, and Pago Pago | One-minute coastal water-level series | 4 approved assets |
| Saipan coastal observations | Exact NOAA event files `.070`, `.071`, and `.072` | Event-day series plus two archival companions | 3 approved preserved assets |
| Valparaíso coastal observations | IOC Sea Level Monitoring Facility radar and pressure series | Radar analysis series plus a pressure quality companion | 2 approved assets |

The six coastal analysis candidates are **Adak, Hilo, Crescent City, Pago Pago,
Saipan, and Valparaíso**. Four DART records add a near-field/far-field deep-ocean
comparison. Station selection was recorded before modeled residuals were
inspected to reduce outcome-driven selection.

Saipan's live NOAA links returned HTTP 403, so the pipeline accepted preserved
copies of those exact URLs only after their headers, identities, units, time
basis, coordinates, byte counts, and checksums were verified. Valparaíso was
retrieved from the official IOC research interface. Its credential is read from
macOS Keychain and sent only as an `X-API-KEY` header to the exact approved IOC
host; it is never written to a URL, configuration file, run bundle, log, or Git.

See the [source inventory](docs/data-sources.md),
[source contracts](config/tohoku-data-proof.toml), and machine-readable
[source manifest](artifacts/provenance/source-manifest.csv) for the complete
asset-level evidence.

### Collection and validation rules

Every source contract records:

- source ID, publisher, exact URL, retrieval date, version, and terms note;
- expected format, content signature, byte count, and SHA-256 checksum;
- units, temporal semantics, CRS, coordinate order, and horizontal/vertical
  datum when the publisher states them;
- local raw path, processing history, missingness, and rejection accounting; and
- an explicit `unknown` or `blocked` value where evidence is insufficient.

The pipeline does not silently repair geometry, infer a datum, snap source
timestamps, replace NoData with zero, or drop malformed records. Raw assets are
immutable after acquisition. Each stage records its inputs, outputs, counts,
hashes, Git SHA, command, and disposition in a portable run bundle.

### Data flow

```text
reviewed source contracts
  -> source-gated acquisition
  -> immutable checksummed raw cache
  -> deterministic normalization and quarantine
  -> source-factual data-quality and missingness analysis
  -> independent data-proof review
  -> versioned shared release manifest (next gate)
       |-> paper-only corpus and experiments
       `-> story-only bundle and browser exports
```

The main data layers are deliberately separated:

| Layer | Location | Git policy |
| --- | --- | --- |
| Source contracts and provenance | `config/`, `artifacts/provenance/` | Tracked |
| Raw source bytes and checksum sidecars | `data/raw/` | Ignored; immutable local cache |
| Interim processing data | `data/interim/` | Ignored; reproducible checkpoints |
| Analysis-ready tables and schemas | `data/processed/` | Ignored; rebuilt deterministically |
| Portable run evidence | `artifacts/logs/runs/` | Tracked |
| Compact EDA metrics | `artifacts/eda/` | Tracked when curated; generated by scripts |
| Local MLflow state | `.mlflow/` | Ignored; paired with portable run IDs |
| Local working notes and reports | `context/` | Ignored; retained locally |

The accepted normalized tables are:

| Table | Grain |
| --- | --- |
| `event.csv` | One row per reviewed earthquake event |
| `station.csv` | One row per selected DART deployment or coastal gauge |
| `observation.csv` | One row per accepted station timestamp and source sample |
| `ttt_contour.csv` | One row per source contour part and travel-time value |
| `rejected_record.csv` | One row per rejected asset, feature, station, or sample |
| `accounting.json` / `schemas.json` | Stage counts, field contracts, and output metadata |

The shared audit retains all 80 event and 80 control settings, including
failures, in [the canonical evidence bundle](artifacts/eda/shared/2026-10-05-final/).
These are threshold diagnostics, not validated physical-arrival records. See
[the EDA report](artifacts/eda/shared/2026-10-05-final/report.md)
and [restricted release](artifacts/releases/tohoku-descriptive-v1.json).
The preliminary visual atlas is independently accepted; arrival comparisons and
community selection remain blocked. The continuous NCTR field is still unavailable.

### Visual-story follow-up diagnostics

The [follow-up report](artifacts/eda/story/followups/2026-10-14-story-followups-v3/report.md)
compares the same UTC day across six coastal gauges, preserves gaps and off-grid
samples, and separates signal support from physical timing validity. It includes
eight PNG/SVG figure pairs, reference CSVs and checksum manifests. These are
preliminary analytical artifacts, not approved story scenes or arrival estimates.

Rebuild from the accepted local cache into fresh directories:

```bash
uv run python scripts/story/build_followup_eda.py \
  --tasks regional coverage signal contours synthesis \
  --run-id YOUR_RUN_ID \
  --output artifacts/eda/story/followups/YOUR_RUN_ID \
  --run-dir artifacts/logs/runs/YOUR_RUN_ID
```

Existing output directories are refused. The optional `contours` task describes
stored source vertices only; it does not assign station arrivals. The portable
run records parameters, source hashes, metrics and implementation SHA; MLflow
tracking remains local and ignored.

### Reproducing the pipeline

Review `config/tohoku-data-proof.toml` before any networked acquisition. Running
the acquisition against a populated cache verifies the existing bytes; missing
approved assets may require network access, and the IOC assets require the
project-specific Keychain entry.

```bash
uv run python scripts/acquire_tohoku.py \
  --config config/tohoku-data-proof.toml \
  --root . \
  --run-tag local-acquisition
```

Normalize an acquisition inventory without network access:

```bash
uv run python scripts/build_tohoku_data.py \
  --inventory artifacts/logs/runs/2026-09-09__1923__valparaiso-reviewed__7576ffb/outputs.json \
  --config config/tohoku-data-proof.toml \
  --root . \
  --run-tag local-build
```

Run the reproducible missingness slice against a reviewed normalized build:
replace `RUN_ID` with a new unique run identifier and `GIT_SHA` with the output
of `git rev-parse --short HEAD`.

```bash
uv run python scripts/profile_missingness.py \
  --processed-dir data/processed/tohoku/2026-09-09-valparaiso-reviewed-7576ffb-a \
  --config config/tohoku-missingness.toml \
  --artifact-dir artifacts/eda/missingness \
  --run-dir artifacts/logs/runs/RUN_ID \
  --report context/EDA_REPORT.md \
  --run-id RUN_ID \
  --git-sha GIT_SHA \
  --working-tree clean \
  --mlflow-dir .mlflow/mlruns \
  --mlflow-experiment tohoku-eda
```

Inspect the generated result through the thin Marimo view:

```bash
uv run marimo edit notebooks/tohoku_missingness.py
```

The notebook performs no acquisition, imputation, or unique scientific
calculation. Reusable Python modules and scripts own the calculations;
Markdown reports own the interpretation.

## Paper and visual-story separation

The repository remains unified because acquisition, provenance, normalization,
and source-factual quality findings should have one implementation and one
scientific meaning. The seam is the reviewed shared release: both submissions
may consume it, but neither may consume the other's derived artifacts.

| Surface | Shared foundation | Conference Paper | Visual Data Story |
| --- | --- | --- | --- |
| Data scope | Reviewed public sources and source-faithful tables | Multi-event, multi-station corpus planned | One reviewed Tōhoku event and small observation chain |
| Analysis | Data quality, missingness, schemas, and transparent source-factual derivations | Statistical/ML modeling, calibration, uncertainty, sensitivity, and visual-analytics evaluation | Descriptive EDA used to choose defensible narrative contrasts |
| Main contribution | Trustworthy, reusable evidence | Scientific visual-analytics method and evaluated research claim | Original guided narrative and interaction design |
| Outputs | Release manifests and shared reports | Paper-only models, figures, tables, supplements, and manuscript | Story-only static exports, scenes, prose, and browser application |
| Prohibited crossover | No fitted submission-specific result | Must not import story modules or reuse story figures/prose | Must not import paper modules or expose paper-model results |

Both submissions will disclose their shared dataset and preserve distinct
questions, methods, figures, and prose. Their final artifact inventories will
document the extent of overlap.

## Repository structure

The current repository is organized around a shared scientific foundation and
a static browser workspace:

```text
Tsunami-Warning-Times/
├── app/                    React, TypeScript, and Vite visual-story workspace
├── artifacts/              Provenance, portable runs, and generated evidence
├── config/                 Reviewed source and EDA configuration; no secrets
├── data/                   Ignored raw, interim, and processed scientific data
├── docs/                   Scientific methods, sources, and feasibility research
├── notebooks/              Thin Marimo views over script-generated artifacts
├── pipeline/               Reusable typed acquisition, normalization, and EDA modules
├── public/data/            Current ignored location for generated web assets
├── scripts/                Reproducible command-line entry points
└── tests/                  Data-contract, pipeline, and provenance tests
```

As the approved dual-track migration proceeds, new submission-specific work
will use explicit lane directories:

```text
analysis/paper/             Paper statistics, ML, and visual-analytics analysis
analysis/story/             Story-only descriptive and narrative-selection analysis
scripts/paper/              Paper experiment and evaluation entry points
scripts/story/              Story analysis and export entry points
notebooks/paper/            Paper diagnostics and experiment views
notebooks/story/            Story-only exploratory views
tests/paper/                Paper protocol and evaluation tests
tests/story/                Story analysis and export tests
paper/                      Manuscript, final paper figures, and supplements
app/public/data/            Planned story-only static export location
```

Existing top-level modules, scripts, notebooks, and tests are
the shared lane. Completed checksummed evidence remains at its recorded path;
the migration will not move historical outputs merely for directory symmetry.

Start with the [methodology](docs/methodology.md),
[source inventory](docs/data-sources.md), and
[timing audit protocol](docs/research/arrival-audit.md).
Internal planning, working notes, and local guidance are kept outside version control.

## Local setup

Requirements:

- Python 3.12
- Node.js 24.18.0
- `uv` 0.11.26
- npm 11.16.0

```bash
uv sync
npm install
```

Start the current browser shell:

```bash
npm run dev
```

The separate [appearance gallery](app/src/samples/README.md) compares eight
coded layout drafts using visibly invented Station A/B fixtures. It does not
replace the story shell or present scientific results:

```bash
npm run samples -- --host 127.0.0.1 --port 4178 --strictPort
```

Open `http://127.0.0.1:4178/samples.html?sample=paired-atlas`. Saved desktop,
portrait, and landscape [screenshots](artifacts/ui-samples/2026-10-23/README.md)
allow comparison without running the gallery.

Run the full repository gate:

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
uv run python -m pipeline.provenance artifacts/provenance/source-manifest.csv
npm run check
```

## Evidence and reporting

Generated scientific data and figures are rebuilt by scripts and are not
hand-edited. Every substantive acquisition, normalization, EDA, or experiment
must record results, interpretation, limitations, decisions, and next steps in
a Markdown report. Portable run bundles and machine-readable metrics provide
the calculation evidence; Markdown is the canonical handoff and review surface.

## Safety and interpretation

This project is retrospective research and visual communication, not an
operational warning system. Modeled arrival, observed first deviation, maximum
wave, bulletin issue, public alert, and evacuation times remain separate
concepts. Rupture-to-arrival duration is not called “actionable warning time”
without evidence for the alert or warning-system timestamps being compared.

For current tsunami information, follow official local authorities and warning
centers.

## License

No repository license has been selected. Do not assume reuse rights for project
code, narrative, or derived assets. Each input source retains its own terms and
attribution requirements; see the source manifest and acquisition report before
redistributing data or derivatives.
