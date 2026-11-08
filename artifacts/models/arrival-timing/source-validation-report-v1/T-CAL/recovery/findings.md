# Design recovery

30 of 30 predefined synthetic datasets completed in 30 attempts. Status: **pending_independent_review**. The NTWC T-CAL exploration design has 156 approved records across 13 events. Actual reported responses were not fitted in these simulations.

All attempts remain in the diagnostics table and original local logs/chains. Posterior estimates use accepted attempts only; repairs reuse the same dataset. Unresolved datasets prevent stage acceptance. Computation under the assumed simulator does not validate physical onset, archive representativeness or predictive accuracy.

Coverage is the fraction of generating values inside central posterior 90% intervals; Wilson 95% intervals describe independent simulation-replicate uncertainty. These finite-replicate estimates are noisy. At tau=0 a positive equal-tailed interval cannot contain the boundary: use the reported posterior 95% upper bound. Any additive-time stress changes the response-generating mechanism and is reported separately from correct-model coverage. Width contraction is 1 minus mean posterior central-90% width / analytic prior central-90% width, not variance contraction.
Standardized mean error z=(posterior mean−truth)/posterior SD; this is a descriptive recovery diagnostic, not a Normal-test statistic.

Parameter meanings: alpha is population signed estimate-minus-observation minutes at 1,000 km; beta changes that mean per unit ln(distance/1000). Tau_event and sigma are between-event and record SDs in minutes. Event_effect_first is the first sorted event's latent minute effect. Mean_response_at_5000km is alpha+beta*ln(5), a signed-minute population mean. This retrospective archive discrepancy is not operational warning performance.

Across the core parameters in correctly specified scenarios, coverage ranges from 70.0% to 100.0%. This range spans multiple noisy comparisons; it is not an automatic identification certificate.

| Setting | Parameter | Mean error | Coverage (90% interval) | 95% reference uncertainty |
| --- | --- | ---: | ---: | --- |
| combined-weak-event-large-spread | alpha | -1.0585 | 80.0% | 49.0%–94.3% |
| combined-weak-event-large-spread | beta | 0.6194 | 100.0% | 72.2%–100.0% |
| combined-weak-event-large-spread | sigma | -0.0928 | 70.0% | 39.7%–89.2% |
| combined-weak-event-large-spread | tau_event | 3.9276 | 100.0% | 72.2%–100.0% |
| no-event-variation | alpha | 1.4301 | 90.0% | 59.6%–98.2% |
| no-event-variation | beta | -0.2812 | 70.0% | 39.7%–89.2% |
| no-event-variation | sigma | -0.8177 | 70.0% | 39.7%–89.2% |
| no-event-variation | tau_event | 4.1971 | Boundary: upper bound | — |
| reference | alpha | 0.8254 | 90.0% | 59.6%–98.2% |
| reference | beta | -0.6618 | 90.0% | 59.6%–98.2% |
| reference | sigma | 0.2705 | 90.0% | 59.6%–98.2% |
| reference | tau_event | 1.1535 | 80.0% | 49.0%–94.3% |
