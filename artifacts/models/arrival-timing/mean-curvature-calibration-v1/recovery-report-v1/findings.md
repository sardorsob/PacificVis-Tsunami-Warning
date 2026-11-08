# Mean-curvature recovery validation

The phase retains 50 distinct synthetic datasets, with four chains of 2,000 posterior draws after 1,000 tuning draws. All retained sampling and 21-quantity rank diagnostics passed their prespecified screens. The 1,064-record, 33-event design supplies distances and membership; generated responses supply the likelihood.

Recovery estimates are in `pointwise-coverage-and-recovery.csv`. Its error measure is the posterior median minus the generating value. The separate standardized mean-error column divides posterior-mean error by posterior SD; it is not a standard-normal test. Wilson intervals describe finite-dataset binomial uncertainty. Coverage is summarized separately for each quantity and scenario.

The median-curve band is simultaneous on the nine fixed distances, at zero event effect. It excludes event and observation noise and makes no claim between grid points. Borderline flags use uncertainty in the 90th-percentile cutoff only; they do not quantify all uncertainty in band endpoints or coverage classification.

Each of the five generating scenarios has ten fresh datasets. Coverage estimates are correspondingly imprecise. No coverage quota or rank-uniformity test is applied to these fixed-truth recovery datasets.

| Scenario | Parameter | 90% interval containment | 95% Wilson interval | Mean median error |
| --- | --- | ---: | ---: | ---: |
| combined | gamma | 8/10 | 49.0%–94.3% | -0.0168 |
| combined | tau_event | 9/10 | 59.6%–98.2% | 0.0031 |
| negative-weak | gamma | 8/10 | 49.0%–94.3% | 0.0272 |
| negative-weak | tau_event | 9/10 | 59.6%–98.2% | -0.0070 |
| null-moderate | gamma | 9/10 | 59.6%–98.2% | 0.0207 |
| null-moderate | tau_event | 9/10 | 59.6%–98.2% | -0.0244 |
| null-weak | gamma | 9/10 | 59.6%–98.2% | -0.0007 |
| null-weak | tau_event | 10/10 | 72.2%–100.0% | 0.0023 |
| positive-weak | gamma | 6/10 | 31.3%–83.2% | 0.0086 |
| positive-weak | tau_event | 9/10 | 59.6%–98.2% | 0.0030 |

Gamma is the additional curvature coefficient for the log median; tau_event is the between-event log-scale SD. Fixed-truth posterior interval containment need not equal nominal frequentist coverage at each chosen truth. These finite recovery results and the curve-band results should be read together; marginal coefficient recovery and curve recovery answer different questions.

| Generating scenario | Median-curve band coverage | 95% Wilson interval | Borderline |
| --- | ---: | ---: | ---: |
| combined | 9/10 | 59.6%–98.2% | 0 |
| negative-weak | 8/10 | 49.0%–94.3% | 1 |
| null-moderate | 7/10 | 39.7%–89.2% | 0 |
| null-weak | 10/10 | 72.2%–100.0% | 1 |
| positive-weak | 9/10 | 59.6%–98.2% | 0 |

Reproduce this report from retained files with `uv run python scripts/summarize_arrival_curvature_calibration.py --phase recovery --output artifacts/models/arrival-timing/mean-curvature-calibration-v1/recovery-report-v1` using a new output directory. No sampler is called. Confirmation outcomes were not parsed; reserved outcomes remain sealed. Historical candidate fitting requires independent acceptance of these computational checks.
