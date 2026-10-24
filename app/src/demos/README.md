# Descriptive station demos

Two working views inspect the same historical observations: paired station
records and a station-linked radial lens. They are internal research demos,
not the final visual story or an operational warning interface.

The export preserves 143,655 observations at ten stations, including source
blanks, off-grid timestamps, zeros and publisher QC. No physical arrival
estimates are released. Arrival comparisons remain prohibited, and the continuous
NCTR field remains unavailable; no contour or image proxy is substituted.

## Prepare the evidence

Use the project environment and an existing checkout containing the accepted
scientific cache and review receipts. This command does not acquire data:

```sh
uv run python scripts/story/build_demo_data.py \
  --source-root /absolute/path/to/checkout-with-accepted-cache \
  --output-root /absolute/path/to/this-checkout/app/demo-public/data \
  --config config/story-demo.toml
```

The exporter checks source hashes and refuses an existing destination. For a
replay, choose a fresh output root; do not delete an accepted bundle to rerun it.
Missing or changed inputs fail explicitly, without fixture substitution. See
the [bundle contract](../../../docs/data/demo-bundle.md) for schema, fingerprints,
source terms, processing and reproducibility details.

Generated `app/demo-public/` is ignored and internal-only. Do not commit, deploy
or redistribute it without the separate scientific publication/terms review.
The original [appearance gallery](../samples/README.md) remains a distinct set
of clearly labeled fictional layout studies, never a fallback for missing data.

## Build and open locally

From the repository root:

```sh
npm run check
npm --workspace app run test:demos
npm run samples:build
python -m http.server 4177 --bind 127.0.0.1 --directory app/dist/samples
```

Open [the paired demo](http://127.0.0.1:4177/demos.html) or
[the station lens](http://127.0.0.1:4177/demos.html?view=radial).
Only the built sample/demo directory is served. Do not serve the repository,
raw cache or processed-data root. Stop the server with Ctrl+C.

Run the sample build last: the production build clears `app/dist/`, including
its nested sample output. After rebuilding, reload the browser. The production
entry and configuration remain separate and do not load these scientific assets.

`npm run check` runs portable tests, typechecking and the production build;
it requires no ignored scientific bundle. `test:demos` is an explicit real-data
integration suite: it requires the accepted v2 bundle and fails clearly if it
is absent. It never silently skips or creates replacement scientific data.

## Reading and interaction

- Select any station through the native selector or named map buttons. Pinning
  retains a separate reference; selecting another station does not move it.
- Both modes share selection, pin, UTC window and product intent. Their URL
  preserves state across reload and Back. The lens also provides bounded
  previous/next station targets; it does not estimate values over empty ocean.
- Traces use actual points, UTC x-axes and station-local y-scales. Coastal level,
  DART water column and retrospective publisher residual/fitted products are
  not interchangeable amplitudes. Unavailable products are not substituted.
- `source_full` has station-specific bounds, not a common comparison period.
  Source blank, absent exact-grid timestamp, off-grid observation and QC flag
  remain separate. DART cadence is descriptive; coastal grid completeness does
  not apply to it. Missingness causes are not inferred.
- **Rows & sources** opens exact selected-window inputs, provenance and reviewed
  support. Tables keep zero and null distinct, retain flags and page 50 rows at
  a time. Enter a page number for large records. Scroll tables sideways for
  more columns; a focused table region supports arrow-key scrolling.
- Native buttons support Enter/Space; disclosures expose secondary controls.
  The evidence dialog initially focuses Close. Close or Escape preserves state
  and returns focus to its invoking control. No hover, drag, sound or animation
  is required to read the evidence.

## Verification boundaries and limitations

Assets are validated against the fixed event/cohort, schema and release
restrictions. Byte count and SHA-256 are checked before decoding each asset.
This establishes integrity relative to the local manifest, not authenticity
against malicious replacement of the entire bundle. Unknown datums remain
unknown; an empty QC object does not certify a QC pass.

Metadata and geometry load first, then selected/pinned chunks on demand. The
uncompressed export is about 33.7 MB; DART 46411 alone is about 24.7 MB. Its full
109,422-row record is retained, not downsampled. Desktop rendering was checked,
but real-phone memory, network and rendering performance are unmeasured.

Layouts were checked at 1440×1000, 390×844 and 844×390, with selected plots on
the first screen. Station controls, keyboard map/target activation, pin/clear,
product/window changes, history, retries, paging, zero/blank/off-grid/QC rows and
focus return were exercised. These checks are not a participant usability study
or screen-reader certification. Native dialog boundary traversal into browser
chrome remains unverified.

Existing dependency advisories remain untriaged; dependency remediation and
public deployment are not included. Use the bounded local static preview,
not a publicly exposed development server.
