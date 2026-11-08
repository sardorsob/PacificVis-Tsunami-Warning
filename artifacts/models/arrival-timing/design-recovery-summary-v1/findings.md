# Design recovery

270 of 270 predefined synthetic datasets completed in 270 attempts. Status: **pending_independent_review**. The fixed design is the primary 1,064-record NCEI exploration view, across 33 events. Actual reported durations were not fitted.

All attempts remain in the diagnostics table and original local logs/chains. Posterior estimates use accepted attempts only; repairs reuse the same dataset. Unresolved datasets prevent stage acceptance. Computation under the assumed simulator does not validate physical onset, archive representativeness or predictive accuracy.

Coverage is the fraction of generating values inside central posterior 90% intervals; Wilson 95% intervals describe independent simulation-replicate uncertainty. With 30 datasets these estimates are noisy. At tau=0 a positive equal-tailed interval cannot contain the boundary: use the reported posterior 95% upper bound. The five-minute additive stress changes the response-generating mechanism and is reported separately from correct-model coverage. Width contraction is 1 minus mean posterior central-90% width / analytic prior central-90% width, not variance contraction.
Standardized mean error z=(posterior mean−truth)/posterior SD; this is a descriptive recovery diagnostic, not a Normal-test statistic.

Parameter meanings: alpha is the population log median/reference ratio at 1,000 km; beta changes that log ratio per unit ln(distance/1000). Tau_event and sigma are between-event and record SDs on the log-ratio scale. Event_effect_first is the first sorted event's latent log-ratio effect. Mean_response_at_5000km is alpha+beta*ln(5), the population mean log ratio, not an arithmetic mean duration.

Across the core parameters in correctly specified scenarios, coverage ranges from 76.7% to 100.0%. This range spans multiple noisy comparisons; it is not an automatic identification certificate.

| Setting | Parameter | Mean error | Coverage (90% interval) | 95% reference uncertainty |
| --- | --- | ---: | ---: | --- |
| combined-weak-event-large-spread | alpha | -0.0127 | 93.3% | 78.7%–98.2% |
| combined-weak-event-large-spread | beta | 0.0026 | 80.0% | 62.7%–90.5% |
| combined-weak-event-large-spread | sigma | -0.0028 | 76.7% | 59.1%–88.2% |
| combined-weak-event-large-spread | tau_event | 0.0111 | 96.7% | 83.3%–99.4% |
| larger-record-spread | alpha | 0.0030 | 96.7% | 83.3%–99.4% |
| larger-record-spread | beta | 0.0010 | 93.3% | 78.7%–98.2% |
| larger-record-spread | sigma | -0.0006 | 96.7% | 83.3%–99.4% |
| larger-record-spread | tau_event | 0.0146 | 90.0% | 74.4%–96.5% |
| material-distance-adjustment | alpha | -0.0015 | 86.7% | 70.3%–94.7% |
| material-distance-adjustment | beta | 0.0043 | 80.0% | 62.7%–90.5% |
| material-distance-adjustment | sigma | 0.0021 | 90.0% | 74.4%–96.5% |
| material-distance-adjustment | tau_event | 0.0024 | 90.0% | 74.4%–96.5% |
| no-distance-adjustment | alpha | -0.0073 | 93.3% | 78.7%–98.2% |
| no-distance-adjustment | beta | -0.0009 | 90.0% | 74.4%–96.5% |
| no-distance-adjustment | sigma | 0.0003 | 90.0% | 74.4%–96.5% |
| no-distance-adjustment | tau_event | 0.0018 | 93.3% | 78.7%–98.2% |
| no-event-variation | alpha | -0.0005 | 93.3% | 78.7%–98.2% |
| no-event-variation | beta | 0.0001 | 93.3% | 78.7%–98.2% |
| no-event-variation | sigma | -0.0026 | 83.3% | 66.4%–92.7% |
| no-event-variation | tau_event | 0.0179 | Boundary: upper bound | — |
| reference | alpha | 0.0030 | 90.0% | 74.4%–96.5% |
| reference | beta | 0.0018 | 90.0% | 74.4%–96.5% |
| reference | sigma | 0.0015 | 86.7% | 70.3%–94.7% |
| reference | tau_event | 0.0034 | 96.7% | 83.3%–99.4% |
| reported-time-addition-stress | alpha | 0.1085 | 10.0% | 3.5%–25.6% |
| reported-time-addition-stress | beta | -0.0474 | 0.0% | 0.0%–11.4% |
| reported-time-addition-stress | sigma | -0.0064 | 70.0% | 52.1%–83.3% |
| reported-time-addition-stress | tau_event | -0.0078 | 90.0% | 74.4%–96.5% |
| strong-event-variation | alpha | -0.0028 | 100.0% | 88.6%–100.0% |
| strong-event-variation | beta | 0.0012 | 83.3% | 66.4%–92.7% |
| strong-event-variation | sigma | 0.0011 | 90.0% | 74.4%–96.5% |
| strong-event-variation | tau_event | -0.0026 | 96.7% | 83.3%–99.4% |
| weak-event-variation | alpha | -0.0045 | 90.0% | 74.4%–96.5% |
| weak-event-variation | beta | 0.0007 | 90.0% | 74.4%–96.5% |
| weak-event-variation | sigma | 0.0010 | 86.7% | 70.3%–94.7% |
| weak-event-variation | tau_event | 0.0037 | 96.7% | 83.3%–99.4% |
