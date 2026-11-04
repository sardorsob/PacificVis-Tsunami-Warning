# Arrival-timing EDA: a guide for Bayesian modeling

Start here to understand the distributions, the observation process, and which
parts of a future Bayesian model the evidence can inform. Folders and filenames describe the response and diagnostic. The `C1`–`C9`
and `B1`–`B11` IDs remain in the registration and run metadata so the original
questions can still be traced.

The [results report](arrival-timing-findings.md) contains the findings and their limitations. Its
[decision memo](arrival-timing-findings.md#decision-memo-for-later-modeling) connects the findings
to possible modeling choices. The [complete figure index](figure-and-table-index.md) lists all
71 figure sets. The guide below gives those outputs descriptive names and a
reading order.

## Find the scientific question

The links in this table use the exploration sample. The report compares these
findings with the frozen confirmation sample and marks weak evidence tentative.

| What you want to learn | Where to look | How it informs modeling |
| --- | --- | --- |
| What do reported travel durations look like? | [NTWC log-duration histogram](results/exploration/travel-duration-distributions-and-clock-precision/ntwc-reported-travel-duration-log-minutes-histogram.png), [NCEI log-duration histogram](results/exploration/travel-duration-distributions-and-clock-precision/ncei-native-travel-duration-log-minutes-histogram.png), and [duration quantiles and robust spread](results/exploration-response-quantiles-and-robust-spread.csv) | Outcome support, transformation, and observable scales. These mix distances and events; their spread is not conditional model noise. |
| What do estimated-minus-observed differences look like? | [Signed timing-difference histogram](results/exploration/estimated-minus-observed-timing-distributions/estimated-minus-observed-time-difference-minutes-histogram.png), [normal-reference QQ plot](results/exploration/estimated-minus-observed-timing-distributions/estimated-minus-observed-time-difference-minutes-normal-quantile-plot.png), and [timing differences by event](results/exploration/estimated-minus-observed-timing-distributions/estimated-minus-observed-time-difference-by-event.csv) | A signed response, its location and spread, asymmetry, and event composition. |
| How much timing structure does distance explain? | [Reported duration versus distance](results/exploration/distance-and-fixed-depth-travel-time-reference/ntwc-reported-travel-duration-versus-distance-and-fixed-depth-reference.png), [NTWC departure from a fixed-depth reference](results/exploration/distance-and-fixed-depth-travel-time-reference/ntwc-reported-travel-duration-log-reference-departure-by-distance-band.png), and [NCEI departure from that reference](results/exploration/distance-and-fixed-depth-travel-time-reference/ncei-native-travel-duration-log-reference-departure-by-distance-band.png) | Distance trend, near-field behavior, and possible reference offsets. The fixed reference is a diagnostic approximation. |
| Does spread change with distance? | [NTWC spread within distance bands](results/exploration/distance-and-precision-dependent-spread/ntwc-reported-travel-duration-distance-spread.csv) and [NCEI spread within distance bands](results/exploration/distance-and-precision-dependent-spread/ncei-native-travel-duration-distance-spread.csv) | Whether a constant conditional scale may be too restrictive. Unmodeled propagation differences can also produce this pattern. |
| Is there evidence for event and station variation? | [Event departures in NCEI durations](results/exploration/event-and-station-timing-variation/ncei-native-travel-duration-component-relative-event-log-timing-effects.png), [station departures](results/exploration/event-and-station-timing-variation/ncei-native-travel-duration-component-relative-station-log-timing-effects.png), and [repeated-site support](arrival-timing-findings.md#repeated-site-and-holdout-support) | Whether event/station terms have support, and where their scales may be difficult to identify. Median-polish effects are descriptive decompositions. |
| What affects whether a usable timestamp is present? | [Exact-time availability by era](results/exploration/observed-timestamp-availability/observed-utc-availability-by-reporting-era.png), [availability by source format](results/exploration/observed-timestamp-availability/observed-utc-availability-by-source-table-format.csv), and [original-source reporting and failure evidence](../../../docs/data/source-process.md) | The observation/reporting layer and selection sensitivities. These do not identify MCAR, MAR or MNAR. |
| How trustworthy are the clock precision and extreme values? | [Clock and duration precision summaries](results/exploration/travel-duration-distributions-and-clock-precision/descriptive-statistics.json), [NTWC flagged cases with source-review status](results/exploration/extreme-timing-departures-and-source-review/ntwc-reported-travel-duration-extreme-departures-and-original-source-review.csv), and [NCEI flagged cases](results/exploration/extreme-timing-departures-and-source-review/ncei-native-travel-duration-extreme-departures-and-original-source-review.csv) | Measurement precision, origin sensitivity, and definition uncertainty. A flagged tail is not proof of a bad observation or a mixture component. |
| Can the two archives measure the same latent arrival? | [Unapproved geographic comparison sensitivity](results/exploration/source-definitions-and-arrival-comparability/unapproved-same-name-2km-duration-differences.png) and [comparison records and identity limitations](results/exploration/source-definitions-and-arrival-comparability/unapproved-same-name-2km-comparison-records.csv) | Source compatibility and shared ancestry. There are no approved direct cross-family comparisons; the sensitivity has 56 exploration comparisons and zero confirmation comparisons. |
| Are conclusions dominated by a few events? | [NTWC event-deletion influence table](results/exploration/event-concentration-and-deletion-influence/ntwc-reported-travel-duration-leave-one-event-out.csv), [NCEI influence table](results/exploration/event-concentration-and-deletion-influence/ncei-native-travel-duration-leave-one-event-out.csv), and [event concentration](results/response-distributions-and-event-station-support.csv) | Sensitivity to event composition and appropriate evaluation groups. Large relative changes may have nearly zero baselines. |
| Do estimated-minus-observed differences change with distance? | [Signed timing difference versus distance](results/exploration/estimated-minus-observed-timing-distributions/estimated-minus-observed-time-difference-versus-source-station-distance.png) and [within-event distance associations](results/exploration/within-event-timing-difference-distance-associations/estimated-minus-observed-time-difference-within-event-event-distance.csv) | A possible distance term in the forecast-comparison model. Confirmation has only two usable event-level associations, so this remains tentative. |

Every linked plot has a same-name CSV and SVG beside it. The CSV preserves the
plotted values and IDs; the SVG is the vector figure.

## Keep the three response variables distinct

| Reader name | Internal ID | Definition | Consequence for the model |
| --- | --- | --- | --- |
| NTWC reported travel duration | `T-OBS` | Reported observed UTC minus a reviewed USGS origin | A positive elapsed duration with uncertainty about the reporting definition, clock accuracy, and appropriate original origin. |
| NCEI native reported travel duration | `NCEI-native-duration` | The positive travel duration explicitly supplied by NCEI | Preserve its own source definition. It is not a reconstructed historical forecast or an independent NTWC observation. |
| Signed estimated-minus-observed timing difference | `T-CAL` | Estimated UTC minus reported observed UTC | Values can be negative or positive. Negative means the estimate precedes the reported observation. |

The complete accepted views contain 258 NTWC durations, 1,221 NCEI native
durations, and 169 signed timing differences. The descriptive exploration scales
below use their designated exploration subsets.

| Response | Exploration records / events | 10th percentile (min) | Median (min) | 90th percentile (min) | MAD (min) |
| --- | ---: | ---: | ---: | ---: | ---: |
| NTWC reported travel duration | 236 / 14 | 64.60 | 440.01 | 1,064.07 | 316.06 |
| NCEI native reported travel duration | 1,070 / 33 | 66.00 | 429.00 | 1,038.20 | 299.00 |
| Signed estimated-minus-observed difference | 156 / 13 | −51.00 | −15.50 | 3.50 | 13.50 |

Source: [exploration observable scales](results/exploration-response-quantiles-and-robust-spread.csv)
and [target counts and summaries](results/response-distributions-and-event-station-support.csv). MAD is the
unscaled median absolute deviation. These are sample summaries. For example,
the 13.5-minute MAD is not an estimate of a Bayesian model's standard deviation.

## A histogram is only one part of the distribution question

The duration histograms show the distribution across the sampled distances,
events and stations. A later arrival model would describe something like
`p(reported duration | distance, event, station, reporting definition)`.
The shape of that conditional distribution can differ from the pooled histogram.

The distance diagnostics therefore also examine
`r0 = ln(reported duration / fixed-reference duration)`. This helps reveal
structure left after a simple distance reference. The reference assumes a
straight geodesic path and a constant 4,000 m depth; its departures combine
unmodeled propagation, source geometry, measurement definitions and reporting
effects. They cannot all be assigned to random observation noise.

The current memo leaves positive log-scale and robust candidates open for the
duration targets, and signed candidates open for the timing-difference target.
Neither the histograms nor the QQ plots select a likelihood. Tail shape,
conditional scale and event/station variation still require an explicit model
and checks of whether its parameters can be learned from this design.

## Which parameters does the EDA inform?

The names below are a vocabulary for reading the evidence, not a selected model
or a list of estimated parameters. Their units and interpretation depend on the
eventual response scale and model specification.

| Possible model quantity | Meaning | Relevant evidence | Current limit |
| --- | --- | --- | --- |
| Distance function `f(distance)` and near-field term `beta_near` | How expected reported timing changes with distance | Fixed-reference departures and distance bins (`C3`, `B1`, `B9`) | NCEI near-field departure repeats. NTWC confirmation has only one near-field record. |
| Conditional scale `sigma`, possibly varying with distance | Remaining spread after explaining the mean structure | Within-band spread and precision groups (`B5`) | Raw-duration MAD and fixed-reference MAD are not identified noise scales; propagation and reporting effects remain mixed. |
| Event variation `tau_event` | Variation between events after other modeled structure | Component-relative event effects and event deletion (`C4`, `B4`, `C7`) | Descriptive event/residual ratios are unstable and sensitive to the connected component. |
| Station variation `tau_site` | Persistent differences between repeatedly observed stations | Station effects, repeated-site counts, and holdout support (`C4`, `B3`, `C9`) | Degenerate residual spread and many invalid bootstrap ratios prevent a stable variance-component claim. |
| Timing-difference location `mu_cal` and distance term `beta_cal` | Expected signed estimate-minus-observation difference | Signed distributions, event summaries, and within-event distance associations (`C8`, `B10`) | Pooled median −15.5 min is descriptive; it is not a fitted conditional bias. Distance evidence is sparse in confirmation. |
| Tail-shape quantity, such as `nu` if a Student-t family is later chosen | How a specified likelihood handles unusually large departures | QQ diagnostics and original-source tail review (`C2`, `B2`) | No tail parameter is estimated, and the source checks do not establish that extreme values are errors. |
| Reporting/selection coefficients `gamma` | Association between recorded features and usable-time availability | Era/format availability and documentary reporting evidence (`C6`, `B7`) | The archive is not a station-operation census; dependence on unobserved arrival values remains unidentified. |
| Observation precision or interval width `delta_time` | Rounding, origin uncertainty, and timestamp accuracy | Native clock fields and origin comparisons (`C1`, `C2`) | Minute display does not establish minute accuracy. An interval width cannot be assigned from display format alone. |
| Cross-source offset or dependence terms | Differences between products and shared measurement ancestry | Definition review and geographic comparison sensitivity (`C5`, `B6`, `B11`, `P1`) | Compatible arrivals and independent source measurements have not been established; an unmatched coastal/DART contrast is not a source-bias estimate. |

## How does a row arise?

This is a working decomposition for interpreting the evidence. It is not a
validated causal model of every warning center or station.

1. **Physical and measurement branch:** earthquake source and ocean path affect
   a physical wave at a location. A sensor records a water-level series. A
   reported arrival then depends on the chosen arrival definition, measurement
   conditions and timing practices. The accepted tables do not validate the
   physical onset for each row.
2. **Forecast branch:** the issuing center uses information available at a
   particular issue time, model and product version to publish an estimate.
   That estimate has its own provenance; it cannot be reconstructed from a
   later observation or a forecast from a different product.
3. **Publication and archive branch:** reporting rules, received information,
   station coverage and preservation determine which values reach a table.
   The [source-process evidence](../../../docs/data/source-process.md) supports
   some policies and links four absent observations to documented gaps.
   Most individual missing-value causes remain unknown.
4. **Processing branch:** the pipeline preserves raw cells and evaluates their
   column meaning, calendar/time basis and geographic identity. The selected
   response then requires the relevant evidence. A retained raw row can exist
   without meeting those requirements; absence from a modeling view is not the
   same as absence from the source table.

This decomposition explains why the EDA includes more than distributions:
measurement definitions, selection and shared sources affect what a Bayesian
likelihood would mean. The current evidence supports a description of reported
timings more directly than a claim to have recovered true physical arrivals.

## Decode the internal question IDs

| ID | Descriptive name |
| --- | --- |
| `C1` | Target definitions, joins, counts, and integrity |
| `C2` | Duration distributions, quantiles, QQ plots, and clock precision |
| `C3` | Distance and departures from the fixed-depth reference |
| `C4` | Component-relative event and station effects |
| `C5` | Source definitions and cross-source comparability |
| `C6` | Availability of usable observed UTC timestamps |
| `C7` | Event concentration and leave-one-event-out influence |
| `C8` | Signed estimated-minus-observed distributions and associations |
| `C9` | Repeated-site support, connected components, and holdout feasibility |
| `B1` / `B9` | Distance/near-field follow-ups; these reuse the selected near−far contrast |
| `B2` | Extreme departures and original-source checks |
| `B3` / `B4` | Station-effect stability / event-effect variation |
| `B5` | Changing spread across distance or precision groups |
| `B6` | Within-event source/family/tier duration contrasts |
| `B7` | Era/format/peak-related availability follow-up |
| `B8` | Sensitivity of descriptive summaries to removing an event |
| `B10` | Within-event distance associations for signed timing differences |
| `B11` | Whether cross-source comparisons identify a common arrival target |
| `P1` | Posthoc, unapproved same-name bounded-2-km comparison sensitivity |

The numerical outputs remain the frozen analysis record. Descriptive paths and
the rename manifest preserve their identity and interpretation.

## File organization and provenance

`results/exploration/` and `results/confirmation/` contain the same scientific
questions under descriptive subject folders. `preliminary-checkpoint/` contains
the earlier integrity, distribution and distance checks. `frozen-inputs/`
contains the source checksums, event metadata and registered questions.

Within each subject, the filenames identify the response, grouping or statistic.
`descriptive-statistics.json` contains summaries; `analysis-metrics.json` records
the numerical diagnostics; `detailed-findings.md` supplies their full context.
`original-run-metadata.json` and `generation-input-and-code-checksums.json`
preserve the original execution record. `output-file-checksums.json` indexes the
current filenames. The confirmation definition separately pins the layout-aware
replay code, so renaming cannot silently change the recorded generation code.

[File renames and content checksums](file-renames-and-content-checksums.json)
resolves every old path in historical run evidence and records before/after
hashes. Renaming did not change any scientific CSV, figure, statistical result,
registered question, source input, or split assignment.
