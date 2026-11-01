"""Offline report-level diagnosis; never changes accepted scientific products.

Run from the repository root with the project Python environment. Rates use
retained NTWC table rows, not stations, wave samples or a population of tsunamis.
Structural rows include separators. Every category has report-level membership.
"""

from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path.cwd()
OUT = ROOT / "artifacts/generated/ntwc-batch/missingness-mechanism-v1"
CORPUS = ROOT / "data/processed/arrival-corpus/foundation-v5"
INPUTS = {}


def pin(path):
    INPUTS[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(relative):
    path = ROOT / relative
    pin(path)
    return json.loads(path.read_text())


def read_csv(path):
    pin(path)
    with gzip.open(path, "rt") as handle:
        return list(csv.DictReader(handle))


inventory = read_json("artifacts/generated/ntwc-batch/recovery-inventory-v1/reports.json")
old = {row["report_id"]: row for row in inventory}
delta_rows = read_json("artifacts/generated/ntwc-batch/recovery-design-v1/recovery_delta.json")
delta = {row["report_id"]: row for row in delta_rows}
summary = read_json("data/processed/arrival-corpus/foundation-v5/summary.json")
assert len(old) == len(inventory) == len(delta) == len(delta_rows) == 1177
assert set(old) == set(delta)
reports = {}
events = {}
pair_ids = set()
eligibility = {}
for folder in sorted(CORPUS.iterdir()):
    if not folder.is_dir():
        continue
    event = read_csv(folder / "event.csv.gz")[0]
    assert event["role"] == "development"
    events[event["event_id"]] = event
    for row in read_csv(folder / "arrival_report.csv.gz"):
        assert row["report_id"] not in reports
        reports[row["report_id"]] = row
    for row in read_csv(folder / "pair.csv.gz"):
        assert row["report_id"] not in pair_ids
        assert row["model_eligible"] == row["physical_onset_validated"] == "False"
        pair_ids.add(row["report_id"])
    for row in read_csv(folder / "target_eligibility.csv.gz"):
        if row["target_id"] == "T-CAL":
            eligibility[row["report_id"]] = row
assert set(reports) == set(old) == set(eligibility)
assert pair_ids == {key for key, row in delta.items() if row["new_pair"]}

absent = {"blank", "source_absent_explicit"}
calendar = {"date_ambiguous", "calendar_context_missing", "day_semantics_unverified"}
counts = Counter()
presence = Counter()
structural = Counter()
inherited = Counter()
families = defaultdict(Counter)
era = defaultdict(Counter)
by_event = defaultdict(Counter)
pair_exclusions = Counter()
heights = Counter()
ledger = []
raw_rows_checked = 0
for key, row in sorted(reports.items()):
    baseline, change = old[key], delta[key]
    raw = json.loads(row["raw_row_json"])
    assert row["estimate_state"] == change["new_estimated_state"]
    assert row["observed_state"] == change["new_observed_state"]
    assert row["source_sha256"] == baseline["source_sha256"]
    source = ROOT / baseline["source_path"]
    if str(source.relative_to(ROOT)) not in INPUTS:
        pin(source)
    assert INPUTS[str(source.relative_to(ROOT))] == row["source_sha256"]
    # Verify the parent page digest and retained raw field/token consistency.
    # Separate source-review findings check original HTML header/row examples.
    states = {row["estimate_state"], row["observed_state"]}
    valid = row["structural_status"] == "accepted_source_row"
    if not valid:
        cause = "structural_or_blank_row"
        structural[row["structural_status"]] += 1
    elif key in pair_ids:
        cause = "resolved_pair"
    elif states & absent:
        cause = "source_time_entry_absent"
    elif "qualified_value" in states:
        cause = "qualified_clock"
    elif "footnoted_value" in states:
        cause = "footnoted_clock"
    elif "legacy_semantics_unverified" in states:
        cause = "column_meaning_unverified"
    elif states & calendar:
        cause = "calendar_or_day_context_unresolved"
    else:
        raise AssertionError((key, states))
    inherited["resolved_pair" if key in pair_ids else baseline["time_gap"]] += 1
    if valid:
        estimate_present = baseline["estimate_presence"] == "source_entry_present"
        observed_present = baseline["observed_presence"] == "source_entry_present"
        assert (row["estimate_state"] not in absent) == estimate_present
        assert (row["observed_state"] not in absent) == observed_present
        assert (estimate_present and observed_present) == (cause != "source_time_entry_absent")
        fields = raw["fields"]
        estimate = fields.get("estimated_arrival", fields.get("eta_as_labeled"))
        observed = fields.get("observed_arrival", fields.get("arrival_as_labeled"))
        assert estimate is not None and observed is not None
        expected_estimate = row["legacy_eta_raw"] if row["header_family"] == "arrival_eta_utc" else row["estimated_raw"]
        expected_observed = row["legacy_arrival_raw"] if row["header_family"] == "arrival_eta_utc" else row["observed_raw"]
        assert " ".join(estimate.split()) == " ".join(expected_estimate.split())
        assert " ".join(observed.split()) == " ".join(expected_observed.split())
        raw_rows_checked += 1
        if cause == "source_time_entry_absent":
            subtype = "estimate_only_absent" if not estimate_present and observed_present else "observed_only_absent" if estimate_present and not observed_present else "both_absent"
            presence[subtype] += 1
        peak = fields.get("peak_amplitude", fields.get("wave_height_peak_to_trough", "")).strip()
        positive_peak = bool(re.fullmatch(r"[+]?\d+(?:\.\d+)?", peak)) and float(peak) > 0
        if not observed_present:
            heights["observed_time_absent"] += 1
            heights["observed_time_absent_with_literal_positive_peak_number"] += positive_peak
            if row["event_id"] == "official20110311054624120_30":
                heights["tohoku_observed_time_absent"] += 1
                heights["tohoku_observed_time_absent_with_literal_positive_peak_number"] += positive_peak
        if not observed_present and estimate_present:
            heights["estimate_present_observed_time_absent"] += 1
            heights["estimate_present_observed_time_absent_with_literal_positive_peak_number"] += positive_peak
    else:
        subtype = "not_applicable_structural"
    counts[cause] += 1
    event = events[row["event_id"]]
    year = event["calendar_year"]
    period = "unknown" if year == "unknown" else "before_2010" if int(year) < 2010 else "2010_onward"
    for group in (families[row["header_family"]], by_event[row["event_id"]], era[period]):
        group["retained_rows"] += 1
        group[cause] += 1
        group["T_CAL_candidates"] += eligibility[key]["eligible"] == "True"
    reasons = json.loads(eligibility[key]["reason_codes"])
    if key in pair_ids:
        pair_exclusions[";".join(reasons) or "eligible_candidate"] += 1
    ledger.append({"report_id": key, "event_id": row["event_id"], "header_family": row["header_family"], "cause": cause, "estimated_state": row["estimate_state"], "observed_state": row["observed_state"], "T_CAL_eligible": eligibility[key]["eligible"], "T_CAL_reasons": eligibility[key]["reason_codes"], "source_path": baseline["source_path"], "source_sha256": row["source_sha256"], "table_index": row["table_index"], "row_index": row["row_index"]})

expected = {"resolved_pair": 388, "source_time_entry_absent": 513, "calendar_or_day_context_unresolved": 230, "qualified_clock": 7, "footnoted_clock": 3, "column_meaning_unverified": 1, "structural_or_blank_row": 35}
assert dict(counts) == expected
assert sum(counts.values()) == summary["source_rows"] == 1177
assert sum(v for k, v in counts.items() if k != "resolved_pair") == 789
assert dict(presence) == {"estimate_only_absent": 224, "observed_only_absent": 216, "both_absent": 73}
assert pair_exclusions == {"geographic_identity_unreviewed": 229, "eligible_candidate": 159}
assert len(events) == 57 and raw_rows_checked == 1142
with (OUT / "report-causes.csv").open("w") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(ledger[0]))
    writer.writeheader()
    writer.writerows(ledger)
output = {"grain": "retained NTWC development table row, including structural/blank rows", "versions": {"corpus": "foundation-v5", "baseline_inventory": "recovery-inventory-v1", "delta": "recovery-design-v1"}, "counts": counts, "unresolved": 789, "cause_percent_of_unresolved": {k: round(v / 789 * 100, 6) for k, v in counts.items() if k != "resolved_pair"}, "source_absence_subtypes": presence, "structural_subtypes": structural, "inherited_R0_categories_for_reconciliation_only": inherited, "paired_T_CAL_disposition": pair_exclusions, "raw_field_readback_rows": raw_rows_checked, "positive_peak_number_cooccurrence": heights, "by_header_family": families, "by_era_descriptive_confounded": era, "by_event": by_event, "development_events": len(events), "events_with_any_retained_rows": len(by_event), "events_with_exact_pairs": sum(v["resolved_pair"] > 0 for v in by_event.values()), "events_with_rows_but_no_exact_pairs": sum(v["resolved_pair"] == 0 for v in by_event.values()), "input_sha256": dict(sorted(INPUTS.items())), "limits": ["No reserved outcomes inspected, new bulk download, model fit or label/date/identity promotion.", "Absent means absent from the downloaded source TABLE, not proof a measurement never existed elsewhere.", "Current-state categories supersede inherited R0 bucket names: two other-bucket survivors are now calendar-only, leaving 230 calendar cases.", "Rows with absent fields may have additional ambiguity in their remaining field; causes use the stated priority and are not independent mechanisms.", "Numeric peak cooccurrence is a literal native field check, not amplitude harmonization or validation of first-arrival truth.", "Header and era comparisons are descriptive and confounded by event/source selection; they do not establish a causal effect or MAR/MNAR identification.", "Conditional usable fraction among accepted-structure rows is 388/1142; excluding separators does not fix missing source entries."]}
(OUT / "summary.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
print(json.dumps({k: output[k] for k in ["counts", "cause_percent_of_unresolved", "paired_T_CAL_disposition", "positive_peak_number_cooccurrence", "by_header_family", "by_era_descriptive_confounded"]}, indent=2))
