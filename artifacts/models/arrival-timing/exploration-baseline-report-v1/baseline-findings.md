# Initial models of NCEI reported durations

Three exploration models use the same 1,064 approved records from 33 events: a pooled log reference ratio, a distance adjustment, and a distance adjustment with partially pooled event effects. All numerical screens passed. These are exploratory development fits; the review receipt records what was independently verified. No held-out score or model selection has been computed. The 18 reserved outcomes remain sealed.

The reference uses epicenter distance and a fixed four-kilometer-depth speed. Reported-duration definitions and clock/source effects are composite. Neither the distance exponent nor an event offset identifies a physical wave speed or delay. The event population center has a different interpretation/weighting from a pooled record center; a change in alpha between these fits is not an observed forecast bias.

| Model | Alpha, log ratio (central 90%) | Beta (central 90%) | Event SD (central 90%) | Record SD (central 90%) |
| --- | --- | --- | --- | --- |
| pooled | 0.170 [0.147, 0.192] | fixed zero | fixed zero | 0.455 [0.439, 0.471] |
| distance | 0.364 [0.337, 0.392] | -0.168 [-0.184, -0.152] | fixed zero | 0.400 [0.387, 0.415] |
| event | 0.443 [0.333, 0.575] | -0.142 [-0.160, -0.125] | 0.352 [0.220, 0.510] | 0.376 [0.362, 0.391] |

Predictive checks replicate reports at the observed distances, conditional on fitted events. The plotted intervals describe variation in replicated sample quantiles, not credible intervals for a mean and not new-event validation. Observed quantiles have no extra uncertainty band. The flags are correlated exploratory discrepancies, not calibrated tests or a ranking criterion.

| Model | Modeled-response quantile checks outside central 90% | Native-minute checks outside central 90% |
| --- | ---: | ---: |
| pooled | 14/15 | 11/15 |
| distance | 12/15 | 9/15 |
| event | 12/15 | 9/15 |

These discrepancies motivate a bounded mean/scale/tail investigation. A smaller fitted record SD alone does not establish improved prediction. Sequence-held-out refits, numerical integration checks and sensitivity precede selection. The difficult-scenario recovery follow-up is complete, with adaptive-selection and conditional-coverage limits. Separate NTWC computational checks remain required.
