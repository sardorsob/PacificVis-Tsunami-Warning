# Distance-dependent reported-record spread

This candidate interpolates positive residual SDs linearly in log distance at500,2000 and5000km, with constant endpoint extrapolation. The curve is continuous with corners, not differentiably smooth. This definition does not validate distance/support transport. No monotonicity is imposed. Anchors reuse existing exploration distance thresholds.

Independent HalfNormal(.4) SD anchors are composite reported-log-ratio variation, not measurement accuracy or physical noise. Alpha,beta and event-SD priors remain the base analyst hypotheses. Equal anchors reproduce the baseline likelihood; they do not define a prior-equivalent equality submodel. The constant reference draws one shared HalfNormal SD. Paired draws reduce Monte Carlo comparison noise.

Prior E[sigma(d)] is constant, but E[sigma(d)^2] falls between anchors: .16 at an anchor versus approximately.131 halfway between two on the log axis. Independence supplies no hierarchy shrinking anchors toward a common value.

At every fixed finite distance, base first and second native-duration moments exist: convexity gives sigma(d)^2<=sum(w_j*s_j^2), and the t=2 HalfNormal MGF bound has 1-4*.4^2*w_j>0. The independent event-scale bound also passes. These are prior scale conditions, not upper bounds on sampled SD values. Wider.6 hypotheses do not retain the second-moment claim. Finite draws alone prove no moment claim.

Support rows/events overlap across anchors; weight mass is not an ESS. Prior predictions condition on the archived exploration design and simulate a new event/record. No actual posterior, source repair, confirmation outcome or reserved outcome is used.
