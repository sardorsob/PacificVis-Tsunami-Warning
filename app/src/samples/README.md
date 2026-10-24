# Appearance gallery

Eight small coded layout drafts for comparing possible visual-story interfaces.
These are not complete applications or an accepted scientific story direction.
Every map and chart uses the same deterministic, invented Station A/B examples;
positions are fictional, the Pacific outline is schematic, and no arrival,
alert, warning-time, demographic or risk result is represented.

## Run and compare

From the repository root, with the existing locked dependencies installed:

```sh
npm run samples -- --host 127.0.0.1 --port 4178 --strictPort
```

Open `http://127.0.0.1:4178/samples.html?sample=paired-atlas` and use the gallery
links. Each URL can be bookmarked or refreshed. Unknown or omitted sample IDs
fall back to `paired-atlas`.

| Sample ID | Layout question |
| --- | --- |
| `paired-atlas` | Is an aligned map-and-two-record layout the clearest baseline? |
| `radial-record` | Can chart-bearing arms keep one station, its trace and its gaps together? |
| `radial-comparison` | Does a pinned/selected orbit help retain two station identities? |
| `timeline-map` | Is a shared linear availability rail a better starting point? |
| `editorial-story` | Does a guided reading sequence explain a record's limitations? |
| `mobile-inspector` | Can a map-first phone sheet keep a selected station and its evidence together? |
| `map-overlay-lens` | Is a static chart-bearing lens over a broad map worth the extra spatial complexity? |
| `evidence-ledger` | Would aligned traces and an explicit value table serve as a useful reference? |

The inspector's native Station A/B selector updates its identity, map highlight,
trace and coverage. Other station selections, pinned labels and lens positions
are static appearance states. The overlay lens is not draggable. No sample
fetches data or needs an API key, backend, map service, external font or asset.

## Build and verify

```sh
npm run check
npm run samples:build
```

`check` typechecks, tests and builds the original production app. The gallery
uses the separate `samples.html` entry and `vite.samples.config.ts`; its output
is `app/dist/samples/`. Serve that directory as the web root to inspect the
static build. Build the gallery after the original app: the normal build clears
`app/dist/`, including an earlier gallery build.

The checked layouts cover 1440×1000 desktop, 390×844 portrait and 844×390
landscape. Full-page screenshots may extend below the viewport. See the
[saved comparison set](../../../artifacts/ui-samples/2026-10-23/README.md).
Viewport emulation and screenshot inspection are not an actual-device study,
screen-reader audit or evidence of scientific validity.

## Source organization and fixtures

Each sample owns its component and scoped CSS in its ID-named directory.
`registry.ts` connects IDs to components; `Gallery.tsx` owns navigation. Small
SVG chart/map primitives and a single immutable fixture are shared, not the
page layouts. Production `App.tsx` and the normal entry point are unchanged.

The fixture has two invented 13-point records, sampled every five example
minutes from 0 through 60. Both traces share a linear elapsed-time axis and a
−10 to +10 cm display range. Null observations split the line into separate
segments. Coverage uses filled versus outlined cells; unavailable is never
treated as zero. The evidence table is another view of those same fixture
values, not an additional dataset. Do not substitute real data without a
separate review of timing definitions, provenance, scientific permissions and
the story's claims.
