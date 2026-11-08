# Difficult-scenario recovery follow-up

The weak-event/wide-record setting was selected after sigma coverage was low in the initial thirty datasets. Thirty new datasets were then frozen before their outcomes, with unchanged truth and independent seeds. Every original dataset remains included. The pooled Wilson interval is descriptive under this adaptive follow-up; it is not fresh confirmation or a guarantee of nominal conditional coverage.

| Cohort | Sigma mean error | Coverage of central 90% interval | Wilson 95% reference |
| --- | ---: | ---: | --- |
| initial | -0.002765 | 23/30 | 59.07%–88.21% |
| independent-followup | 0.001673 | 26/30 | 70.32%–94.69% |
| pooled-descriptive-adaptive-followup | -0.000546 | 49/60 | 70.08%–89.44% |

All thirty follow-up fits passed without repairs. Independent review reproduced all new posterior means, quantiles, SDs and standardized errors; representative chains also passed independent rank and sampler-statistic checks. Recovery used 300 of the original 330 calls and 565,205,400 of 2,147,483,648 posterior bytes. The accepted 200-dataset SBC results and all original recovery chains remain intact.

This completes the bounded follow-up. Fixed-truth Bayesian coverage need not equal nominal probability at every parameter setting. These results limit conditional interval claims; they justify neither forcing priors to achieve 90% nor claiming a physical model has been validated. No further iterations are scheduled.
