## Branch registry (pre-registered in this plan; freeze unchanged in PE-00)

Thresholds are screening thresholds, not significance tests. Each branch has
at most two follow-up checks.

| ID | Trigger | Smallest check | Decision output |
| --- | --- | --- | --- |
| B1 Distance form | C3 binned-median r₀ has a monotone trend over > 0.1 log units across distance bins, or near-field departs | Geodesic vs NCEI `distFromSource`; near/far split; land-shadow flag | Covariate-form candidates (≤ 2 forms) |
| B2 Tails and outliers | > 2 % of rows with \|robust z\| > 3.5, or any \|r₀\| > log 2 | Source-cell review: later wave/definition, compound event, typo, origin; no edits | Likelihood-shape candidates; data findings |
| B3 Site effects | C4 site-effect MAD ≥ 0.5 × residual MAD, stable across ≥ 2 site keys and in the bootstrap | Site-type contrasts: coastal vs DART, provider, region | Crossed-site vs site-type-only candidate |
| B4 Event effects | C4 event-effect spread > residual MAD | Rank correlation with magnitude, depth, mechanism and region | Event-covariate candidates |
| B5 Heteroskedasticity | r₀ spread varies > 1.5× across distance or precision bins | Spread by family × distance bin | Variance-structure candidates |
| B6 Source and definition offsets | Within-event median difference between families, eras or tiers, or linked NTWC–NCEI pairs, > 1 min with a bootstrap interval excluding 0 | Within-event contrasts only | Source-offset term vs separate families |
| B7 Missingness | Availability differs > 15 points across era or format, or peak amplitude differs between reported and unreported rows | Within-event conditional comparisons | MAR covariate set; MNAR sensitivity design |
| B8 Influence | A C3–C5 summary flips sign or moves > 30 % with one event removed | Full leave-one-event-out profile | Weighting and holdout cautions |
| B9 Near-field and origin | Near-field r₀ departs, or origin differences are material relative to precision | Cutoff profile at 30 / 60 / 90 min of reference travel | Cutoff candidates |
| B10 T-CAL structure | C8 E−O trends with distance or product era | Within-event trend and era contrasts | Calibration-covariate candidates |
| B11 Cross-target comparability | C5 linked differences not ≈ 0 | Definition review on linked entities | Shared latent target vs separate families |

**Replication rule.** A decision output is *confirmed* if the frozen check on
confirmation shows the same direction, with magnitude within ×2 (or interval
overlap). Otherwise it is *tentative*, or *contradicted*.

