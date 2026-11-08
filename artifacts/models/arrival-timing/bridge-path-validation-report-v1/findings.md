# Numerical checks for a fixed likelihood path

An eight-edge geometric path estimates the same joint held-event predictive
density as a direct bridge. Intermediate distributions are integration devices.
Their adjacent normalizer ratios telescope exactly, without thermodynamic-integration
discretization error. Every edge still needs posterior overlap, reliable sampling
and Monte Carlo precision. Coefficients remain explicit; the new event effect is
integrated before powering its entire marginal Gaussian likelihood. The native-minute
Jacobian is subtracted once at the end.

The known-normalizer experiment retains 60 six-dimensional Gaussian trials:
30 independent-draw trials and 30 with stationary autocorrelation 0.8. Each uses
nine independent stage ensembles of four chains and 8,000 draws. A normalization
count of 100 sets the numerical reporting scale; it does not represent 100 tsunami
observations. All 60 passed their declared numerical screens. Coverage of nominal
90% intervals was 27/30 and 26/30; the tables include binomial uncertainty.
These are estimator checks, not model SBC, physical validation or proof that the
actual Tōhoku path will have sufficient overlap.

The autocorrelated cohort retains a warning: mean error is -0.003516
raw nat, or -2.28 empirical standard errors. Its descriptive 95%
interval is [-0.006666,
-0.000365]. Independent replay found no target,
stationarity, seed, root or covariance defect explaining this result. It remains
a finite-cohort warning. No trials were replaced or added and no empirical bias
correction is applied. Reported RMS MCSE was about 8–10% below empirical SD, with
substantial uncertainty at 30 trials. This supports a cautious bounded prototype.

Adjacent ratios share middle-stage samples. Their incoming and outgoing influences
must be added within each stage before estimating MCSE. Across these checks,
the correct MCSE averaged 1.36 times the naïve independent-edge
calculation. Independent stage variances then add.

The actual contingency is fixed before fitting: seven new middle-stage fits for
the designated primary path, then eight for a fully independent computational
repeat using a previously saved independent augmented endpoint. All 15 calls
debit the existing production ceiling; no repair, replacement or ladder insertion
is allowed. Each stage and newly available edge is checked immediately. Whole-path
precision and independent-repeat agreement are separate requirements. No broad
cross-validation or model-selection result is established here.

Reproduce the known experiment with `scripts/validate_arrival_bridge_path.py`;
its frozen targets, original seeds and source identities accompany the tables.
The bridge identity is described by
[Meng and Wong](https://www3.stat.sinica.edu.tw/statistica/j6n4/j6n43/j6n43.htm)
and [Gronau et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC5699790/).
