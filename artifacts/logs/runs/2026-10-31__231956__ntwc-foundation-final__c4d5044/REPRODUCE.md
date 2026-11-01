# Final data-foundation evidence

This run records the completed finite data acquisition and descriptive exports.
It does not certify physical onsets, deployments, model eligibility, or publication
rights. Data versions and full file inventories are in outputs.json; input and
code hashes are in inputs.json and the copied independent acceptance receipts.
Raw data remain in the repository's ignored cache, identified by path, size and
checksum in acquisition-inventory.json. Copy that cache and the pinned code/config
files with the project when moving this run; this compact bundle does not embed
all scientific data.

Run commands from the project root using its Python environment. config.json
records the consolidation arguments; the data guide gives waveform/catalog
build commands. Always rebuild into a new directory. Review tools are byte-for-byte
copies of the executed independent checks. Some preserve the original checkout
or temporary replay paths; inspect their arguments before using a relocated
checkout. Do not rerun evidence writers over frozen receipts. For waveform row
conservation, supply the final waveform folder, a fresh replay folder and a new
review-receipt path. The catalog verifier takes the catalog folder as its argument.
The saved pytest module imports its sibling record_ntwc_foundation_final.py.

bundle-manifest.json hashes every other file in this run, including this guide,
review tools, review receipts and environment metadata. Its own hash is recorded
by the separate final-bundle-mlflow-review-v1.json receipt, also logged to the same
MLflow run under checks/final-bundle-readback. No late file additions are omitted
from MLflow: the entire completed bundle is re-logged under portable-run and
independently compared to the local artifact-store copy.
