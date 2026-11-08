# Design recovery

30 of 30 predefined synthetic datasets completed in 30 attempts. Status: **pending_independent_review**. The fixed design is the primary 1,064-record NCEI exploration view, across 33 events. Actual reported durations were not fitted.

All attempts remain in the diagnostics table and original local logs/chains. Posterior estimates use accepted attempts only; repairs reuse the same dataset. Unresolved datasets prevent stage acceptance. Computation under the assumed simulator does not validate physical onset, archive representativeness or predictive accuracy.

Coverage is the fraction of generating values inside central posterior 90% intervals; Wilson 95% intervals describe independent simulation-replicate uncertainty. With 30 datasets these estimates are noisy. At tau=0 a positive equal-tailed interval cannot contain the boundary: use the reported posterior 95% upper bound. The five-minute additive stress changes the response-generating mechanism and is reported separately from correct-model coverage. Width contraction is 1 minus mean posterior central-90% width / analytic prior central-90% width, not variance contraction.
Standardized mean error z=(posterior mean−truth)/posterior SD; this is a descriptive recovery diagnostic, not a Normal-test statistic.

Parameter meanings: alpha is the population log median/reference ratio at 1,000 km; beta changes that log ratio per unit ln(distance/1000). Tau_event and sigma are between-event and record SDs on the log-ratio scale. Event_effect_first is the first sorted event's latent log-ratio effect. Mean_response_at_5000km is alpha+beta*ln(5), the population mean log ratio, not an arithmetic mean duration.

Across the core parameters in correctly specified scenarios, coverage ranges from 86.7% to 96.7%. This range spans multiple noisy comparisons; it is not an automatic identification certificate.

| Setting | Parameter | Mean error | Coverage (90% interval) | 95% reference uncertainty |
| --- | --- | ---: | ---: | --- |
| combined-weak-event-large-spread | alpha | -0.0005 | 96.7% | 83.3%–99.4% |
| combined-weak-event-large-spread | beta | -0.0010 | 93.3% | 78.7%–98.2% |
| combined-weak-event-large-spread | sigma | 0.0017 | 86.7% | 70.3%–94.7% |
| combined-weak-event-large-spread | tau_event | 0.0101 | 90.0% | 74.4%–96.5% |
