# Simulation-based calibration

30 of 30 predefined synthetic datasets completed in 30 attempts. Status: **pending_independent_review**. The NTWC T-OBS exploration design has 236 approved records across 14 events. Actual reported responses were not fitted in these simulations.

All attempts remain in the diagnostics table and original local logs/chains. Posterior estimates use accepted attempts only; repairs reuse the same dataset. Unresolved datasets prevent stage acceptance. Computation under the assumed simulator does not validate physical onset, archive representativeness or predictive accuracy.

Ranks use 100 spaced draws while retaining all original chains. Rank R-hat, ESS and lag screens do not make MCMC draws exactly independent. The ECDF reference band uses DKW with a Bonferroni correction across six planned quantities (familywise 0.05 under independent uniform ranks). Its interpretation is approximate for MCMC. A crossing calls for investigation; no crossing is not proof of correctness.

Parameter meanings: alpha is the population log median/reference ratio at 1,000 km; beta changes that log ratio per unit ln(distance/1000). Tau_event and sigma are between-event and record SDs on the log-ratio scale. Event_effect_first is the first sorted event's latent log-ratio effect. Mean_response_at_5000km is alpha+beta*ln(5), the population mean log ratio, not an arithmetic mean duration.
