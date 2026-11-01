# Recovered tsunami data release

This bundle pins the completed acquisition, extraction, native samples and
candidate reported targets. It does not certify physical onsets or a fitted model.
See `docs/data/multi-event.md` for table definitions, current products and limits.

Use the project Python environment from the repository root. Required scientific
source bytes and generated inputs remain in the ignored local data cache. Raw
redistribution is not authorized by this bundle. Original request contracts are
saved verbatim in each acquisition run's `config.json`; their body/query/hash and
outcome records are in `inputs.json` and `outputs.json`. No credentials are needed
for the new public NOAA sources.

`reproduction/ncei-final-build-command.json` saves the exact NCEI CLI argument
array. `reproduction/build_final_ncei.py NEW_OUTPUT_DIRECTORY` rebuilds from its
pinned local receipts; the source-review copies preserve the reviewed event map
and official field-definition locators. Use a new output directory; never edit
existing scientific products. The other replay and profile tools preserve source
conservation, frozen-product checks and denominators. The earlier corpus/waveform
and consumer builders are documented in the data guide and their pinned manifests.

`verification.json` records the final gate. The first full-suite log captures a
test-only global-clock mock failure; the fail-first regression and independent
review are retained. A module-local test clock fixed it without production or
data changes. The final full suite passed 761 tests. Frontend checks passed 178
tests, type checking and build. Source ledgers validated 19/2253/2388 records.

`reproduction/mlflow-stage-index.json` maps ten logical recovery stages to their
portable bundles and project-local MLflow IDs. Registration occurs after review;
original acquisition/build timestamps remain in their receipts. File-store use
requires `MLFLOW_ALLOW_FILE_STORE=true`. No tracking server or migration was added.
