# Initial models of NTWC estimate-minus-observation minutes

Three exploration models use the same 156 approved records from 13 events: a pooled population center, a distance adjustment, and a distance adjustment with partially pooled event effects. All numerical screens passed. These are exploratory development fits; the review receipt records what was independently verified. No held-out score or model selection has been computed. The 18 reserved outcomes remain sealed.

The signed response is estimated UTC minus reported observed UTC in minutes. The predictor is ln(source–station distance/1000km); this response uses no distance/reference-duration transformation. Population means describe archived products, not prospective warning performance or a causal forecaster error.

| Model | Alpha, minutes (central 90%) | Beta (central 90%) | Event SD (central 90%) | Record SD (central 90%) |
| --- | --- | --- | --- | --- |
| pooled | -20.574 [-24.263, -16.801] | fixed zero | fixed zero | 28.030 [25.582, 30.910] |
| distance | -7.295 [-12.471, -2.137] | -9.747 [-12.653, -6.872] | fixed zero | 25.750 [23.519, 28.359] |
| event | -11.927 [-22.760, -0.983] | -8.605 [-11.403, -5.716] | 18.718 [11.929, 29.731] | 21.842 [19.889, 24.119] |

Predictive checks replicate reports at the observed distances, conditional on fitted events. The plotted intervals describe variation in replicated sample quantiles, not credible intervals for a mean and not new-event validation. Observed quantiles have no extra uncertainty band. The flags are correlated exploratory discrepancies, not calibrated tests or a ranking criterion.

For T-CAL the modeled and native scales are both minutes, so the two columns repeat the same checks and are not independent evidence.

| Model | Modeled-response quantile checks outside central 90% | Native-minute checks outside central 90% |
| --- | ---: | ---: |
| pooled | 6/15 | 6/15 |
| distance | 6/15 | 6/15 |
| event | 7/15 | 7/15 |

These discrepancies motivate a bounded mean/scale/tail investigation. A smaller fitted record SD alone does not establish improved prediction. Sequence-held-out refits, numerical integration checks and sensitivity precede selection. Each source's computational readiness is reviewed separately; its finite-check and interpretation limits remain. Source likelihoods are never independently pooled.
