# Artifacts

`provenance/` contains tracked source and processing evidence. Large generated
figures and tables belong under ignored `generated/` paths until a task curates
them. `logs/runs/` holds compact, portable run bundles; keep metadata and small
evidence tracked while referencing large inputs/outputs by checksum and location.

Every reportable artifact must record its producing command, Git commit, input
source IDs and checksums, output checksum, units, CRS/time basis where relevant,
and review disposition. Generated artifacts are never hand-edited.

For T-002, each meaningful execution writes
`logs/runs/<YYYY-MM-DD__HHMM__tag__gitsha>/` containing `meta.json`,
`config.json`, `inputs.json`, `outputs.json`, `metrics.json`, and `notes.md`.
Acquisition, data-quality, and EDA working summaries are retained locally.
Curated scientific reports remain alongside their checksummed evidence under
`eda/`; internal planning and review conversations are excluded from Git.

Stage A visual-story runs write generated diagnostics beneath
`eda/story/<run_id>/` and a matching six-file portable bundle beneath
`logs/runs/<run_id>/`. Each story atlas contains four numbered PNG/SVG pairs,
`atlas-manifest.json`, and `decision-ledger.csv`. The manifest labels every file
`preliminary_storyboard_evidence`, records input and output checksums, and keeps
the blocked continuous NCTR field, incompatible units, local panel scales, and
manual-review state explicit. These exploratory files never flow directly into
`app/public/data/`; a later reviewed promotion requires a separate manifest.
