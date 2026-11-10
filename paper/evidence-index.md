# Evidence index for the manuscript

Paths below are relative to the repository root. They identify the completed
study at scientific source commit `46831fb9380a73dbe135cf2a65dda6b59fdc609e`.
This index adds no observations or analyses. Native source caches and posterior
arrays remain separate from the portable tables; checksums identify those inputs
without claiming that a public replication archive has already been deposited.

## Claim locations

| Manuscript claim | Evidence locator |
| --- | --- |
| 118 archive entries;57development/18reserved/43other;1,177NTWC rows/388pairs | `docs/data/multi-event.md`, scope and candidate table; frozen development metadata below |
| Missing-pair reasons and four documentary gap links | `docs/data/source-process.md`, first-reason and evidence-level tables; fields and rows have different denominators |
| 1,221→1,215NCEI reports;258T-OBS;169T-CAL and target event counts | Full summary `lanes[0..2].membership`; eligibility rule in model contract; native candidates distinct from included counts |
| Actual likelihoods, fixed reference, priors and curvature | Three config files below; point-density measurement rule; final full summary `lanes[].model`, `response`, `prior` |
| Event SD0.352→0.046 under changed residual specification | `distance-scale-fit-report-v1/between-event-spread-by-model.csv`, constant versus distance-scale, same1,064/33 exploration cohort |
| Pooled/distance/event comparisons for three targets | `sequence-predictive-comparison-v1/paired-score-differences.csv`, rows keyed distance/pooled/NCEI;event/pooled/T-OBS;event/distance/T-CAL |
| Curved-versus-linear NCEI sequence scores and uncertainty | `curvature-sequence-predictive-comparison-v1/model-scores.csv` and `paired-score-differences.csv`;33events/29sequence groups |
| Fullfit parameters/intervals, sampler diagnostics and predictive quantiles | Full summary `lanes[].parameters`, `diagnostics`, `curves` |
| 20/30,21/30,10/30PPC flags | Full summary `lanes[].conditional_ppc`, Boolean `observed_outside_replicated_central90`; correlated cells and duplicate signed scales |
| Frozen selected forms before19-entry development check | `specification-freeze-v1/model-selection.json`; EDA exposure and sequence purge retained |
| 54usable sensitivity fits/55probes/58calls; unresolved linear2014+ | Accepted sensitivity findings and full-development findings |
| Two missing aggregate comparisons and selected-NCEI numerical resolution | Full summary `lanes[].checks`; no replacement of original marginal predictions |
| Figure3 exact rendered data | Saved plotted-quantiles CSV and figure caption; central90pointwise intervals, nine distances, no additional prediction |
| Computational/review lineage and original failure retention | Full fit/report acceptance and project-local tracking receipt;17runs in final program |

## File identities

| File | SHA-256 |
| --- | --- |
| [docs/data/multi-event.md](../docs/data/multi-event.md) | `c0665b361c36f984a7afcc3286204a22dfa36ec95760c8b8df534ad3cd4d90a1` |
| [docs/data/source-process.md](../docs/data/source-process.md) | `ab4cbe04c1c41db29e6b668f9afbfcecace15398a2936feefe7ea31fd9e1b05b` |
| [config/arrival-model-contract-v1.toml](../config/arrival-model-contract-v1.toml) | `7cdb86c6c2ef8e57f23251fea10d852cffe9bd7b33d4241660dfa1069c5a6264` |
| [config/arrival-model-priors-v1.toml](../config/arrival-model-priors-v1.toml) | `5f7f48b167c8bb9ee21516d7c68eb76d5416404b6f501efa8de3f37139db7622` |
| [config/arrival-mean-curvature-v1.toml](../config/arrival-mean-curvature-v1.toml) | `18097d0f718ed43466c216e89bc36be14b4333bb48bfc021483a31185e2a1080` |
| [artifacts/models/arrival-timing/distance-scale-fit-report-v1/between-event-spread-by-model.csv](../artifacts/models/arrival-timing/distance-scale-fit-report-v1/between-event-spread-by-model.csv) | `68345a8d8966e7d80dd5f55ee1c08a5e7419cfe0ccc8ffadec8b980cbee676d8` |
| [artifacts/models/arrival-timing/sequence-predictive-comparison-v1/paired-score-differences.csv](../artifacts/models/arrival-timing/sequence-predictive-comparison-v1/paired-score-differences.csv) | `d96e05dc3dd41894abaf3faa3662ade4797e263e47bf535bc9ae7847cb3f9a87` |
| [artifacts/models/arrival-timing/curvature-sequence-predictive-comparison-v1/model-scores.csv](../artifacts/models/arrival-timing/curvature-sequence-predictive-comparison-v1/model-scores.csv) | `c6009799d100520fd7e4180849d34b69ead44d1ef39fd61d5af6b572fa006194` |
| [artifacts/models/arrival-timing/curvature-sequence-predictive-comparison-v1/paired-score-differences.csv](../artifacts/models/arrival-timing/curvature-sequence-predictive-comparison-v1/paired-score-differences.csv) | `30d0a6c28481ceb61f06c3fec7bdc780b0eb9b1b143d2a27adf5164f06ab7e85` |
| [artifacts/models/arrival-timing/specification-freeze-v1/model-selection.json](../artifacts/models/arrival-timing/specification-freeze-v1/model-selection.json) | `9360f0069bb8980a86d6b5d9e27c57be39a3862a5eb6038ae3da4cba711673e8` |
| [artifacts/models/arrival-timing/exploration-sensitivity-report-v1/findings.md](../artifacts/models/arrival-timing/exploration-sensitivity-report-v1/findings.md) | `f4d6f04a1015242865029521c82fc96980f7ac9fe1bf38727abd87c7dad49b40` |
| [artifacts/models/arrival-timing/full-development-analysis-v1/findings.md](../artifacts/models/arrival-timing/full-development-analysis-v1/findings.md) | `dee543a8c960db453f06aa1f69f2f0a7b96eb90dfa108eb69933ec19595c15b1` |
| [artifacts/models/arrival-timing/full-development-analysis-v1/summary.json](../artifacts/models/arrival-timing/full-development-analysis-v1/summary.json) | `7e55ca05a7b7d85df9faff99e4d6567c67285f41d668d0c9110dd694b1714f72` |
| [artifacts/models/arrival-timing/full-development-analysis-v1/review-acceptance.json](../artifacts/models/arrival-timing/full-development-analysis-v1/review-acceptance.json) | `5108ae32c540cc07916ecec9fd500a751a1178485245dcedec5366483a409f82` |
| [artifacts/models/arrival-timing/full-development-figures-v1/plotted-quantiles.csv](../artifacts/models/arrival-timing/full-development-figures-v1/plotted-quantiles.csv) | `38b614230a6cc0933d1ec3ce2b573816317c78fc03ccaf115c84513410db85f7` |
| [artifacts/models/arrival-timing/full-development-figures-v1/caption.md](../artifacts/models/arrival-timing/full-development-figures-v1/caption.md) | `b405dd1c0ae57bfcf27072f4e10c3ecd2561a6a3ec900d48e687ad0f7917ab50` |
| [artifacts/models/arrival-timing/full-development-v1/review-acceptance.json](../artifacts/models/arrival-timing/full-development-v1/review-acceptance.json) | `3b7e50e44f41a8adbc4994f600cc30f22cc829a3569c38f75b4b5f01f3232ff9` |
| [artifacts/models/arrival-timing/development-tracking-v1/mlflow-receipt.json](../artifacts/models/arrival-timing/development-tracking-v1/mlflow-receipt.json) | `ff94caafb79ab852e1369fe1dc1d08eb68a88425ad32b40efa52244dca3d362f` |
| [artifacts/eda/arrival-timing/frozen-inputs/development-event-metadata.csv](../artifacts/eda/arrival-timing/frozen-inputs/development-event-metadata.csv) | `cfd73bf800ee1afe52253d847f7446ed778eb9ee40b8205429b6429c052d9781` |
| [artifacts/eda/arrival-timing/frozen-inputs/response-record-event-station-counts.csv](../artifacts/eda/arrival-timing/frozen-inputs/response-record-event-station-counts.csv) | `a4c25e36f7fa62d4b412d211c73d4a38f7f5d7fbdbca6a254e994aa804c6a852` |
| [artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json](../artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json) | `0b421f67eaf9a47e2772a05d854b4615054802d373a8f98b4c1038c81f1c3feb` |
