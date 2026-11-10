---
title: Probabilistic Hierarchical Modeling of Tsunami Arrival-Time Differences
lang: en-US
---

## Abstract

Historical tsunami archives report arrival times in different ways. A statistical model must distinguish these quantities before its uncertainty can be interpreted. We examine three targets separately: reported travel durations from the National Centers for Environmental Information, and observed-minus-origin durations and estimated-minus-observed differences from the National Tsunami Warning Center. The fitted datasets contain 1,215 reports from 47 events, 258 from 20 events, and 169 from 18 events, respectively. We compare Bayesian models using omitted-sequence prediction and visual predictive checks. On the same exploration dataset, allowing residual spread to vary with distance changes the estimated between-event standard deviation from 0.352 to 0.046 log units. Adding curvature to the mean improves the estimated prediction score by 0.084 nats per report, but its descriptive 95% interval spans zero, [-0.049, 0.217]. All three final fits pass the reported sampling checks while retaining substantial predictive discrepancies. The figures explain these results by separating event variation, uncertainty in the fitted center, and variation in a new report. The analysis describes selected archive reports; it does not validate physical first arrivals or operational forecasts.

**Keywords:** Bayesian modeling; tsunami arrival times; hierarchical models; uncertainty visualization; posterior predictive checks.

## 1. Introduction

To compare tsunami arrival estimates with observations, we first need to know what each time represents. Historical records often lack that context. An estimate may have no issue time or product version. An observed time may have no date, or may refer to a different wave feature from another source's arrival. Nearby locations may belong to different instruments or deployments. Subtracting two times is easy; establishing a meaningful pair is harder.

These differences also affect how a model should be displayed. A narrow band around a smooth curve can suggest precise predictions even when individual reports vary widely. An event effect can appear to measure a difference between tsunamis while absorbing variation that the rest of the model fails to describe. The figures must therefore identify what was measured and which source of uncertainty each interval includes.

We ask three questions about public Pacific tsunami records: **(1)** which timing quantities can be compared reproducibly; **(2)** how the distance model changes the variation attributed to events; and **(3)** whether the fitted models reproduce the observed distributions and predict omitted groups of related events. We initially sought to model uncertain first-wave arrivals. Because the archive lacks a common, independently validated arrival definition, the completed study models reported values instead.

The paper presents a reproducible Bayesian modeling case study. We separate three timing targets, show how residual assumptions change estimated event variation, and use three figures to connect those assumptions to model comparisons and predictions. The results include simpler alternatives, predictive discrepancies, and comparisons that remain unresolved.

## 2. Background and related work

Warning messages, modeled arrivals, and water-level observations serve different purposes. Observing networks and forecast products inform warning services,[^noaa_warning] while travel-time maps describe modeled propagation.[^ncei_travel_maps] The historical NCEI database compiles reports from many sources. It defines arrival as the first wave at a runup location but notes that an original source may report a later wave.[^ncei_tsunami_data] These quantities require separate definitions before comparison.

Probabilistic tsunami forecasting already combines reduced-order physical models with hierarchical pooling.[^coffing2026] Here the problem is retrospective: what can historical timing reports support? We analyze their statistical relationships without estimating an initial sea-surface condition or validating a physical forecast.

Bayesian workflow links model building to computational checks, predictive checks, and revision.[^gelman2020workflow] Visualization helps reveal structure that a single score can conceal.[^gabry2017visualization] Two checks have distinct roles. Convergence diagnostics assess the behavior of the posterior sampler. Simulation-based calibration tests inference under a specified simulator.[^talts2018sbc] Predictive checks then ask whether the model can reproduce features of the actual reports. Passing the first two does not guarantee the third.

## 3. Data and observational targets

### 3.1. Archive scope and eligibility

The snapshot preserves all 118 historical NTWC archive entries,[^ntwc_messages] which are not necessarily independent earthquakes. Metadata screening assigns 57 to development, reserves 18, and records exclusion or uncertainty reasons for the other 43. Of 1,177 development table rows, 388 have source-supported complete pairs; incomplete rows remain preserved. Additional warning messages remain separate unless evidence supports an observation link. The evidence index documents these study-specific cohorts, counts, and source-process tables.

NCEI supplies positive reported travel durations. From 1,221 candidates across 47 events, we exclude all six records in three unresolved repeated event/site groups. This leaves 1,215 reports from the same 47 events, addressing ambiguous repeated evidence rather than unusual timing values.

Table 1 lists the target-specific fitted datasets. Geographic and calendar checks further restrict NTWC eligibility, even among complete pairs.

| Response | Definition | Eligible reports | Events |
|:--|:--|--:|--:|
| NCEI duration | Explicit native positive reported travel duration | 1,215 | 47 |
| T-OBS | Reported observed UTC minus reviewed USGS origin | 258 | 20 |
| T-CAL | Reported estimated UTC minus reported observed UTC | 169 | 18 |

**Table 1.** Full-development modeling cohorts. Counts are target-specific and are not independent samples across source families. The NCEI cohort follows the repeated-evidence exclusion; the two NTWC targets can share the same observed clock.

### 3.2. Meaning of a timing difference

For a record with estimated time $E$ and reported observed time $O$, we define the signed discrepancy

$$\Delta=E-O.$$

A negative value means the estimate is earlier than the reported observation. It is not a measure of warning lateness: the historical product's issue time, version, and reference origin are not sufficiently resolved for that interpretation.

The positive NTWC duration is $Y_O=O-T_{\mathrm{origin}}$, using a reviewed USGS origin that may differ from the historical product's origin. NCEI's reported travel duration remains a separate target. We do not reconstruct missing dates from distance or another station's time. The two NTWC targets share the observed time $O$, so they would not be independent in a combined likelihood. We fit each target separately.

We preserve reported values and their displayed precision, then use continuous point-value likelihoods as working models. A time displayed to the minute does not establish its accuracy. We therefore do not infer rounding bounds, censoring intervals, or latent physical arrival times without supporting measurement evidence.

### 3.3. Availability and selection

Among the 789 NTWC rows without a complete pair, 513 lack at least one time in the source table and 230 lack resolved calendar context. The other 46 comprise 35 structural or blank rows, seven qualified clocks, three footnoted clocks, and one row with unverified column meaning. The source tables lack 297 estimates and 289 observations, including 73 rows missing both. These counts describe retained rows, not every station that could have reported an arrival.

Documentary evidence supports gaps near arrival for four of the 289 absent observations, but does not establish their technical causes. General reporting policies cannot explain every blank. We cannot identify whether missingness is completely random, depends on recorded information, or depends on unrecorded values. The models consequently describe eligible archive reports. They neither represent all possible arrivals nor recover absent historical forecasts.

## 4. Models and computational checks

### 4.1. Reference scale and model comparisons

Let $d_i$ be geodesic source-to-site distance in kilometers. We use the fixed reference duration

$$t_0(d)=\frac{1000d}{60\sqrt{gh}},\qquad g=9.80665\ \mathrm{m\,s^{-2}},\quad h=4000\ \mathrm{m},$$

in minutes, and $x_i=\log(d_i/1000)$. The reference assumes a straight path through water of constant depth. It provides a common scale, not a bathymetric forecast; $h$ is water depth, not earthquake focal depth. For positive durations, we model $r_i=\log(Y_i/t_0(d_i))$. A value of zero means the reported duration equals the reference, and a positive value means it is longer.

We start with pooled and distance-only models, then consider event effects, spread that varies with distance, and a curved mean where exploratory checks motivate them. In an event hierarchy, reports from the same event share an offset. Partial pooling estimates those offsets together, allowing less informative events to borrow information from the overall distribution.[^gelmanhill2007] The remaining residual spread describes variation among reports after the fitted mean and event offset. These two sources of variation can compete to explain the data. We do not add final station effects because repeated locations and sparse coverage do not establish stable deployment identities.

### 4.2. Hierarchical NCEI duration model

The frozen selected NCEI form is

$$r_i\sim\mathcal N\!\left(\alpha+\beta x_i+\gamma b(d_i)+u_{e[i]},\ \sigma(d_i)^2\right),$$

$$b(d)=\log\!\left(\frac{d+500}{1.5d}\right),\qquad u_e\sim\mathcal N(0,\tau^2).$$

Here $\mathcal N(\mu,v)$ has mean $\mu$ and variance $v$. The event offset $u_e$ shifts the mean for event $e$; $\tau$ measures its spread across events. The curvature basis $b(d)$ is zero at 1,000 km, so $\alpha$ is the log median/reference ratio there for zero event offset. The curvature coefficient $\gamma$ describes the chosen statistical curve, not an identified shelf delay or physical correction.

Residual standard deviations $s_j$ are specified at anchors $a_j\in\{500,2000,5000\}$ km. Between adjacent anchors,

$$\sigma(d)=(1-w)s_j+ws_{j+1},\qquad w=\frac{\log d-\log a_j}{\log a_{j+1}-\log a_j}.$$

Outside the anchor range, the endpoint SD is held constant. We interpolate SD itself, not its logarithm, and impose no monotonicity constraint. Independent priors are $\alpha\sim\mathcal N(0,0.5^2)$, $\beta\sim\mathcal N(0,0.25^2)$, $\gamma\sim\mathcal N(0,0.5^2)$, and $\tau,s_j\sim\operatorname{HalfNormal}(0.4)$. These scales reflect analyst choices informed by exploratory data analysis (EDA); they are not physical constants or upper bounds.

### 4.3. Separate NTWC models

For T-OBS, the selected model is $r_i\sim\mathcal N(\alpha_O,\sigma_O^2)$, with $\alpha_O\sim\mathcal N(0,0.5^2)$ and $\sigma_O\sim\operatorname{HalfNormal}(0.4)$. Pooling applies to the log-relative duration. The median in minutes still increases with distance through $t_0(d)$.

For T-CAL, the model operates directly in signed minutes:

$$\Delta_i\sim\mathcal N(\alpha_C+\beta_C x_i,\sigma_C^2).$$

Its priors are $\alpha_C\sim\mathcal N(0,30^2)$ minutes, $\beta_C\sim\mathcal N(0,15^2)$ minutes per unit log distance, and $\sigma_C\sim\operatorname{HalfNormal}(30)$ minutes. Neither selected NTWC model includes event or station terms. The comparisons below explain why we retain these simpler forms.

### 4.4. Computation and predictive criticism

Each full fit uses four chains, 1,000 tuning steps and 2,000 retained draws per chain, with target acceptance 0.95. Implementation checks cover density, gradients, saved-summary replay, and simulation-based recovery/calibration for relevant development models. Six fixed-truth runs additionally check the selected computations; they are not calibration or coverage studies.

We assess rank-normalized $\widehat R$ and effective sample size,[^vehtari2019rhat] along with divergences and maximum-depth behavior. We then simulate reports from the fitted model and ask whether their sample quantiles resemble the observed ones. These conditional posterior predictive checks use five distance strata, three quantiles, and two displayed scales: 30 diagnostic cells per target. A cell is flagged when the observed statistic lies outside the replicated central 90% interval. Overlapping strata and correlated quantiles make the cells dependent; the two T-CAL scales also duplicate the same evidence. Their flagged counts measure diagnostic discrepancies, not predictive coverage.

## 5. Predictive comparisons and visual design

### 5.1. Sequence-aware predictive comparisons

The development split assigns 38 archive entries to exploration and 19 to a later check. Both sets had already been inspected in EDA, so the later check is not an independent test. Metadata groups related entries into source sequences. Holding out an entire sequence reduces leakage between related events. The main NCEI comparison uses 1,064 exploration reports from 33 events in 29 sequences. T-OBS uses 236 reports in 13 sequences; T-CAL uses 156 reports in 12 sequences.

We score how much predictive probability density a model assigns to the omitted reports. Higher log scores indicate better predictions within a target. Dividing each event's joint score by its report count and then averaging gives each event equal weight:

$$S=\frac{1}{J}\sum_{e=1}^{J}\frac{\log p(\mathbf y_e\mid\mathcal D_{-q(e)})}{n_e},$$

Here $q(e)$ is event $e$'s source sequence and $n_e$ its report count. Joint integration preserves dependence among reports sharing a new-event effect. Duration scores include the transformation back to native-minute density once. Comparisons use the same target and cohort. We report numerical Monte Carlo error separately from uncertainty across sequences; the latter also depends on metadata grouping and overlapping training sets.

Model forms and priors were fixed before the 19-entry check. One source sequence crosses the original split, so its exploration member is removed from every model's check training set. All eligible development records are then restored for the fixed full fits. The 18 reserved outcomes remain sealed and contribute no results.

### 5.2. How the figures support model decisions

The three figures follow the modeling decisions. **Figure 1 asks what the event effect is explaining:** it places residual spread beside estimated event variation, so changes in one can be read against the other. **Figure 2 asks whether added curvature helps prediction:** it pairs score differences with predictive probability checks, keeping between-sequence uncertainty visible. **Figure 3 asks how uncertain a new report remains:** it shows the fitted median and new-report prediction together, in minutes.

In Figure 3, dark intervals describe the population median; lighter intervals add new-report variation, including a new-event offset for NCEI. A narrow dark interval can therefore sit inside a wide light interval. Durations use logarithmic axes and signed differences a linear axis. Hatching marks distance extrapolation; a separate mark identifies NCEI SD clamping. The nine points are saved predictions, with no additional evaluation along their connectors. Intervals are central 90% and pointwise.

These static views use established encodings. We have not evaluated them in a user study or measured their effect on decisions. The separate visual-story prototype is not an evaluated system in this paper.

## 6. Results

### 6.1. Event variation depends on residual specification

For the same 1,064 NCEI exploration reports from 33 events, the estimated event SD changes from 0.352 [0.220, 0.510] with constant residual spread to 0.046 [0.029, 0.084] with distance-varying spread (Figure 1). These are posterior medians and central 90% intervals. The change follows a change in the residual model, not a comparison of prior settings. Much of what the constant-spread model attributes to events can instead be represented by distance-dependent spread. Neither decomposition identifies physical variation between tsunamis.

![Changing residual spread changes the attribution of NCEI event variation. Both models use the same 1,064 exploration reports from 33 events. The figure compares their distance-dependent spread and event-effect summaries; uncertainty concerns the fitted statistical models.](figures/residual-spread-and-event-variation.png)

**Figure 1.** Residual specification and event attribution for the same 1,064 NCEI reports from 33 exploration events. Bands and bars are central 90% posterior intervals. Changing the residual specification changes the estimated event variation; neither decomposition identifies physical variance. Source: NOAA NCEI.

### 6.2. The predictive gain from curvature remains uncertain

Distance improves NCEI prediction relative to the pooled log-relative model: the score difference is 0.423 nats per report [0.111, 0.736], with a descriptive 95% sequence-cluster interval. Among hierarchical models, scores are -6.2426 for a linear mean with constant spread, -5.8490 for a linear mean with varying spread, and -5.7651 for a curved mean with varying spread. The curved model's estimated gain over the linear varying-spread model is 0.0839 nats per report, with an interval of [-0.0487, 0.2165] (Figure 2). This interval does not establish that curvature predicts better. Monte Carlo standard errors near 0.0001 show precise numerical integration of the hierarchical scores; they do not resolve the much larger uncertainty across sequences.

The NTWC comparisons also leave the value of event effects uncertain. The event-minus-pooled T-OBS difference is -0.424 [-1.382, 0.534] nats per report; the event-minus-distance T-CAL difference is 0.0205 [-0.0988, 0.1397]. Both use descriptive 95% sequence-cluster intervals. We retain the simpler NTWC forms without concluding that the alternatives are equivalent.

![Omitted-sequence score differences and predictive diagnostics for the NCEI mean-form comparison. The original figure retains sequence-cluster uncertainty and calibration strata; it does not supply reserved-test evaluation.](figures/sequence-prediction-and-probability-check.png)

**Figure 2.** Exploratory sequence-prediction comparison for 1,064 NCEI reports, 33 events and 29 sequences. Positive score differences favor the curved, varying-spread specification; bars show descriptive 95% sequence-cluster intervals. For each omitted report, panel B uses the predicted probability that a new report would have a shorter duration. It plots the cumulative distribution of these probabilities with equal event weights; the diagonal is the reference for uniform probabilities. Shading is the curved model's descriptive 95% sequence-bootstrap band, based on the largest bootstrap deviation across evaluated probabilities, not a uniformity test. Numerical precision and between-sequence uncertainty are distinct. Source: NOAA NCEI.

### 6.3. Full-development estimates and predictions

Every parameter interval in this subsection is a central 90% posterior interval; prediction intervals additionally include modeled report variation.

![Native-minute uncertainty for the three frozen models. Dark intervals summarize the population median; light intervals predict a new report. Logarithmic duration axes, the signed discrepancy axis, extrapolation hatching and residual-scale clamping distinguish the quantities being displayed.](figures/median-and-new-report-intervals.png)

**Figure 3.** Full-development median and new-report intervals from nine saved distances. All intervals are central 90% and pointwise. NCEI predictions include a new event offset; the NTWC forms have no event term. The signed difference is estimated minus observed UTC. Hatching marks distance extrapolation. NCEI residual SD is separately held constant below 500 km and above 5,000 km. These archive-conditional distributions are not validated physical arrival forecasts. Sources: NOAA NCEI and NTWC.

The NCEI full fit has curvature coefficient $\gamma=0.546$ [0.428, 0.661] and event SD $\tau=0.0655$ [0.0436, 0.0981]. Residual SD medians at 500, 2,000 and 5,000 km are 0.632, 0.691 and 0.0993. The fitted spread is smaller at the far anchor under this model and archive. The nonzero curvature coefficient does not settle the predictive comparison: a parameter conditional on one model answers a different question from predicting omitted events.

For T-OBS, $\alpha_O=0.102$ [0.0562, 0.148] and $\sigma_O=0.442$ [0.411, 0.476]. At 1,000 km, the median duration is 93.2 [89.0, 97.5] minutes. A new report has a much wider 90% predictive interval: [44.2, 200.9] minutes. Figure 3 makes this distinction visible. Estimating the center precisely does not make an individual report equally predictable.

For T-CAL, $\alpha_C=-6.73$ [-11.59, -1.91] minutes and $\beta_C=-9.67$ [-12.44, -6.98] minutes per unit log distance, with residual SD 25.2 [23.1, 27.6] minutes. The fitted center becomes more negative with distance in these reports. Yet at 1,000 km, the new-report interval spans -48.3 to +32.7 minutes: estimates can fall on either side of observations. The slope describes the archive; it does not explain an operational bias mechanism.



### 6.4. Good sampling does not ensure a good predictive fit

All three full fits have zero divergences and zero maximum-depth hits. The largest $\widehat R$ is 1.00145; the smallest bulk and tail effective sample sizes are approximately 2,984 and 3,804. These diagnostics support the reported posterior calculations, without proving global exploration or model adequacy.

Predictive checks give a less reassuring result. Observed quantiles fall outside their replicated central 90% intervals in 20 of 30 NCEI cells, 21 of 30 T-OBS cells, and 10 of 30 T-CAL cells. These dependent counts are not estimates of prediction coverage. They show that the models miss important features of the reported distributions, even after fitting all eligible development records.

### 6.5. Sensitivity and incomplete comparisons

Of 55 prespecified sensitivity probes, 54 yield usable fits. The linear NCEI model restricted to 2014 onward remains unresolved after a reviewed retry fails the divergence screen. The usable curved-model result cannot replace that comparison or establish robustness in favor of curvature.

In the later development check, numerical precision failures leave two aggregate joint scores unavailable: NCEI linear varying-spread and pooled T-CAL. Their marginal predictions are retained. A separately reviewed integration resolves the selected NCEI score failure without changing its model, priors, training records, or marginal predictions. The remaining gaps, small NTWC datasets, and prior EDA exposure limit comparisons.

## 7. Discussion and limitations

An event SD measures variation left for the hierarchy under the chosen residual model. Its large change in Figure 1 shows why a precise estimate can still depend strongly on that decomposition. Source, path, origin, and reporting differences may all contribute to the event term; this archive cannot separate their causes.

The negative T-CAL slope has a similar limit: distance cannot distinguish unresolved forecast-version, source-ancestry, and arrival-definition effects. Repeated locations do not verify instrument continuity, and a shared distance range does not establish transfer to new stations, regions, deployments, or sequences.

Pair eligibility is selective, with an unidentified missingness mechanism. The likelihoods omit unmeasured onset and rounding uncertainty, site effects, cross-source dependence, and product-version effects. Predictive mismatch, two joint-score gaps, and one unresolved era stress remain. The EDA-exposed development check and sealed reserved outcomes preclude a claim of independent predictive validation.

Further work should resolve deployment identities, arrival definitions, and versioned forecasts before adding measurement layers or interpreting operational calibration. Predictive discrepancies need a new development protocol. Reserved evaluation requires a metadata-only sequence-overlap audit and a fixed assessment contract, without tuning on those outcomes.

## 8. Reproducibility and data availability

Preserved sources, native cells, eligibility rules, and checksums document the data. Portable artifacts record cohorts, priors, seeds, posterior summaries, predictive checks, sequence scores, and failed or unresolved runs. A lockfile pins the environment. Local experiment tracking mirrors these records; large posterior files and source-response caches remain local with hashes.

Numbers and figures use accepted saved tables without new fitting or prediction. The evidence index links tables to claims, and repository instructions describe reproduction. A stable, appropriately anonymized replication package and sharing link still require author verification; public access to source data alone does not provide that package.

## 9. Conclusion

Distance-dependent residual spread changes the variation attributed to events, while curvature's predictive gain remains uncertain and satisfactory sampling coexists with predictive mismatch. These results describe selected archive reports; physical-arrival accuracy and operational forecast performance remain unvalidated.

[^noaa_warning]: NOAA, *Detection, Warning, and Forecasting* (accessed November 9, 2026). [@noaa_warning]

[^ncei_travel_maps]: NOAA NCEI, *Tsunami Travel Time Maps* (accessed November 9, 2026). [@ncei_travel_maps]

[^ncei_tsunami_data]: NOAA NCEI, *Introduction to Global Historical Tsunami Data* (accessed November 9, 2026). [@ncei_tsunami_data]

[^coffing2026]: S. X. Coffing and colleagues, *Reduced Order Modeling for Tsunami Forecasting With Bayesian Hierarchical Pooling*, JAMES (2026). [@coffing2026]

[^gelman2020workflow]: A. Gelman and colleagues, *Bayesian Workflow*, arXiv:2011.01808 (2020). [@gelman2020workflow]

[^gabry2017visualization]: J. Gabry and colleagues, *Visualization in Bayesian Workflow*, JRSS A (2019). [@gabry2017visualization]

[^talts2018sbc]: S. Talts and colleagues, *Validating Bayesian Inference Algorithms with Simulation-Based Calibration*, arXiv:1804.06788 (2018). [@talts2018sbc]

[^ntwc_messages]: National Tsunami Warning Center, *Previous Tsunami Messages* (accessed November 9, 2026). [@ntwc_messages]

[^gelmanhill2007]: A. Gelman and J. Hill, *Data Analysis Using Regression and Multilevel/Hierarchical Models*, Cambridge University Press (2007). [@gelmanhill2007]

[^vehtari2019rhat]: A. Vehtari and colleagues, *Rank-Normalization, Folding, and Localization: An Improved $\widehat{R}$ for Assessing Convergence of MCMC*, Bayesian Analysis (2021). [@vehtari2019rhat]

## Acknowledgments

We acknowledge NOAA's National Tsunami Warning Center and National Centers for Environmental Information, the USGS, and the original observing and reporting organizations. OpenAI ChatGPT/Codex assisted with analysis-code development, numerical verification, figure-generation code, and drafting and editing this manuscript. The human authors retain responsibility for the final scientific content and submission.

## References
