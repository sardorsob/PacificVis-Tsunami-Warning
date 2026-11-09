# Frozen development model summary

The 19-event check was previously inspected during EDA. It is a development check, not an independent test. The specification was frozen before evaluation. The 18 reserved outcomes remain sealed.

Targets retain separate likelihoods and units. Reported timing is conditional on archive inclusion. The models do not establish physical onset, causal delay, operational warning time, or transfer to new station geography.

All intervals below are central 90%. Parameter intervals describe posterior uncertainty; New-event intervals are pointwise reported-value predictions. Positive-target summaries use quantiles, with no predictive mean or moment claim.

The NCEI linear 2014-onward sensitivity remains computationally unresolved after two failed attempts. Its original run had 30 divergences; the reviewed numerical attempt retained one divergence among 8,000 draws and failed the unchanged zero-divergence screen. No third attempt is authorized. Neither attempt supplies posterior parameters, curves or predictive checks. This leaves a gap in the linear-model stress checks: the available results cannot establish robustness for this comparison or be used to favor curvature. Its 150 original observations remain in the other applicable fits and full-data analyses; this disposition deletes no data. The curved 2014-onward fit became usable only after its final numerical repair. Its availability does not resolve the missing linear comparison or establish an era advantage.

The unresolved linear 2014-onward stress provides no robustness claim and no basis to prefer curvature. The frozen decision must acknowledge that gap; this report does not reopen model selection.


The first NCEI check retained an original numerical precision failure. Its predictions remain unchanged. A separate, reviewed integration of the same frozen predictive density supplies a score only when its numerical checks pass. The linear NCEI runner-up has a separately reviewed numerical gap: both aggregate score views remain unavailable while its original marginal predictions are retained. This gap establishes neither model rejection nor superiority or equivalence. Unresolved scores remain unavailable. The first recovery smoke retains its original controller failure and was independently accepted under strict revalidation of the same saved computation; no additional sampler call was made. Recovery smoke G2 retains its earlier proof failure and absent accepted attempt; a separate stable recomputation of the original scientific diagnostics validates the same saved computation, with no additional sampling. Mixed-method aggregate uncertainty sums the shared-draw MCSE estimate and the weighted integration MCSE estimate, without assuming independence; this is not a finite-bias bound. Model selection stays frozen.

## NCEI-native-duration

NCEI positive reported travel duration. Response: `ln(y/t0(distance))`. Frozen form: **mean-curvature**; prior: **base** (normal).

Full fit: 1215 reports across 47 eligible events. Distance range: 32.9197–18273.8 km. Support flags describe distance only.

| Parameter | Median [90% interval] |
| --- | --- |
| alpha | 0.2375 [0.201, 0.2742] |
| beta | -0.01147 [-0.03651, 0.01266] |
| gamma | 0.5464 [0.4283, 0.6613] |
| tau_event | 0.06551 [0.04356, 0.09805] |
| sigma_anchor at 500 km | 0.6323 [0.5883, 0.6809] |
| sigma_anchor at 2000 km | 0.6905 [0.6424, 0.7447] |
| sigma_anchor at 5000 km | 0.09934 [0.0946, 0.1046] |

| Distance km | Curve | Native minutes: median [90% interval] | Support |
| ---: | --- | --- | --- |
| 20 | population_median | 10.61 [8.078, 13.79] | below; SD endpoint clamped |
| 20 | new_event | 10.73 [3.329, 30.73] | below; SD endpoint clamped |
| 50 | population_median | 16.41 [13.57, 19.69] | within; SD endpoint clamped |
| 50 | new_event | 17.28 [5.701, 45.76] | within; SD endpoint clamped |
| 100 | population_median | 23.37 [20.47, 26.56] | within; SD endpoint clamped |
| 100 | new_event | 24.05 [8.292, 69.75] | within; SD endpoint clamped |
| 500 | population_median | 62.93 [60.05, 65.95] | within |
| 500 | new_event | 61.73 [24.45, 172.3] | within |
| 1000 | population_median | 106.7 [102.9, 110.7] | within |
| 1000 | new_event | 107.3 [34.25, 328.3] | within |
| 2000 | population_median | 191.7 [185.7, 197.9] | within |
| 2000 | new_event | 191.4 [61.4, 591.4] | within |
| 5000 | population_median | 442.1 [430.5, 454.8] | within |
| 5000 | new_event | 435.2 [361.7, 544.4] | within |
| 10000 | population_median | 855.1 [833, 879.7] | within; SD endpoint clamped |
| 10000 | new_event | 853.6 [700.8, 1048] | within; SD endpoint clamped |
| 20000 | population_median | 1675 [1619, 1734] | above; SD endpoint clamped |
| 20000 | new_event | 1677 [1389, 2061] | above; SD endpoint clamped |

| Frozen check model | Native nats/report ± MCSE | Excluding crossing event |
| --- | --- | --- |
| NCEI-native-duration:mean-curvature:selected | -5.1367 ± 0.000286 (sum of MCSE estimates) | -5.2023 ± 0.000299 (sum of MCSE estimates) |
| NCEI-native-duration:distance-scale:runner_up | source-null; score/MCSE unavailable | source-null; score/MCSE unavailable |

Check `NCEI-native-duration:mean-curvature:selected`: 14 eligible events / 151 reports; 0 prediction precision flags; 0 ambiguous interval classifications. Distance support: `{'within': 151}`.

Check `NCEI-native-duration:distance-scale:runner_up`: 14 eligible events / 151 reports; 0 prediction precision flags; 0 ambiguous interval classifications. Distance support: `{'within': 151}`.

Conditional PPC: 20/30 observed quantile cells outside replicated central 90% intervals. These correlated, fitted-event checks are descriptive; they are not held-out validation.

## T-OBS

NTWC reported observed UTC minus the reviewed USGS origin, a positive reported travel duration. Response: `ln(y/t0(distance))`. Frozen form: **pooled**; prior: **base** (normal).

Full fit: 258 reports across 20 eligible events. Distance range: 75.7455–17841 km. Support flags describe distance only.

| Parameter | Median [90% interval] |
| --- | --- |
| alpha | 0.1018 [0.05618, 0.1477] |
| sigma | 0.4416 [0.4107, 0.4758] |

| Distance km | Curve | Native minutes: median [90% interval] | Support |
| ---: | --- | --- | --- |
| 20 | population_median | 1.863 [1.78, 1.951] | below |
| 20 | new_event | 1.886 [0.8759, 4.052] | below |
| 50 | population_median | 4.658 [4.451, 4.877] | below |
| 50 | new_event | 4.579 [2.3, 9.458] | below |
| 100 | population_median | 9.316 [8.901, 9.754] | within |
| 100 | new_event | 9.49 [4.464, 19.93] | within |
| 500 | population_median | 46.58 [44.51, 48.77] | within |
| 500 | new_event | 44.89 [21.52, 97.35] | within |
| 1000 | population_median | 93.16 [89.01, 97.54] | within |
| 1000 | new_event | 93.96 [44.23, 200.9] | within |
| 2000 | population_median | 186.3 [178, 195.1] | within |
| 2000 | new_event | 185.4 [87.48, 379.1] | within |
| 5000 | population_median | 465.8 [445.1, 487.7] | within |
| 5000 | new_event | 470.7 [231.1, 956.2] | within |
| 10000 | population_median | 931.6 [890.1, 975.4] | within |
| 10000 | new_event | 922.6 [458.7, 1962] | within |
| 20000 | population_median | 1863 [1780, 1951] | above |
| 20000 | new_event | 1870 [972.9, 3620] | above |

| Frozen check model | Native nats/report ± MCSE | Excluding crossing event |
| --- | --- | --- |
| T-OBS:pooled:selected | -5.1243 ± 0.000527 MCSE | -5.1243 ± 0.000527 MCSE |
| T-OBS:distance:runner_up | -5.0884 ± 0.000579 MCSE | -5.0884 ± 0.000579 MCSE |

Check `T-OBS:pooled:selected`: 6 eligible events / 22 reports; 0 prediction precision flags; 0 ambiguous interval classifications. Distance support: `{'within': 22}`.

Check `T-OBS:distance:runner_up`: 6 eligible events / 22 reports; 0 prediction precision flags; 0 ambiguous interval classifications. Distance support: `{'within': 22}`.

Conditional PPC: 21/30 observed quantile cells outside replicated central 90% intervals. These correlated, fitted-event checks are descriptive; they are not held-out validation.

## T-CAL

NTWC reported estimated UTC minus reported observed UTC, a signed archive discrepancy in minutes. Response: `identity_minutes`. Frozen form: **distance**; prior: **base** (normal).

Full fit: 169 reports across 18 eligible events. Distance range: 124.031–17225 km. Support flags describe distance only.

| Parameter | Median [90% interval] |
| --- | --- |
| alpha | -6.733 [-11.59, -1.909] |
| beta | -9.669 [-12.44, -6.984] |
| sigma | 25.18 [23.05, 27.63] |

| Distance km | Curve | Native minutes: median [90% interval] | Support |
| ---: | --- | --- | --- |
| 20 | population_median | 31.07 [16.5, 46.07] | below |
| 20 | new_event | 29.65 [-14.73, 77.77] | below |
| 50 | population_median | 22.24 [10.07, 34.77] | below |
| 50 | new_event | 22.44 [-23.99, 65.12] | below |
| 100 | population_median | 15.58 [5.127, 26.15] | below |
| 100 | new_event | 17.12 [-26.87, 58.51] | below |
| 500 | population_median | 0.00265 [-6.429, 6.394] | within |
| 500 | new_event | -0.4691 [-44.09, 42.58] | within |
| 1000 | population_median | -6.733 [-11.59, -1.909] | within |
| 1000 | new_event | -7.023 [-48.34, 32.7] | within |
| 2000 | population_median | -13.45 [-17.22, -9.794] | within |
| 2000 | new_event | -14.83 [-57.7, 28.84] | within |
| 5000 | population_median | -22.37 [-25.63, -19.1] | within |
| 5000 | new_event | -23.09 [-67, 20.1] | within |
| 10000 | population_median | -29.06 [-33.18, -25.07] | within |
| 10000 | new_event | -29.68 [-71, 8.855] | within |
| 20000 | population_median | -35.77 [-41.27, -30.46] | above |
| 20000 | new_event | -35.06 [-76.66, 4.433] | above |

| Frozen check model | Native nats/report ± MCSE | Excluding crossing event |
| --- | --- | --- |
| T-CAL:distance:selected | -4.4052 ± 0.000537 MCSE | -4.4052 ± 0.000537 MCSE |
| T-CAL:pooled:runner_up | source-null; score/MCSE unavailable | source-null; score/MCSE unavailable |

Check `T-CAL:distance:selected`: 5 eligible events / 13 reports; 0 prediction precision flags; 0 ambiguous interval classifications. Distance support: `{'within': 12, 'below': 1}`.

Check `T-CAL:pooled:runner_up`: 5 eligible events / 13 reports; 0 prediction precision flags; 0 ambiguous interval classifications. Distance support: `{'within': 12, 'below': 1}`.

Conditional PPC: 10/30 observed quantile cells outside replicated central 90% intervals. These correlated, fitted-event checks are descriptive; they are not held-out validation.

For signed T-CAL, native and modeled PPC scales repeat the same evidence. The crossing sequence was purged uniformly from check training and restored for the unchanged full refit. Target eligibility counts differ; 57 is the catalogue size, not each target's event count.

The initial 34 sensitivity fits were an interim checkpoint. The accepted complete analysis and frozen decision govern the specification. Posterior sensitivity is not a new predictive ranking or proof of equivalence. Two fixed synthetic cases per selected target provide a computational smoke check, not calibration or coverage evidence.

Scores are saved equal-event joint native-minute densities; no additional Jacobian is applied. MCSE retains shared-training covariance. Numerical screens do not certify tail accuracy or global exploration; unresolved supplemental results remain unavailable. No re-selection follows the check.

[Saved summaries](summary.json) include prior distribution scales, residual-scale and elasticity intervals, diagnostics, precision flags and support counts. [Input identities](inputs.json) bind the accepted artifacts and reproduction code. Predictive summaries retain the existing 800-draw budget; small shifts need Monte Carlo caution.

The accepted MS5 analysis has 54 usable fits across 55 planned probes (1 computationally unresolved) and 58 sampler calls, including 4 retained failed calls. Failed draws contribute no posterior summaries. The accepted numerical amendment also covered the first attempts of 18 prespecified cases. Recorded amended sampling settings: `{'draws': 2000, 'tune': 2000, 'chains': 4, 'cores': 2, 'target_accept': 0.99, 'nuts_sampler': 'nutpie'}`.

The accepted MS5 method record retains the statistical models, priors, masks, cohorts and seeds; same-model repairs amend numerical sampling settings.
