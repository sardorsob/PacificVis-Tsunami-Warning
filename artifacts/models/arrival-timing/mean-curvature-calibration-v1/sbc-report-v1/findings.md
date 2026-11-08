# Mean-curvature sbc validation

The phase retains 100 distinct synthetic datasets, with four chains of 2,000 posterior draws after 1,000 tuning draws. All retained sampling and 21-quantity rank diagnostics passed their prespecified screens. The 1,064-record, 33-event design supplies distances and membership; generated responses supply the likelihood.

Recovery estimates are in `pointwise-coverage-and-recovery.csv`. Its error measure is the posterior median minus the generating value. The separate standardized mean-error column divides posterior-mean error by posterior SD; it is not a standard-normal test. Wilson intervals describe finite-dataset binomial uncertainty. Coverage is summarized separately for each quantity and scenario.

The median-curve band is simultaneous on the nine fixed distances, at zero event effect. It excludes event and observation noise and makes no claim between grid points. Borderline flags use uncertainty in the 90th-percentile cutoff only; they do not quantify all uncertainty in band endpoints or coverage classification.

Each truth is drawn independently from the frozen base prior. Final rank checks use the discrete uniform reference on integers 0 through 100 and a 21-quantity DKW union bound at family alpha 0.05. Correlations among quantities are allowed by the union bound. The 100 spaced posterior states per rank approximate independent draws; they are not 100 effective samples. The independent replication count is 100 datasets, not 2,100 parameter estimates.

Final rank screens exceeded: 0 of21. A screen diagnoses computational calibration under the assumed model; passing does not establish physical correctness or predictive superiority.

| Scenario | Parameter | 90% interval containment | 95% Wilson interval | Mean median error |
| --- | --- | ---: | ---: | ---: |
| prior-generated | gamma | 91/100 | 83.8%–95.2% | 0.0058 |
| prior-generated | tau_event | 93/100 | 86.3%–96.6% | -0.0029 |

Gamma is the additional curvature coefficient for the log median; tau_event is the between-event log-scale SD. Fixed-truth posterior interval containment need not equal nominal frequentist coverage at each chosen truth. These finite recovery results and the curve-band results should be read together; marginal coefficient recovery and curve recovery answer different questions.

| Generating scenario | Median-curve band coverage | 95% Wilson interval | Borderline |
| --- | ---: | ---: | ---: |
| prior-generated | 89/100 | 81.4%–93.7% | 2 |

Reproduce this report from retained files with `uv run python scripts/summarize_arrival_curvature_calibration.py --phase sbc --output artifacts/models/arrival-timing/mean-curvature-calibration-v1/sbc-report-v1` using a new output directory. No sampler is called. Confirmation outcomes were not parsed; reserved outcomes remain sealed. Historical candidate fitting requires independent acceptance of these computational checks.
