# Distance-dependent reported-duration spread: computational checks

100 of 100 predefined synthetic datasets completed in 100 attempts. The fixed NCEI exploration design has 1,064 records and 33 events. Actual reported responses did not enter these simulated likelihoods. All attempts, including failed precision checks, remain in the diagnostics table.

The six population parameters are alpha and beta (log-ratio center/distance adjustment), tau (between-event log-ratio SD), and three residual SD anchors at500/2000/5000km. SD1000 is the interpolation midpoint of the first two anchors. The first effect is the lexically first fitted event's latent effect, reconstructed by its exact conditional Normal. These quantities describe composite reports, not physical noise or accuracy.

Eight prespecified quantities use 100 spaced posterior draws for ranks while retaining all original chains and ESS. The simultaneous DKW/Bonferroni band has familywise reference alpha.05 under independent uniform ranks; MCMC dependence makes it approximate. A crossing needs diagnosis. No crossing is not proof of computational correctness or physical validity.

Recovery and calibration under an assumed simulator do not establish model adequacy, predictive transfer, archive representativeness or a model-selection decision. The 18 reserved outcomes remain sealed.
