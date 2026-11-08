# Reported-timing prior hypotheses

These are analyst scale choices made after descriptive EDA, not expert elicitation or measured physical constraints. The three source/target lanes remain separate.

For durations, r=ln(y/t0), x=ln(d/1000), r~Normal(alpha+beta*x+tau*z,sigma), z~Normal(0,1). The fixed t0 uses 4 km depth. Base priors are alpha~Normal(0,0.5), beta~Normal(0,0.25), tau,sigma~HalfNormal(0.4). At 1,000 km and zero event effect, the central 95% interval for the conditional median/reference ratio is [0.375,2.664]; the linear total distance exponent 1+beta has interval [0.510,1.490]. These broad ranges express uncertainty in reported values, not wave-speed limits.

T-CAL uses signed minutes directly. Base alpha~Normal(0,30), beta~Normal(0,15) minutes per unit log-distance; tau,sigma~HalfNormal(30). Centering alpha at zero is a modeling hypothesis, not evidence that historical forecasts were unbiased.

Wider duration scales are 0.8/0.4/0.6/0.6; wider T-CAL scales are 60/30/60/60. Duration base priors have finite predictive first and second moments at fixed distance. The wider joint duration prior has a finite mean but infinite second moment: for a HalfNormal scale s times independent standard Normal, its MGF exists only for |t|s<1; 2*0.6>1. Quantiles, not a predictive SD, summarize this sensitivity.

The likelihood is a working continuous density for native reported point values. Display precision is retained without asserting accuracy or a rounding rule. Event variation includes unresolved clock/source/path effects; origin error is not separately identified. Sigma is composite reported-record spread. Missingness and archive selection are conditioned on, not corrected as MCAR/MAR/MNAR. Observation/coarsening and conflict-record sensitivities precede selection.

The dictionary contains 2.5% and 97.5% parameter quantiles. Non-centered z_event has a standard Normal prior; event_effect=tau_event*z_event. Alpha and beta are locations/slopes, while tau_event and sigma are SDs on the modeled response scale.

All six 2,000-draw ancestral checks produced finite predictions, with positive durations. Soft flags (ratio below 0.05/above 20, or absolute T-CAL above 180 minutes) are diagnostic yardsticks, not impossible outcomes or automatic acceptance cutoffs. Pooled-design quantiles reflect the archived distance composition. The plotted bands instead condition on distance and simulate a new event and record.

Recommendation: take the base hypotheses into simulation/recovery; retain the wider hypotheses for sensitivity. This check does not establish physical validity, identifiability, posterior convergence or predictive performance. No scientific posterior was fitted. Reproduce with the recorded inputs, seeds and CLI.
