# Descriptive station demos

Three views inspect the same historical observations on one Night stage and
one shared clock: **Story** (six guided steps around a map lens), **Paired**
(two stations' full records, side by side) and **Station lens** (one station's
full records around the map lens). They are internal research demos, not an
operational warning interface.

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

Open [the story](http://127.0.0.1:4177/demos.html) (a plain link opens it),
[paired records](http://127.0.0.1:4177/demos.html?view=paired) or
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

- Station A is chosen through the native selector, the named map buttons or
  the named previous/next targets; B is pinned separately. B is never A: when
  A lands on B, B moves to the first other station, visibly.
- All three views share A, B, UTC window, product and the clock. The URL holds
  the whole screen (`view`, `selected`, `pinned`, `window`, `product`, `t`,
  `cmp`, `step`, `at`, `z`, `from`) and restores it on reload and Back at any
  screen size. Switching views keeps the moment: Back returns to it.
- The station lens always rests on a station; a move over open ocean glides on
  to the nearest one. It never estimates values over empty ocean.
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

## Story view: lens and published clock

`demos.html?view=story` is a full-screen guided view over the same records. A
Night map of the Pacific shows NOAA/NCEI's published hourly travel-time
contours for 11 March 2011. A fixed lens magnifies the map; the station under it
opens three panels: its record at the story clock, what supports that record,
and how to read it. Six guided steps set the clock, lens and comparison, then
free exploration opens all controls.

Build the companion map-layers bundle once (it does not change the records
bundle), then build and serve as above:

```sh
uv run python scripts/story/build_map_layers.py \
  --source-root /absolute/path/to/checkout-with-accepted-cache \
  --output-root /absolute/path/to/this-checkout/app/demo-public/data \
  --config config/story-map-layers.toml
```

Open [the story](http://127.0.0.1:4177/demos.html?view=story). The layers
contract is in [story-map-layers.md](../../../docs/data/story-map-layers.md).

How to read it:

- Contours are **published estimates**: hours after the earthquake, computed by
  NCEI from a point at the epicentre (not the full rupture), first arrival
  only, no wave height. They are not a station's arrival and not warning time.
  Hour 0 is equated with the USGS origin, 05:46:24 UTC.
- The white line on a record is the clock: a time, not an arrival pick. Points
  after it are dimmed, never removed. Records keep station-local heights.
- Over open ocean the lens names the two nearest published contour hours; it
  never interpolates a time or substitutes the nearest station.
- The loaded records cover 11 March UTC (to about +18 h). Later clock times
  say "No record loaded for this time" (backlog DEF-01).

Controls: drag or arrow keys move the map under the lens; `[` / `]` change
station; `+` / `−` zoom; Space plays; the slider seeks. **⇄ Compare** adds a
pinned second lens (B) and stacks both records on one UTC axis. URL fields
`t`, `cmp` and `step` (1–6 or `explore`) restore the view on reload and Back.
While playing, the map tilts into an oblique view and the panels fade; it
settles flat on pause. With reduced motion there is no tilt, pulse, glide or
autoplay, and the play button steps one published hour.

If the layers bundle is missing or fails its checks, the view keeps the map,
lens and records, disables the clock and says "Published contour layer
unavailable". Internal use only: the contour layer's terms are unconfirmed (G2).

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

Layouts are unit-tested for the Story and Station lens at 360×640, 390×844,
568×320, 667×375, 768×1024, 1024×768, 1280×800 and 1440×900, and checked in a
browser at the six main sizes; Paired is a responsive page checked at 1440×900
and 390×844. Station controls, keyboard map/target activation, pin/clear,
product/window changes, history, retries, paging, zero/blank/off-grid/QC rows and
focus return were exercised. These checks are not a participant usability study
or screen-reader certification. Native dialog boundary traversal into browser
chrome remains unverified.

Existing dependency advisories remain untriaged; dependency remediation and
public deployment are not included. Use the bounded local static preview,
not a publicly exposed development server.
