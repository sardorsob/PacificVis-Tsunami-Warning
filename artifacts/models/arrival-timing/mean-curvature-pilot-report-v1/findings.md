# Mean-curvature computational pilot

All five prespecified synthetic fits passed on their first attempts. Each uses four chains with 1,000 tuning and 1,000 retained draws per chain. The frozen 1,064-record, 33-event design supplies distances, group membership and exclusions; generated responses replace the historical outcomes in the likelihood.

| Scenario | Gamma truth | Gamma median [90% interval] | Event SD truth | Event SD median [90% interval] |
| --- | ---: | ---: | ---: | ---: |
| null-weak | 0.00 | 0.086 [-0.039, 0.212] | 0.05 | 0.047 [0.031, 0.073] |
| positive-weak | 0.50 | 0.584 [0.471, 0.696] | 0.05 | 0.061 [0.043, 0.088] |
| negative-weak | -0.50 | -0.569 [-0.685, -0.448] | 0.05 | 0.053 [0.036, 0.082] |
| null-moderate | 0.00 | 0.005 [-0.110, 0.118] | 0.25 | 0.279 [0.216, 0.360] |
| combined | 0.75 | 0.646 [0.514, 0.775] | 0.05 | 0.065 [0.045, 0.095] |

The largest R-hat is 1.0045; the smallest bulk and tail effective sample sizes are 1428 and 1764. No divergences or maximum-depth hits occurred. Sampled hyperparameters were screened before reconstructing conditional event effects or derived quantities.

Gamma is a dimensionless coefficient for the fixed smooth basis. Event SD is between-event variation on the log-duration scale. Local median elasticity, the 100-km median/reference ratio and total new-event log SD are recorded among the twelve correlated summaries. A small event SD does not establish an absence of physical event differences.

There is one dataset at each generating truth. These intervals and successful diagnostics establish computational feasibility, not nominal conditional coverage, SBC calibration or predictive superiority. No interval-containment quota was used, and no datasets or unsuccessful attempts were replaced. The prior SD references are finite Monte Carlo estimates from the accepted 2,000 base ancestrals.

Independent replay checked every synthetic native/log response, conditional event effect, scalar summary and diagnostic table. Dense block-Gaussian likelihood/prior calculations agreed with retained sampler log densities within 7.64e-9 nats. This checks the computational route under the assumed model.

Storage totals are monitored trip observations rather than hard filesystem quotas; the individual 64-MiB file cap is enforced by the kernel. The end-run observation was 15,707,182 bytes, including caches and evidence. Later review and tracking files are additional. The five-slot allocation is exhausted; the larger recovery/SBC program requires its own finite allocation and review.

No historical candidate fit or confirmation/reserved evaluation is reported here. The 19 previously inspected confirmation outcomes have not been reopened; 18 reserved outcomes remain sealed. Source-quality sensitivities and candidate recovery/SBC precede the historical fit and model comparison.

Tables: [sampling and runtime](sampling-and-runtime-summary.csv), [all known-truth estimates](known-truth-estimates.csv). [Original pilot evidence](../mean-curvature-pilot-v1/).

Reproduce: `uv run --locked --offline python scripts/summarize_arrival_curvature_pilot.py --output <new-project-path>`. This only summarizes accepted saved evidence.
