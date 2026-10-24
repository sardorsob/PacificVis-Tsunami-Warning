# UI appearance comparisons

Eight coded drafts captured at three viewport sizes. All station names,
positions and chart values are invented examples, not scientific results.
These screenshots compare layouts; they do not establish an arrival time,
warning estimate, geographic accuracy or a preferred scientific story.

| Draft | Desktop | Portrait | Landscape |
| --- | --- | --- | --- |
| Paired atlas | [1440px](paired-atlas-desktop.jpg) | [390px](paired-atlas-portrait.jpg) | [844px](paired-atlas-landscape.jpg) |
| Radial record | [1440px](radial-record-desktop.jpg) | [390px](radial-record-portrait.jpg) | [844px](radial-record-landscape.jpg) |
| Radial comparison | [1440px](radial-comparison-desktop.jpg) | [390px](radial-comparison-portrait.jpg) | [844px](radial-comparison-landscape.jpg) |
| Timeline map | [1440px](timeline-map-desktop.jpg) | [390px](timeline-map-portrait.jpg) | [844px](timeline-map-landscape.jpg) |
| Editorial story | [1440px](editorial-story-desktop.jpg) | [390px](editorial-story-portrait.jpg) | [844px](editorial-story-landscape.jpg) |
| Mobile inspector | [1440px](mobile-inspector-desktop.jpg) | [390px](mobile-inspector-portrait.jpg) | [844px](mobile-inspector-landscape.jpg) |
| Map-overlay lens | [1440px](map-overlay-lens-desktop.jpg) | [390px](map-overlay-lens-portrait.jpg) | [844px](map-overlay-lens-landscape.jpg) |
| Evidence ledger | [1440px](evidence-ledger-desktop.jpg) | [390px](evidence-ledger-portrait.jpg) | [844px](evidence-ledger-landscape.jpg) |

The desktop viewport is 1440×1000, portrait 390×844, and landscape 844×390.
Images are full-page JPEGs, so their height may exceed the viewport. The
[manifest](manifest.json) records the source commit, actual CSS/document
dimensions, disclosures and SVG text bounding-box measurements. Those bounds
are not a font-size, contrast or accessibility certification.

The native inspector defaults to Station A in these captures. Its selector can
switch to B; other pinned/selected labels and lens positions depict static
states. Narrow radial/overlay views reflow into upright detail stacks rather
than retaining the desktop geometry. There are no measured arrival estimates
or draggable lenses in this set.

See the [gallery guide](../../../app/src/samples/README.md) to run, build and
bookmark the samples. Captures use the gallery at
`/samples.html?sample=<sample-id>`; they do not replace the production app.
This is appearance QA, not a reader study, actual-device test, screen-reader
audit or complete native keyboard/touch validation.
