# Initial models of NTWC reported durations

Three exploration models use the same 236 approved records from 14 events: a pooled population center, a distance adjustment, and a distance adjustment with partially pooled event effects. All numerical screens passed. These are exploratory development fits; the review receipt records what was independently verified. No held-out score or model selection has been computed. The 18 reserved outcomes remain sealed.

The reference uses epicenter distance and a fixed four-kilometer-depth speed. Reported-duration definitions and clock/source effects are composite. Neither the distance exponent nor an event offset identifies a physical wave speed or delay. The event population center differs from a pooled record center; a change in alpha does not identify historical forecast bias.

| Model | Alpha, log ratio (central 90%) | Beta (central 90%) | Event SD (central 90%) | Record SD (central 90%) |
| --- | --- | --- | --- | --- |
| pooled | 0.108 [0.060, 0.157] | fixed zero | fixed zero | 0.459 [0.428, 0.497] |
| distance | 0.181 [0.114, 0.246] | -0.061 [-0.100, -0.024] | fixed zero | 0.453 [0.421, 0.489] |
| event | 0.151 [0.009, 0.277] | -0.065 [-0.105, -0.026] | 0.199 [0.059, 0.373] | 0.439 [0.407, 0.476] |

Predictive checks replicate reports at the observed distances, conditional on fitted events. The plotted intervals describe variation in replicated sample quantiles, not credible intervals for a mean and not new-event validation. Observed quantiles have no extra uncertainty band. The flags are correlated exploratory discrepancies, not calibrated tests or a ranking criterion.

| Model | Modeled-response quantile checks outside central 90% | Native-minute checks outside central 90% |
| --- | ---: | ---: |
| pooled | 11/15 | 11/15 |
| distance | 10/15 | 10/15 |
| event | 10/15 | 10/15 |

These discrepancies motivate a bounded mean/scale/tail investigation. A smaller fitted record SD alone does not establish improved prediction. Sequence-held-out refits, numerical integration checks and sensitivity precede selection. Each source's computational readiness is reviewed separately; its finite-check and interpretation limits remain. Source likelihoods are never independently pooled.
