# Story map-layers bundle

`tohoku-story-layers-v1` holds the two map layers drawn by the lens + clock
story view. It sits beside the descriptive records bundle
(`tohoku-descriptive-demo-v2`, see [demo-bundle.md](demo-bundle.md)), which it
does not change. Like that bundle it is generated, local-only and ignored by
Git under `app/demo-public/data/`.

## Files

| File | Contents |
|---|---|
| `manifest.json` | Bundle identity, display CRS, the reading statement, source ids, origin time, hour semantics, asset sizes and SHA-256, input fingerprints, config SHA-256 and accounting |
| `contours.json` | `features[]`: `hours` (integer), `index` (NCEI index contour, every 5 h), `parts[][]` of `[x, y]` |
| `coastline.json` | `parts[][]` of `[x, y]` and `closed[]` (true when a part starts and ends on the same point) |

Coordinates are Equal Earth metres
(`+proj=eqearth +lon_0=-160 +datum=WGS84 +units=m +no_defs +type=crs`, the
same display CRS as `geometry.json`), `x,y` order, rounded to whole metres.

## How to read the contours

NOAA/NCEI published tsunami travel-time contours for 11 March 2011: hours after
the earthquake, computed from a point at the epicentre (not the full rupture),
first arrival only, no wave height. They are not a station's arrival, not the
NCTR modeled field and not warning time. NCEI's
[travel-time maps page](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis/travel-time-maps)
describes them as first-arrival times for a tsunami generated at an earthquake
epicenter, made with Paul Wessel's TTT software over NCEI 2-minute relief. Hour
0 is equated with the USGS origin time, 2011-03-11T05:46:24.120Z.

## Processing

1. Verify each input's SHA-256 against `config/story-map-layers.toml`.
2. Split lines at the 20° E display seam with `split_at_display_seam` (the same
   rule as the atlas and demo geometry). Vertices slightly past ±180° are
   wrapped into the Pacific domain, never clamped or dropped.
3. Project with the display CRS and round to whole metres.
4. Write to a temporary directory, recheck inputs, then rename atomically. An
   existing bundle is never overwritten.

No simplification, smoothing, interpolation between contours or gridding.

## Sources and terms

| Layer | Source id | Terms |
|---|---|---|
| Contours | `ncei-ttt-tohoku-layer17-geojson` | Asset-specific authorship and terms are absent (see the source manifest). Internal use only until gate G2 passes. |
| Coastline | `natural-earth-50m-coastline` (v4.1.0) | Public domain (Natural Earth terms of use). |

## Build

```sh
uv run python scripts/story/build_map_layers.py \
  --source-root /absolute/path/to/checkout-with-accepted-cache \
  --output-root /absolute/path/to/this-checkout/app/demo-public/data \
  --config config/story-map-layers.toml
```

Accepted v1 accounting: 72 contour features (hours 1–75; 71–73 absent in the
source), 4,396 parts, 63,020 vertices; 1,450 coastline parts.
