# Curvature in reported arrival duration

The additional mean basis changes the distance relationship while the residual-spread model stays fixed. Both fits use the same 1,064 NCEI reports from 33 exploration events, with the six ambiguous repeated-edge records excluded together. The target is native reported positive duration, not a universally verified physical onset or warning time.

Gamma is 0.545 [0.420, 0.676] and local median elasticity at 1,000 km is 0.804 [0.776, 0.830], with central 90% posterior intervals. The curvature basis is log((d+500)/(1.5d)); alpha remains the population log-median ratio at 1,000 km. Beta alone is not a global distance exponent for this candidate. Coefficient correlations describe posterior coupling, not causation. The beta–gamma posterior correlation is 0.790.

| Model | Between-event log-scale SD | Central 90% interval |
| --- | ---: | ---: |
| Linear log-median ratio | 0.0464 | [0.0288, 0.0840] |
| Curved log-median ratio | 0.0358 | [0.0221, 0.0585] |

Between-event variation is conditional on the specified mean and residual-spread model. Its magnitude does not identify clock, source, path or reporting mechanisms.

Of 15 correlated fitted-event log-ratio quantile checks, 8 observed statistics fall outside their central 90% replicated ranges. These checks criticize the model; they are neither independent tests nor a selection score. Inspect the table and figure for which strata and tails remain mismatched. New-sequence prediction and sensitivity analysis remain necessary before selection.

Bulk quantile checks can hide individual discrepancies. The retained LATA WHARF, NENDO IS, SANTA CRUZ IS report for usc000piqj is 1,125 minutes, while its central 90% fitted-event replicated interval is [20.10, 165.05] minutes. The earlier source-component audit flags a disagreement among the recorded time components for this row. That triage flag does not prove a timing error, its cause or a justified replacement. The original value remains in the primary fit. Tail and observation-process sensitivities remain necessary.

Curve bands are pointwise central 90% posterior parameter intervals at zero event effect, not simultaneous or noisy-observation bands. Predictive-check bars are central 90% variation in sample quantiles replicated conditional on the fitted events. The plotted grid extends from 20 to 20,000 km; endpoint behavior remains model-imposed.

Reproduce with `uv run python scripts/summarize_arrival_curvature_fit.py --output artifacts/models/arrival-timing/exploration-mean-curvature-v1/report-v1` using a new output directory. Confirmation outcomes were not parsed and reserved outcomes remain sealed.
