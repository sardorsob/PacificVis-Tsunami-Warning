# Checking the joint predictive-density estimator

A two-posterior bridge estimates the same new-event joint predictive density as
the original integration. It uses independent training and training-plus-one-held-event
posterior ensembles. The latter is an integration device; it supplies no training-only
predictions or parameter conclusions. Whole related sequences still leave training
together. Other held-out events never enter the augmented fit.

Normal coefficients and event effects are integrated at fixed variance parameters.
With f₀ the training hyperparameter density and f₁ its product with the joint
conditional held-event density, the bridge estimates Z₁/Z₀. For durations, subtract
Σ log(y_minutes) to return to native-minute density. This ratio scores a held event
within one model; no Bayes-factor interpretation is used for predictive differences
between models. See [Meng and Wong](https://www3.stat.sinica.edu.tw/statistica/j6n4/j6n43/j6n43.htm)
and [Gronau et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC5699790/).

The finite experiment retains all 170 known-normalizer trials.
160 of 160 adequate-overlap trials passed; 0 of 10 deliberately
separated cases passed. Cases include unequal ensemble sizes, changed covariance,
four dimensions and stationary autocorrelation 0.8. The 90% interval coverage counts
range from 35 to 38
of 40 for the adequate-overlap settings; the table gives binomial uncertainty.
These are computation checks, not model SBC or physical validation, and cannot
certify arbitrary posterior geometry.

Two real exploration folds and an independent two-fit repeat agree with separately
checked two-dimensional quadrature within 0.606 reported Monte Carlo
standard errors. Overlap ranges from 0.442 to 0.861.
The two independent estimates of the difficult event differ by 0.044
combined standard errors. Reference quadrature refinement differences are at most
2.23e-10 raw nats; finite refinement and routine error estimates do not
prove exhaustive mode coverage.

The four-variance fixed-anchor model was also checked on the blocked Chile event.
Two independent training/augmented pairs give normalized scores
-5.7117268 and -5.7115111,
with MCSEs 0.0002030 and 0.0002416.
Their difference is 0.684 combined standard errors. Overlap is
0.265 and 0.250.
Independent all-draw and dense Gaussian replay verified the conditional coefficient
and event-effect integration, memberships, base priors and native-duration measure.
This is numerical validation of one difficult fold, with no deterministic exact
four-dimensional reference or universal posterior-exploration certificate.

Numerical screens keep event-score MCSE ≤0.005 and aggregate MCSE ≤0.002 nat per
record. Additional analyst screens require overlap ≥0.1, |empirical fixed-point
derivative| ≤0.25, both bridge weight concentrations ≥100, functional R-hat ≤1.01
and bulk/tail ESS ≥400. Weight concentration is distinct from MCMC ESS. A bounded
monotone root checks algebraic accuracy separately from sampling precision.
Shared-training influences are summed before computing MCSE; independent augmented
ensembles contribute separate variances. Overlap and clean diagnostics do not prove
global exploration. MCSE is asymptotic and gives no deterministic tail certificate.

Original failed importance estimates remain unresolved and retained. This validation
supports review of the integration method only. Production scoring,
completed sequence comparisons, model selection and sensitivity remain separate gates.
Previously inspected confirmation outcomes and 18 reserved outcomes were not read
in these checks.
