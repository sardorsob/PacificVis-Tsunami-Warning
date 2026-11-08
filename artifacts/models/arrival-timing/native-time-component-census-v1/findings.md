# Native reported time-component consistency

This census applies one posthoc rule to every frozen exploration NCEI duration record. It tests internal agreement of source time-of-day fields and reported duration, using the pinned NCEI origin rather than the USGS origin. It does not validate physical arrival accuracy.

| Cohort | Records | Assessed | Unassessed | Flagged above 60 min |
| --- | ---: | ---: | ---: | ---: |
| all_exploration | 1070 | 1056 | 14 | 4 |
| primary | 1064 | 1050 | 14 | 4 |

The signed residual is ((arrival time of day − source time of day − reported duration + 720) mod 1440) − 720 minutes, in [−720,720). Arrival day is checked for range only; no arrival month, year or absolute date is inferred. Explicit complete valid components are required. Missing components remain unassessed.

The 60-minute threshold is a posthoc triage choice, not an accuracy tolerance or rounding assumption. Small residuals can hide whole-day discrepancies, compensating errors or incorrect event association. Flags identify cases for sensitivity analysis and source clarification; they establish neither cause nor corrected values.

The rule was recorded after the influential LATA 1,125-minute case was traced. The census retains all original values and all six rows already excluded from the primary model view in their original roles. No missing forecast/observation pair is recovered.

Raw page hashes and all event/request metadata are checked before any selected raw JSON is parsed. Only pages belonging to frozen exploration events are read. Native item IDs are bound by immutable page hash and frozen one-based item position; the exploration table contains no independent native item-ID column. The 19 previously inspected confirmation outcomes and 18 reserved outcomes are not parsed.

Source: NOAA/NCEI historical tsunami catalog, retained HaZEL runup responses. [Field definitions](https://data.noaa.gov/metaview/page?view=xml2text/xml-to-text-ISO&xml=NOAA/NESDIS/NGDC/MGG/Hazards/iso/xml/G02151.xml).

Reproduce: `uv run --locked --offline python scripts/audit_arrival_source_components.py --output <new-project-path>`. Exact inputs accompany this census.
