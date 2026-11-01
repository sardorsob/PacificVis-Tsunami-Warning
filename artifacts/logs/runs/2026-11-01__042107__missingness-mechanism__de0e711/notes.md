# Missing historical arrival pairs

The unresolved-pair rate combines source omissions, incomplete calendar metadata,
uncertain meaning and structural rows. It is not a download-loss rate. Of 789
unresolved rows, 513 lack a source time entry, 230 have unresolved calendar/day
context, 35 are structural/blank and 11 have qualified/footnoted/semantic values.
These mutually exclusive current-state groups account for all 1,177 retained
NTWC development table rows together with 388 exact pairs. Source-absence rows
are 224 missing-estimate-only, 216 missing-observation-only and 73 missing-both.

All 229 complete pairs outside the 159-row geographic candidate view are held
solely for geographic identity review. Among 289 rows lacking observed times,
273 retain a literal positive peak-height number. Original source headers
separate measured peaks from modeled amplitude; this supports a reporting/pick
metadata gap, without proving why a pick was omitted or that it is recoverable.

Prioritize targeted date/semantic/geographic review, then original forecast and
dated observation products. Expand events/stations for explicit coverage gaps.
Missing source values may exist elsewhere; new waveforms cannot provide an
original historical forecast. Never infer dates from agreement with the forecast,
replace initial arrivals with maximum-wave times, or treat imputation as truth.
Missingness is associated with source/format/era; observed data cannot identify
MAR versus MNAR. No model, label, date, identity or accepted product was changed.
No reserved outcomes were inspected and no bulk acquisition was performed.

Reproduce from the repository root with `.venv/bin/python PATH_TO_THIS/analyze.py`.
It reads the hash-pinned ignored scientific cache and writes the ignored
`artifacts/generated/ntwc-batch/missingness-mechanism-v1/` diagnostic outputs.
Every report-level cause is retained there in report-causes.csv; its digest is
in outputs.json. The main raw/processed scientific products remain unchanged.
The script checks all memberships and 1,142 raw-field/token mappings. A separate
readback independently reproduces the taxonomy, height cooccurrence and original
HTML examples. Verification repeated the audit with byte-identical outputs;
application tests were not rerun because no production source or data changed.

Original examples: [Tohoku](https://www.tsunami.gov/previous.events/?p=03-11-11_Honshu),
[Peru 2001](https://www.tsunami.gov/previous.events/?p=06-23-01), and
[Kuril 2007](https://www.tsunami.gov/previous.events/01-13-07/01-13-07.html).
A linked [historical forecast table](https://www.tsunami.gov/previous.events/01-13-07/0113forecast.html)
contains dated local-zone estimates that differ from some main-table clocks;
product issue/version lineage must be reviewed before pairing.
[CO-OPS API documentation](https://api.tidesandcurrents.noaa.gov/api/prod/)
defines predictions as tides/water levels, not historical tsunami ETAs.
