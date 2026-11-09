# Sensitivity of reported arrival durations

The NCEI linear 2014-onward sensitivity remains computationally unresolved after two failed attempts. Its original run had 30 divergences; the reviewed numerical attempt retained one divergence among 8,000 draws and failed the unchanged zero-divergence screen. No third attempt is authorized. Neither attempt supplies posterior parameters, curves or predictive checks. This leaves a gap in the linear-model stress checks: the available results cannot establish robustness for this comparison or be used to favor curvature. Its 150 original observations remain in the other applicable fits and full-data analyses; this disposition deletes no data. The curved 2014-onward fit became usable only after its final numerical repair. Its availability does not resolve the missing linear comparison or establish an era advantage.

This exploration report contains 54 usable fits and 14 historical posterior views (eight full base fits and six sequence-deletion training fits). The controller charged 58 calls within a 110-call ceiling. Historical views require no new fits.

T-OBS is reported observed UTC minus the reviewed USGS origin: a positive reported travel duration. T-CAL is reported estimated UTC minus reported observed UTC: a signed archive discrepancy, distinct from travel duration. Positive T-CAL means the estimate was later than the observation; negative T-CAL means the estimate was earlier. These definitions retain the reviewed source observation and forecast calendar contexts; they do not establish physical onset or independent timestamp accuracy.

## What the tables show

Each source and mean form has its own base comparison. Positive-duration changes are log shifts and native median ratios; signed T-CAL changes are absolute minutes. Changes subtract marginal posterior medians, without pretending they are paired posterior differences or assigning them difference intervals.

The curve table contains 858 supported typed intervals; 429 of 612 change cells lie within both training-distance ranges. Unsupported change cells are blank. For publisher distances, a numeric km grid comparison is conditional on that alternative distance definition, not a matched-site prediction.

There are 1157 observed quantile checks outside their replicated 90% bounds among 2040 checks across all 68 usable views. These dependent, partly overlapping in-sample checks are descriptive; their count is not a calibration test or a model ranking.

The following spans describe supported grid-cell changes across the scenarios in each row. They are descriptive spans, not uncertainty intervals or materiality thresholds; exact scenario results are in the change table.

| Source | Mean form | Sensitivities | Supported cells | Median-change span |
| --- | --- | --- | ---: | --- |
| NCEI-native-duration | distance-scale | Prior assumptions | 28 | -0.003939 to 0.0001317 log units |
| NCEI-native-duration | distance-scale | Data stresses and sequence deletions | 91 | -0.02516 to 0.3307 log units |
| NCEI-native-duration | mean-curvature | Prior assumptions | 35 | -0.0119 to 0.01424 log units |
| NCEI-native-duration | mean-curvature | Data stresses and sequence deletions | 96 | -0.06914 to 0.3983 log units |
| T-OBS | pooled | Prior assumptions | 24 | -0.0005281 to 0.001061 log units |
| T-OBS | distance | Prior assumptions | 24 | -0.002741 to 0.008551 log units |
| T-OBS | event | Prior assumptions | 24 | -0.006119 to 0.003639 log units |
| T-CAL | pooled | Prior assumptions | 20 | -0.05035 to 0.0649 minutes |
| T-CAL | distance | Prior assumptions | 20 | -0.1135 to 0.1408 minutes |
| T-CAL | event | Prior assumptions | 20 | -0.549 to 0.7106 minutes |

## Interpretation and limits

These are source-specific reported-data sensitivities, conditional on reporting; they do not identify physical first arrival or actionable warning time.

Population median 90% posterior bands describe parameter uncertainty. New-event report 90% predictive quantiles include event and report variation; they are a different type.

Predictive summaries use 800 simulated draws and finite posterior draws. Tiny changes are not automatically material; interval overlap establishes neither equivalence nor a winner.

In the current NCEI base-report views, observed quantiles fall outside the conditional replicated 90% interval in 11/15 modeled-response and 10/15 native checks for the linear form, and 8/15 modeled-response and 9/15 native checks for the curved form. These overlapping in-sample checks do not rank held-out performance. The 1,125-minute LATA report remains a hard case in the full cohorts.

Conditional checks use fitted events and are in-sample model criticism, not held-out validation. Finite autocorrelation calibration checks do not establish physical validity.

Matched Student-t4 population priors change priors, not the Normal residual likelihood. Positive-native predictive means and variances can be infinite even under a posterior; only medians and quantiles are reported, with log-space validity retained.

Priors are analyst choices informed by exploration, not expert facts. Era and omission stresses do not correct values or identify selection or missingness; omitting short rows does not fit a truncated population or a verified rounding model.

Publisher distance units are km, but its algorithm is unknown. All dependent response, reference and predictor quantities change coherently; native durations and IDs stay fixed.

The 1/2/5-km site keys preserve the mask and likelihood without a retained site effect; this does not demonstrate the absence of site effects. T-CAL lineage is unknown; independent cross-source pooling is not justified.

Changes are compared within source and form on the common training-distance range only. This range check does not prove dense coverage between endpoints or geographic transfer. Changed cohorts receive no ELPD ranking, Bayes factor or new model selection.

The 19-event development check is not revisited; 18 reserved outcomes remain sealed. This report remains pending independent scientific and figure review.

## Reproduce and inspect

Run `uv run --locked --offline python scripts/summarize_arrival_completed_sensitivities.py --output <new-project-local-directory>` after the complete independent computation review exists. The reader checks all 58 attempt proofs and the unresolved dispositions, raw posterior bindings, source and reference closures before any scientific loading.

Reference predictive seeds are 2916110800 + 1000 × descriptor order, with 800 draws. New cases retain their accepted seeded summaries. Exact inputs and source credits are retained in [inputs](inputs.json) and [reference provenance](reference-provenance.json). NCEI native reported durations and NTWC T-OBS/T-CAL remain separate targets.

Tables: [posterior-parameters](posterior-parameters.csv), [population-median-and-predictive-quantiles](population-median-and-predictive-quantiles.csv), [supported-distance-sensitivity-changes](supported-distance-sensitivity-changes.csv), [conditional-predictive-checks](conditional-predictive-checks.csv), [training-cohorts-and-omissions](training-cohorts-and-omissions.csv).

Figures: [prior curves](prior-population-median-curves.png) and [NCEI data stresses](ncei-data-stress-log-changes.png); matching SVG files are supplied.
Inspect these multi-panel figures at full size or zoom the SVG; a 600-pixel thumbnail does not preserve their label sizes. The prior figure has eight source/form facets, log-distance axes, log-duration axes for positive targets and signed-minute axes for T-CAL. The NCEI heatmaps have 14 data/deletion scenarios and nine distance cells per form; unsupported cells are gray and colors encode signed log changes around zero.

## Numerical computation and call accounting

All 55 planned probes have recorded dispositions: 54 usable sensitivity fits and 1 computationally unresolved case(s). They required 58 sampler calls, including 4 retained failures. The pre-2007 NCEI linear fit succeeded after its separately reviewed repair using 2,000 tuning steps and target_accept=0.99. Both attempts for the 2014-onward linear fit failed diagnostics; no third attempt is permitted. The curved 2014-onward first attempt also failed; its one final numerical attempt used 4,000 tuning steps and target_accept=0.999. The first attempts of original cases37..54 and the unsuccessful second linear attempt used 2,000 tuning steps and target_accept=0.99. All numerical attempts retain four chains and 2,000 retained draws. Original models, priors, masks, cohorts and seeds are unchanged. These are not independent repeat experiments. Predictive summaries retain original seed + 1 and 800 draws. Failed outputs contribute no posterior draws to the 68 usable report views. Accepted-case summaries rely on independent scientific review and fresh complete producer bytes; the 14 historical reference summaries are recomputed. No native data were changed or imputed.
