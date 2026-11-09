"""Independent saved-cell QC; run only after Root collects the actual S5 report.

No fitting/scoring, no accepted-case posterior replay, and no acceptance Gate creation.
Fourteen fixed historical references use their reviewed seed/800-draw recipe.
"""

# pyright: basic

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from contextlib import contextmanager
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

ROOT = Path("/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times")
IDENTITY = ("view_id", "target", "kind", "role", "scenario", "prior_variant", "distance_mode")
TABLES = (
    "posterior-parameters",
    "population-median-and-predictive-quantiles",
    "supported-distance-sensitivity-changes",
    "conditional-predictive-checks",
    "training-cohorts-and-omissions",
)
GRID = (20, 50, 100, 500, 1000, 2000, 5000, 10000, 20000)
VISUAL_CHECKLIST = [
    "Open both actual PNGs at native resolution; inspect panels, axes, legends and source "
    "lines for clipping/overlap.",
    "Prior panels: separate source/form labels and central90 intervals; median bands "
    "distinct from predictive variation.",
    "Heatmap: the reviewed linear era2014plus gap, and curved gap only if exhausted, "
    "are hatched and labeled Unresolved; "
    "unsupported cells gray, never zeros.",
    "Diverging scale centered at zero and shared across NCEI forms; no visual ranking "
    "from the unresolved gap.",
    "Titles, units, uncertainty and qualifications readable at intended report size; "
    "preserve compact-preview text limitations.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def equal(value, expected):
    if expected is None:
        return value == ""
    if type(expected) is float:
        return (
            value != ""
            and math.isfinite(float(value))
            and math.isclose(float(value), expected, rel_tol=2e-12, abs_tol=2e-12)
        )
    return value == str(expected)


def source_cells(actual, expected):
    require(
        all(equal(actual.get(key, ""), value) for key, value in expected.items()),
        "saved source quantile/metadata differs",
    )


def unique_index(values, keys):
    result = {tuple(row[key] for key in keys): row for row in values}
    require(len(result) == len(values), "duplicate report table cell")
    return result


def change(source, baseline, positive, supported):
    if not supported:
        return None, None, None
    with localcontext() as context:
        context.prec = 60
        key = "log_q50" if positive else "q50"
        difference = Decimal(str(source[key])) - Decimal(str(baseline[key]))
        delta = float(difference)
        require(math.isfinite(delta), "unrepresentable signed/log median difference")
        if not positive:
            return delta, None, None
        ratio = float(difference.exp())
        representable = math.isfinite(ratio) and ratio > 0
        return delta, ratio if representable else None, representable


def interval(row, keys=("q05", "q50", "q95")):
    values = [row[key] for key in keys]
    require(
        all(type(v) in (float, int) and math.isfinite(v) for v in values)
        and values == sorted(values),
        "invalid source90 quantiles",
    )


def check_cells(views, tables, expected_views):
    by_id = {view["view_id"]: view for view in views}
    require(
        len(by_id) == len(views) == expected_views, "exact branch-specific source views required"
    )
    base = {(v["target"], v["kind"]): v for v in views if v["role"] == "base"}
    require(len(base) == 8, "eight source/form base views required")
    curve_index = unique_index(tables[TABLES[1]], ("view_id", "curve", "distance_km"))
    change_index = unique_index(tables[TABLES[2]], ("view_id", "distance_km"))
    ppc_index = unique_index(tables[TABLES[3]], ("view_id", "stratum", "scale", "quantile"))
    cohort_index = unique_index(tables[TABLES[4]], ("view_id",))
    checked, ppc_misses = Counter(), 0
    expected_columns = {name: set() for name in TABLES}

    def claim(name, actual, expected, view):
        expected = {**{key: view[key] for key in IDENTITY}, **expected}
        expected_columns[name].update(expected)
        for key, value in expected.items():
            if isinstance(value, (dict, list)):
                require(json.loads(actual[key]) == value, "structured source cell differs")
            else:
                require(equal(actual.get(key, ""), value), "source CSV cell differs")
        require(
            all(value == "" for key, value in actual.items() if key not in expected),
            "unexpected nonempty CSV cell",
        )

    for values in tables.values():
        require(all(row["view_id"] in by_id for row in values), "foreign/unresolved table view")
        for row in values:
            source_cells(row, {key: by_id[row["view_id"]][key] for key in IDENTITY})
    for view in views:
        saved, vid = view["summary"], view["view_id"]
        support = saved["support"]
        low, high = support["distance_km_min"], support["distance_km_max"]
        require(
            saved["membership"] == view["training_record_ids"]
            and support["records"] == len(saved["membership"]),
            "source membership/count mismatch",
        )
        require(
            saved["conditional_predictive_draws"] == 800
            and saved["native_predictive_means_or_variances_reported"] is False,
            "quantile-only800-draw source required",
        )
        same_base = base[view["target"], view["kind"]]
        require(
            set(view["training_record_ids"] + view["omitted_record_ids"])
            == set(same_base["training_record_ids"]),
            "cohort partition differs from source-specific base",
        )
        positive = view["target"] != "T-CAL"
        modeled = "log reference ratio" if positive else "signed minutes"
        parameter_rows = [r for r in tables[TABLES[0]] if r["view_id"] == vid]
        expected_parameters = []
        for group in ("parameters", "derived"):
            for source in saved[group]:
                interval(source)
                if "distance_km" in source and not source["within_training_distance_range"]:
                    continue
                expected = {
                    **source,
                    "row_type": group,
                    "units": "dimensionless"
                    if source.get("quantity", "").endswith("elasticity")
                    else modeled,
                    "interval_type": "90% marginal posterior interval",
                }
                matches = [
                    row
                    for row in parameter_rows
                    if all(equal(row.get(k, ""), v) for k, v in expected.items())
                ]
                require(
                    len(matches) == 1, "parameter/derived source row not represented exactly once"
                )
                require(
                    json.loads(matches[0]["prior_specification"]) == view["prior_specification"],
                    "prior label differs from frozen source settings",
                )
                claim(
                    TABLES[0],
                    matches[0],
                    {**expected, "prior_specification": view["prior_specification"]},
                    view,
                )
                expected_parameters.append(expected)
        require(len(expected_parameters) == len(parameter_rows), "extra parameter/derived rows")
        checked[TABLES[0]] += len(parameter_rows)
        originals = {
            r["distance_km"]: r
            for r in same_base["summary"]["curves"]
            if r["curve"] == "population_median"
        }
        require(
            len(saved["curves"]) == 18
            and {(r["curve"], r["distance_km"]) for r in saved["curves"]}
            == {(c, float(d)) for c in ("population_median", "new_event") for d in GRID},
            "fixed18 source curves required",
        )
        for source in saved["curves"]:
            interval(source)
            supported = low <= source["distance_km"] <= high
            require(
                source["within_training_distance_range"] is supported,
                "source range flag differs from numeric endpoints",
            )
            if positive:
                interval(source, ("log_q05", "log_q50", "log_q95"))
                require(
                    all(
                        source[q] > 0
                        and math.isclose(math.log(source[q]), source["log_" + q], abs_tol=1e-12)
                        for q in ("q05", "q50", "q95")
                    ),
                    "positive native/log quantiles incoherent",
                )
            key = (vid, source["curve"], str(source["distance_km"]))
            if supported:
                actual = curve_index[key]
                source_cells(actual, source)
                require(
                    actual["units"] == "minutes"
                    and actual["interval_type"]
                    == (
                        "90% posterior band for population median"
                        if source["curve"] == "population_median"
                        else "90% new-event report predictive quantiles"
                    ),
                    "curve interval/units mislabeled",
                )
                claim(
                    TABLES[1],
                    actual,
                    {
                        **source,
                        "units": "minutes",
                        "interval_type": "90% posterior band for population median"
                        if source["curve"] == "population_median"
                        else "90% new-event report predictive quantiles",
                    },
                    view,
                )
                checked[TABLES[1]] += 1
            else:
                require(key not in curve_index, "unsupported curve exported")
            if source["curve"] != "population_median":
                continue
            original = originals[source["distance_km"]]
            common = (
                supported
                and same_base["summary"]["support"]["distance_km_min"]
                <= source["distance_km"]
                <= same_base["summary"]["support"]["distance_km_max"]
            )
            delta, ratio, representable = change(source, original, positive, common)
            expected = dict(
                baseline_view_id=same_base["view_id"],
                common_supported=common,
                median_log_shift=delta if positive else None,
                native_median_ratio=ratio,
                native_ratio_representable=representable,
                signed_median_shift_minutes=delta if not positive else None,
                comparison="difference_of_marginal_posterior_medians_no_difference_interval",
                support_rule="intersection_of_training_distance_ranges_not_dense_coverage_proof",
            )
            source_cells(change_index[(vid, str(source["distance_km"]))], expected)
            claim(
                TABLES[2],
                change_index[(vid, str(source["distance_km"]))],
                {"distance_km": source["distance_km"], **expected},
                view,
            )
            checked[TABLES[2]] += 1
        for source in saved["conditional_ppc"]:
            actual = ppc_index[(vid, source["stratum"], source["scale"], str(source["quantile"]))]
            source_cells(actual, source)
            observed, lower, upper = [
                Decimal(str(source[k])) for k in ("observed", "replicated_q05", "replicated_q95")
            ]
            require(
                all(value.is_finite() for value in (observed, lower, upper)), "nonfinite source PPC"
            )
            outside = observed < lower or observed > upper
            source_cells(
                actual,
                dict(
                    observed_outside_replicated_90=outside,
                    units="minutes" if source["scale"] == "native-minutes" else modeled,
                    check_scope="conditional_fitted_events_in_sample_not_held_out",
                ),
            )
            claim(
                TABLES[3],
                actual,
                {
                    **source,
                    "observed_outside_replicated_90": outside,
                    "units": "minutes" if source["scale"] == "native-minutes" else modeled,
                    "check_scope": "conditional_fitted_events_in_sample_not_held_out",
                },
                view,
            )
            checked[TABLES[3]] += 1
            ppc_misses += outside
        cohort = cohort_index[(vid,)]
        for key, value in support.items():
            if isinstance(value, dict):
                require(json.loads(cohort[key]) == value, "cohort support map differs")
            else:
                require(equal(cohort[key], value), "cohort support scalar differs")
        for key in ("training_record_ids", "omitted_record_ids", "excluded_record_ids"):
            require(json.loads(cohort[key]) == view[key], "ordered cohort labels differ")
        source_cells(
            cohort,
            dict(
                omitted_count=len(view["omitted_record_ids"]),
                excluded_count=len(view["excluded_record_ids"]),
                new_sampler_calls=int(view["role"] == "sensitivity"),
                selection_interpretation="conditional_on_reporting_no_missingness_identification",
            ),
        )
        claim(
            TABLES[4],
            cohort,
            {
                **support,
                **{
                    key: view[key]
                    for key in ["training_record_ids", "omitted_record_ids", "excluded_record_ids"]
                },
                "omitted_count": len(view["omitted_record_ids"]),
                "excluded_count": len(view["excluded_record_ids"]),
                "new_sampler_calls": int(view["role"] == "sensitivity"),
                "selection_interpretation": (
                    "conditional_on_reporting_no_missingness_identification"
                ),
            },
            view,
        )
        checked[TABLES[4]] += 1
    require(
        all(checked[name] == len(tables[name]) for name in TABLES),
        "extra/missing numeric table rows",
    )
    require(
        all(
            set(row) == expected_columns[name] for name, values in tables.items() for row in values
        ),
        "CSV column inventory differs from independent source schema",
    )
    return dict(
        table_rows=dict(checked),
        ppc_outside_cells=ppc_misses,
        csv_cells=sum(len(row) for values in tables.values() for row in values),
    )


def program_contract(checked, source_pins, report):
    """Independent discrete accounting/protocol audit, before saved scientific bodies."""
    run, jobs = checked["run_summary"], checked["jobs"]
    orders = [u["order"] for u in run["unresolved_cases"]]
    require(orders in [[36], [36, 47]], "only reviewed unresolved36/optional47 permitted")
    healthy = orders == [36]
    expected_counts = dict(
        planned_cases=55,
        completed_probes=55,
        accepted_logical_fits=54 if healthy else 53,
        unresolved_case_count=len(orders),
        actual_sampler_calls=58,
        calls_charged=58,
        calls_started=58,
        retained_failed_calls=4 if healthy else 5,
        max_sampler_call_slots=110,
    )
    require(
        run["schema_version"] == 4
        and run["status"] == "sensitivity_program_complete_with_unresolved_cases"
        and run["case47_outcome"] == ("accepted_repair" if healthy else "exhausted_unresolved")
        and all(type(run[k]) is int and run[k] == v for k, v in expected_counts.items()),
        "exact typed schema4/58-call branch required",
    )
    require(
        len(jobs) == 55
        and [j["order"] for j in jobs] == list(range(55))
        and len({j["id"] for j in jobs}) == 55,
        "immutable original55 ordered jobs required",
    )
    accepted, failures = run["accepted"], run["retained_failures"]
    require(
        accepted == checked["accepted"]
        and failures == checked["failures"]
        and [e["order"] for e in accepted] == [n for n in range(55) if n not in orders]
        and len(failures) == expected_counts["retained_failed_calls"],
        "no lost/zero-filled original disposition or accepted relabeling",
    )
    require(
        Counter(e["order"] for e in failures) == Counter({34: 1, 36: 2, 47: 1 if healthy else 2}),
        "all four/five failed calls must remain explicit",
    )
    raw_names = [e["posterior"] for e in accepted] + [e["posterior"] for e in failures]
    require(
        len(raw_names) == len(set(raw_names)) == 58,
        "every actual call retains a distinct raw; failed raw cannot become accepted",
    )
    for u in run["unresolved_cases"]:
        require(
            u["original_job"] == jobs[u["order"]]
            and u["case_id"] == jobs[u["order"]]["id"]
            and u["status"] == "computationally_unresolved"
            and u["posterior"] is None
            and u["no_third_attempt"] is True
            and len(u["failed_attempts"]) == 2
            and u["failed_attempts"] == [f for f in failures if f["order"] == u["order"]],
            "unresolved case must retain both failures and no usable theta",
        )
    by_order = {e["order"]: e for e in accepted}
    repairs = [34, *([47] if healthy else [])]
    mapping = run["successful_numerical_repair_mapping"]
    require(
        set(mapping) == {jobs[n]["id"] for n in repairs}, "only successful34/optional47 repairs"
    )
    for n in repairs:
        require(
            all(
                mapping[jobs[n]["id"]][k] == by_order[n][k]
                for k in ["posterior", "posterior_sha256", "receipt", "receipt_sha256"]
            ),
            "successful repair must point to its literal accepted producer",
        )
    protocol = dict(
        draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
    )
    repair_protocol = {**protocol, "tune": 4000, "target_accept": 0.999}

    def execution(n, attempt=1, settings=protocol):
        return dict(
            id=f"ms5-numerical-protocol-v2-{n:03d}-attempt-{attempt}",
            order=n,
            original_job=jobs[n],
            attempt=attempt,
            sampler={**settings, "seed": jobs[n]["seed"]},
        )

    repair47, tail = execution(47, 2, repair_protocol), [execution(n) for n in range(48, 55)]
    require(
        run["repair_job"] == repair47
        and run["remaining_jobs"] == tail
        and [a["execution_job"] for a in run["completion_attempts"]] == [repair47, *tail]
        and all(a["charged_slots"] == a["start_markers"] == 1 for a in run["completion_attempts"]),
        "one final47 plus seven unchanged charged starts required",
    )
    require(
        run["protocol_amendment"]
        == dict(
            protocol=protocol,
            first_attempt_original_case_ids=[j["id"] for j in jobs[37:]],
            execution_jobs=[execution(n) for n in range(37, 55)],
            case47_final_repair=dict(
                execution_job=repair47,
                protocol=repair_protocol,
                worker_spec_gate=report.EXECUTION_GATE,
                worker_spec_gate_sha256=source_pins[report.EXECUTION_GATE],
            ),
            remaining_execution_jobs=tail,
        ),
        "original18, distinct final47, and unchanged seven protocols",
    )
    require(
        Counter(e["producer"] for e in accepted)
        == Counter(
            {
                "original": 35,
                "repair_v1": 1,
                "numerical_protocol": 17,
                **({"repair47": 1} if healthy else {}),
            }
        ),
        "producer counts must respect original35/A1/B17/optional47",
    )
    for e in accepted:
        n = e["order"]
        require(
            e["original_job"] == jobs[n] and e["case_id"] == jobs[n]["id"],
            "original source identity",
        )
        if n >= 37:
            gate = report.EXECUTION_GATE if n >= 47 else report.OLD_EXECUTION_GATE
            spec = report.EXECUTION_GATE if n == 47 else report.NUMERICAL_GATE
            require(
                e["execution_job"] == (repair47 if n == 47 else execution(n))
                and e["producer"] == ("repair47" if n == 47 else "numerical_protocol")
                and e["source_role"] == ("numerical_repair" if n == 47 else "numerical_protocol")
                and e["execution_gate"] == gate
                and e["worker_spec_gate"] == spec,
                "job-specific worker spec and execution authority cannot be exchanged",
            )
    for key, name in {
        "worker_spec_gate": report.NUMERICAL_GATE,
        "repair_spec_gate": report.EXECUTION_GATE,
        "execution_authority_gate": report.EXECUTION_GATE,
        "case47_disposition_review": report.SCIENTIFIC_REVIEWS["case47_disposition"],
    }.items():
        require(
            run[key] == name and run[key + "_sha256"] == source_pins[name],
            "literal reviewed Gate binding",
        )
    require(len(report.SCIENTIFIC_REVIEWS) == 7, "all seven scientific review parents required")
    return expected_counts


@contextmanager
def reference_only_nc(refs, root, raw_names):
    """Only the14 fixed reference paths may reach xarray's NetCDF reader."""
    original = refs.xr.open_dataset
    allowed = {(root / name).resolve() for name in raw_names}
    opened = []

    def guarded(path, *args, **kwargs):
        literal = Path(path)
        require(
            literal == literal.resolve() and literal in allowed,
            "non-reference NetCDF body read forbidden",
        )
        opened.append(str(literal.relative_to(root)))
        return original(path, *args, **kwargs)

    refs.xr.open_dataset = guarded
    try:
        yield opened
    finally:
        refs.xr.open_dataset = original


def source_case_paths(root, entry, report):
    producer, job = entry["producer"], entry["execution_job"]
    if producer == "original":
        return root / report.old.fit.OUTPUT / "jobs" / job["id"], root / report.old.fit.STORE / (
            job["id"] + ".nc"
        )
    if producer == "repair_v1":
        return root / report.repair.OUTPUT, root / report.repair.STORE
    require(producer in {"numerical_protocol", "repair47"}, "literal known producer required")
    # The final47 shares native B storage; it must not acquire the old B admission.
    return root / report.NUMERICAL_OUTPUT / "jobs" / job[
        "id"
    ], root / report.numerical_api().STORE / (job["id"] + ".nc")


def science_parents(root, pins, report, run):
    expected = {
        "first34": "accepted_sensitivity_thirty_four_case_checkpoint",
        "repair_v1": "accepted_sensitivity_same_model_numerical_repair",
        "baseline_v2": "accepted_sensitivity_remaining_numerical_protocol_plan",
        "unresolved_case": "accepted_sensitivity_unresolved_case_disposition",
        "baseline50": "accepted_late_sensitivity_repair_and_tail_plan",
        "case47_disposition": "accepted_sensitivity_case47_disposition",
        "remaining": "accepted_finished_sensitivity_computations",
    }
    require(
        set(report.SCIENTIFIC_REVIEWS) == set(expected), "seven exact scientific parents required"
    )
    result = {}
    for key, status in expected.items():
        name = report.SCIENTIFIC_REVIEWS[key]
        require(name in pins and sha(root / name) == pins[name], "scientific parent source drift")
        value = read(root / name)
        require(
            value["status"] == status
            and value["independent_checker"] is True
            and value["confirmation_outcomes_parsed"] is False
            and value["reserved_outcomes"] == "sealed"
            and all(pins.get(p) == digest for p, digest in value["files"].items()),
            "scientific parent status/exposure/full closure mismatch",
        )
        if key == "case47_disposition":
            require(
                value["case47_outcome"] == run["case47_outcome"]
                and value["calls_charged"] == value["calls_started"] == 51
                and value["repair_job"] == run["repair_job"]
                and value["execution_authority_gate_sha256"] == pins[report.EXECUTION_GATE]
                and value["repair_spec_gate_sha256"] == pins[report.EXECUTION_GATE],
                "typed51 disposition must bind genuine repair spec and execution authority",
            )
        result[key] = {"path": name, "sha256": pins[name], "status": status}
    return result


OLD_QUALIFICATION_SENTENCE = (
    "The original NCEI linear and curved fits each retained 8/15 "
    "conditional predictive-check misses."
)
CORRECTION_FOLDER = "artifacts/models/arrival-timing/exploration-sensitivity-qualification-v1"
CORRECTION_SCRIPT = "scripts/correct_arrival_sensitivity_qualifications.py"
CORRECTION_TEST = "tests/test_correct_arrival_sensitivity_qualifications.py"
REPORT_FILES = {name + ".csv" for name in TABLES} | {
    "findings.md",
    "summary.json",
    "inputs.json",
    "reference-provenance.json",
    "probe-dispositions.json",
    "prior-population-median-curves.png",
    "prior-population-median-curves.svg",
    "ncei-data-stress-log-changes.png",
    "ncei-data-stress-log-changes.svg",
    "output-checksums.json",
}


def base_ppc_counts(table):
    result = {}
    for kind in ["distance-scale", "mean-curvature"]:
        result[kind] = {}
        for scale in ["modeled-response", "native-minutes"]:
            selected = [
                r
                for r in table
                if r["target"] == "NCEI-native-duration"
                and r["kind"] == kind
                and r["role"] == "base"
                and r["scale"] == scale
            ]
            require(len(selected) == 15, "each NCEI base scale must retain15 quantile checks")
            misses = sum(
                not Decimal(r["replicated_q05"])
                <= Decimal(r["observed"])
                <= Decimal(r["replicated_q95"])
                for r in selected
            )
            result[kind][scale] = dict(misses=misses, checks=len(selected))
    return result


def corrected_qualification(counts):
    def n(kind, scale):
        return counts[kind][scale]["misses"]

    return (
        "In the current NCEI base-report views, observed quantiles fall outside the conditional "
        f"replicated 90% interval in {n('distance-scale', 'modeled-response')}/15 modeled-response "
        f"and {n('distance-scale', 'native-minutes')}/15 native checks for the linear form, "
        f"and {n('mean-curvature', 'modeled-response')}/15 modeled-response and "
        f"{n('mean-curvature', 'native-minutes')}/15 native checks for the curved form. "
        "These overlapping in-sample checks do not rank held-out performance."
    )


def closed_report(output):
    require(output.resolve() == output, "literal report path required")
    require(
        {p.name for p in output.iterdir()} == REPORT_FILES, "exact14 payloads+manifest required"
    )
    hashes = {}
    for name in REPORT_FILES:
        path = output / name
        require(
            path.resolve() == path and path.is_file(), "regular nonsymlink report artifact required"
        )
        hashes[name] = sha(path)
    manifest = read(output / "output-checksums.json")
    require(
        manifest == {k: v for k, v in hashes.items() if k != "output-checksums.json"},
        "closed output manifest differs from actual bytes",
    )
    return hashes


def correction_proof(root, output, receipt_path, expected_original_manifest, old_qualifications):
    require(
        receipt_path == root / CORRECTION_FOLDER / "receipt.json"
        and receipt_path.resolve() == receipt_path,
        "literal standalone correction receipt required",
    )
    value = read(receipt_path)
    actual = closed_report(output)
    relative = str(output.relative_to(root))
    require(
        value["schema_version"] == 1
        and value["status"] == "corrected_sensitivity_predictive_check_qualification"
        and value["report_path"] == relative
        and value["confirmation_outcomes_parsed"] is False
        and value["reserved_outcomes"] == "sealed",
        "explicit correction status/path/exposure required",
    )
    before, after = value["before_files"], value["after_files"]
    require(
        set(before) == set(after) == REPORT_FILES
        and after == actual
        and value["original_manifest_sha256"]
        == expected_original_manifest
        == before["output-checksums.json"],
        "correction must bind reviewed oldmanifest and current15files",
    )
    changed = {"findings.md", "summary.json", "output-checksums.json"}
    require(
        set(value["changed_files"]) == changed
        and len(value["changed_files"]) == 3
        and {n for n in REPORT_FILES if before[n] != after[n]} == changed,
        "only findings+one summaryqualification+manifest may change",
    )
    expected_snapshots = {
        name: CORRECTION_FOLDER + "/" + leaf
        for name, leaf in {
            "findings.md": "original-findings.md",
            "summary.json": "original-summary.json",
            "output-checksums.json": "original-output-checksums.json",
        }.items()
    }
    require(
        set(value["snapshots"]) == set(expected_snapshots), "exact original3 snapshots required"
    )
    require(
        {p.name for p in receipt_path.parent.iterdir()}
        == {"receipt.json", *[Path(p).name for p in expected_snapshots.values()]},
        "closed correction evidence inventory required",
    )
    originals, pins = {}, {}
    for name, path in expected_snapshots.items():
        snapshot = value["snapshots"][name]
        file = root / path
        require(
            snapshot["path"] == path
            and file.resolve() == file
            and file.is_file()
            and snapshot["sha256"] == before[name] == sha(file),
            "byte-exact original snapshot required",
        )
        originals[name] = file.read_bytes()
        pins[path] = snapshot["sha256"]
    require(
        json.loads(originals["output-checksums.json"])
        == {k: v for k, v in before.items() if k != "output-checksums.json"},
        "original manifest snapshot must close all14 originalpayloads",
    )
    source = {CORRECTION_SCRIPT, CORRECTION_TEST, relative + "/conditional-predictive-checks.csv"}
    require(source <= set(value["source_files"]), "tool/test/actualPPC source pins required")
    for name, digest in value["source_files"].items():
        path = root / name
        require(
            not Path(name).is_absolute()
            and ".." not in Path(name).parts
            and path.resolve() == path
            and path.is_file()
            and sha(path) == digest,
            "correction source SHA/path changed",
        )
        pins[name] = digest
    counts = base_ppc_counts(rows(output / "conditional-predictive-checks.csv"))
    replacement = corrected_qualification(counts)
    require(
        value["base_counts"] == counts
        and value["replacement"]
        == {"old_sentence": OLD_QUALIFICATION_SENTENCE, "new_text": replacement},
        "correction must state independently recomputed current in-sample counts",
    )
    old, new = OLD_QUALIFICATION_SENTENCE.encode(), replacement.encode()
    for name in ["findings.md", "summary.json"]:
        require(
            originals[name].count(old) == 1
            and (output / name).read_bytes() == originals[name].replace(old, new, 1),
            "exactly one sentence replacement; all other bytes immutable",
        )
    require(
        json.loads(originals["summary.json"])["qualifications"] == list(old_qualifications),
        "original qualifications must match immutable source",
    )
    qualifications = [
        q.replace(OLD_QUALIFICATION_SENTENCE, replacement) for q in old_qualifications
    ]
    require(
        read(output / "summary.json")["qualifications"] == qualifications,
        "only corrected qualification may differ",
    )
    pins[str(receipt_path.relative_to(root))] = sha(receipt_path)
    return dict(
        receipt=str(receipt_path),
        receipt_sha256=sha(receipt_path),
        source_files=pins,
        original_manifest_sha256=expected_original_manifest,
        after_files=after,
        base_counts=counts,
        new_text=replacement,
        qualifications=qualifications,
    )


def run(root, output, correction_receipt=None, original_manifest=None):
    sys.path.insert(0, str(root))
    from PIL import Image

    from analysis.arrival import model_sensitivity_completion_report as report

    checked = report.verify_report_sources(root)  # Complete seven-review hash closure first.
    source_pins = checked["files"]
    run = checked["run_summary"]
    counts = program_contract(checked, source_pins, report)
    scientific_reviews = science_parents(root, source_pins, report, run)
    valid, expected_views = counts["accepted_logical_fits"], counts["accepted_logical_fits"] + 14
    unresolved_orders = [u["order"] for u in run["unresolved_cases"]]
    require(
        output.resolve() == output and output.is_relative_to(root),
        "literal project-local report required",
    )
    manifest = read(output / "output-checksums.json")
    expected = {name + ".csv" for name in TABLES} | {
        "findings.md",
        "summary.json",
        "inputs.json",
        "reference-provenance.json",
        "probe-dispositions.json",
        "prior-population-median-curves.png",
        "prior-population-median-curves.svg",
        "ncei-data-stress-log-changes.png",
        "ncei-data-stress-log-changes.svg",
    }
    require(
        set(manifest) == expected
        and {p.name for p in output.iterdir()} == expected | {"output-checksums.json"},
        "exact closed report inventory required",
    )
    for name, digest in manifest.items():
        require(
            (output / name).resolve() == output / name and sha(output / name) == digest,
            "report artifact checksum mismatch",
        )
    before = {name: sha(output / name) for name in [*expected, "output-checksums.json"]}
    correction = (
        correction_proof(
            root, output, correction_receipt, original_manifest, report.old.QUALIFICATIONS
        )
        if correction_receipt
        else None
    )
    qualifications = correction["qualifications"] if correction else list(report.old.QUALIFICATIONS)
    summary, inputs = read(output / "summary.json"), read(output / "inputs.json")
    require(
        inputs["files"] == source_pins
        and inputs["schema_version"] == summary["schema_version"] == 4
        and inputs["reference_summary"]
        == {"seed_base": 2916110800, "seed_stride": 1000, "draws": 800},
        "exact report source/seed metadata required",
    )
    require(
        summary["views"] == expected_views
        and summary["selection"] == "none"
        and summary["qualifications"] == qualifications,
        "branch-specific unselected views and unchanged limitations required",
    )
    require(
        summary["confirmation_outcomes_parsed"] is False
        and summary["reserved_outcomes"] == "sealed"
        and summary["report_proof_contract"] == report.REPORT_PROOF_CONTRACT,
        "exposure/proof contract changed",
    )
    require(
        all(summary[k] == v for k, v in counts.items()),
        "program call/probe counts differ",
    )
    dispositions = read(output / "probe-dispositions.json")
    probes = dispositions["probes"]
    require(
        [p["order"] for p in probes] == list(range(55))
        and len({p["case_id"] for p in probes}) == 55,
        "all55 unique planned dispositions required",
    )
    require(
        summary["probe_dispositions"] == probes
        and dispositions["unresolved_cases"] == run["unresolved_cases"],
        "disposition source differs",
    )
    missing = [p for p in probes if p["status"] == "computationally_unresolved"]
    require(
        [p["order"] for p in missing] == unresolved_orders
        and all(
            p["posterior"] is None
            and len(p["failed_attempt_receipts"]) == 2
            and p["no_third_attempt"] is True
            for p in missing
        ),
        "unresolved slots must never acquire posterior/zero fill",
    )
    require(
        summary["successful_numerical_repair_mapping"] == run["successful_numerical_repair_mapping"]
        and inputs["successful_numerical_repair_mapping"]
        == run["successful_numerical_repair_mapping"]
        and summary["case47_outcome"] == inputs["case47_outcome"] == run["case47_outcome"]
        and summary["unresolved_cases"] == run["unresolved_cases"]
        and summary["protocol_amendment"]
        == inputs["protocol_amendment"]
        == run["protocol_amendment"],
        "saved report must retain exact typed branch/protocol/repair mapping",
    )
    views = []
    for entry in checked["accepted"]:
        job = entry["original_job"]
        folder, raw = source_case_paths(root, entry, report)
        require(
            (folder, raw) == report.producer_paths(root, entry, checked["numerical_admission"])
            and entry["posterior"] == str(raw.relative_to(root))
            and entry["posterior_sha256"] == source_pins[str(raw.relative_to(root))],
            "saved body must come from the literal accepted producer; no failed substitution",
        )
        saved = report.old._read(
            root, source_pins, str((folder / "summary.json").relative_to(root))
        )
        recorded = report.old._read(
            root, source_pins, str((folder / "inputs.json").relative_to(root))
        )
        views.append(
            dict(
                view_id=job["id"],
                target=job["target"],
                kind=job["kind"],
                role="sensitivity",
                scenario=job["scenario"],
                prior_variant=job["prior_variant"],
                distance_mode=job["distance_mode"],
                training_record_ids=job["training_record_ids"],
                omitted_record_ids=job["omitted_record_ids"],
                excluded_record_ids=job["excluded_record_ids"],
                summary=saved,
                prior_specification=report.old._priors(
                    root, job["target"], job["kind"], job["prior_variant"], recorded
                ),
            )
        )
    # Fixed references only: no accepted or failed sensitivity posterior is opened/replayed.
    descriptors = report.old.refs.descriptors()
    blocked = {f["posterior"] for f in [*run["retained_failures"], *run["accepted"]]}
    require(
        len(descriptors) == 14 and all(d["raw"] not in blocked for d in descriptors),
        "reference-only raw allowlist",
    )
    lanes, contract = report.old.load_lanes(root)
    require(
        contract == checked["admission"]["contract"], "same exploration-only reference contract"
    )
    provenance = read(output / "reference-provenance.json")["references"]
    require(len(provenance) == 14, "all14 reference provenance records required")
    seeds, reference_opens = [], []
    for i, descriptor in enumerate(descriptors):
        seed = 2916110800 + 1000 * i
        seeds.append(seed)
        with reference_only_nc(report.old.refs, root, [d["raw"] for d in descriptors]) as opened:
            lane, kind, indices, posterior, proof = report.old.refs.load_reference(
                root, descriptor["key"], lanes, source_pins
            )
        reference_opens.extend(opened)
        saved = report.old.summarize_posterior(
            lane, kind, posterior, indices=indices, seed=seed, draws=800
        )
        chosen = set(saved["membership"])
        original = lanes[lane.target]
        view = dict(
            view_id=descriptor["key"],
            target=lane.target,
            kind=kind,
            role=descriptor["role"],
            scenario=descriptor["role"],
            prior_variant="base",
            distance_mode=descriptor["distance_mode"],
            training_record_ids=saved["membership"],
            omitted_record_ids=[
                rid
                for rid, keep in zip(original.record_ids, original.included, strict=True)
                if keep and rid not in chosen
            ],
            excluded_record_ids=[
                rid
                for rid, keep in zip(original.record_ids, original.included, strict=True)
                if not keep
            ],
            summary=saved,
            prior_specification=report.old._priors(root, lane.target, kind, "base"),
        )
        require(
            provenance[i]["summary_seed"] == seed
            and provenance[i]["summary_draws"] == 800
            and provenance[i]["descriptor_order"] == i,
            "reference seed/order budget differs",
        )
        require(
            all(provenance[i].get(k) == v for k, v in proof.items()),
            "literal historical source provenance differs",
        )
        views.append(view)
    require(
        set(reference_opens) == {d["raw"] for d in descriptors},
        "exactly the14 distinct reference NC files must supply reference summaries",
    )
    require(
        Counter(v["role"] for v in views)["sensitivity"] == valid and len(views) == expected_views,
        "branch-specific valid+14 source reconstruction required",
    )
    tables = {name: rows(output / (name + ".csv")) for name in TABLES}
    require(
        all(
            row["view_id"] not in {checked["jobs"][n]["id"] for n in unresolved_orders}
            for values in tables.values()
            for row in values
        ),
        "failed/unresolved posterior table row",
    )
    numeric = check_cells(views, tables, expected_views)
    require(summary["table_rows"] == numeric["table_rows"], "saved row-count summary differs")
    text = (output / "findings.md").read_text()
    require(
        report.unresolved_note(run) in text
        and text.index(report.unresolved_note(run)) < text.index("## What the tables show"),
        "gap qualification must be prominent",
    )
    require(
        report.method_note(run) in text
        and "cannot establish robustness" in text
        and "favor curvature" in text,
        "unresolved gap must not favor curvature",
    )
    require(all(q in text for q in qualifications), "scientific limitation missing")
    require(
        summary["unresolved_comparison"] == report.unresolved_note(run)
        and summary["numerical_repair_method"] == report.method_note(run)
        and f"{valid} usable sensitivity fits" in text
        and f"{counts['unresolved_case_count']} computationally unresolved case(s)" in text
        and "58 sampler calls" in text
        and f"{counts['retained_failed_calls']} retained failures" in text
        and f"{expected_views} usable report views" in text
        and "4,000 tuning steps and target_accept=0.999" in text
        and "2,000 tuning steps and target_accept=0.99" in text,
        "independent branch-specific narrative count/protocol qualification differs",
    )
    if 47 in unresolved_orders:
        require(
            "Neither mean form has a usable posterior" in text and "favor either mean form" in text,
            "both missing stress checks must be disclosed",
        )
    require(
        f"There are {numeric['ppc_outside_cells']} observed" in text
        and f"among {len(tables[TABLES[3]])} checks" in text,
        "PPC narrative count differs",
    )
    ranges = []
    for target, kind in report.old.FORMS:
        for prior in (True, False):
            selected = [
                r
                for r in tables[TABLES[2]]
                if r["target"] == target
                and r["kind"] == kind
                and r["role"] != "base"
                and r["common_supported"] == "True"
                and (r["scenario"] == "prior") == prior
            ]
            if not selected:
                continue
            key = "signed_median_shift_minutes" if target == "T-CAL" else "median_log_shift"
            values = [Decimal(r[key]) for r in selected]
            low, high = float(min(values)), float(max(values))
            units = "minutes" if target == "T-CAL" else "log units"
            label = "Prior assumptions" if prior else "Data stresses and sequence deletions"
            require(
                f"| {target} | {kind} | {label} | {len(selected)} | "
                f"{low:.4g} to {high:.4g} {units} |" in text,
                "independent descriptive range differs",
            )
            ranges.append(
                dict(
                    target=target,
                    kind=kind,
                    group=label,
                    cells=len(values),
                    minimum=low,
                    maximum=high,
                    units=units,
                )
            )
    images = []
    for name in ("prior-population-median-curves", "ncei-data-stress-log-changes"):
        with Image.open(output / (name + ".png")) as image:
            image.verify()
        with Image.open(output / (name + ".png")) as image:
            require(
                image.width >= 1500 and image.height >= 1000, "unexpected low-resolution figure"
            )
            images.append(
                dict(
                    path=str(output / (name + ".png")),
                    width=image.width,
                    height=image.height,
                    sha256=before[name + ".png"],
                )
            )
    require(
        "Unresolved" in (output / "ncei-data-stress-log-changes.svg").read_text(),
        "missing hatched unresolved figure label",
    )
    final_checked = report.verify_report_sources(root)
    require(
        final_checked["files"] == source_pins and final_checked["run_summary"] == run,
        "scientific source closure or branch drifted during checker",
    )
    report.old._unchanged(root, source_pins)
    require(
        all(sha(output / name) == value for name, value in before.items()),
        "report bytes drifted during checker",
    )
    return dict(
        status="independent_saved_cell_checks_passed_pending_visual_review",
        report=str(output),
        report_checksums_sha256=before["output-checksums.json"],
        source_gate_sha256=source_pins[report.GATE],
        execution_authority_gate_sha256=source_pins[report.EXECUTION_GATE],
        numerical_worker_spec_gate_sha256=source_pins[report.NUMERICAL_GATE],
        case47_outcome=run["case47_outcome"],
        scientific_reviews=scientific_reviews,
        counts=counts,
        views=expected_views,
        source_saved_summaries=valid,
        accepted_case_NC_replays=0,
        failed_NC_reads=0,
        reference_NC_allowlist=[d["raw"] for d in descriptors],
        reference_NC_unique_files=len(set(reference_opens)),
        reference_NC_group_opens=len(reference_opens),
        reference_summary_seeds=seeds,
        reference_summary_draws=800,
        numeric_checks=numeric,
        qualification_correction=correction,
        descriptive_ranges=ranges,
        figure_files=images,
        visual_review_required=True,
        visual_checklist=VISUAL_CHECKLIST,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        new_sampler_calls=0,
    )


def recheck_corrected(root, output, receipt_path, baseline_path, baseline_sha):
    """Reuse accepted numerical evidence only for byte-identical mathematical artifacts."""
    require(
        baseline_sha
        and baseline_path.resolve() == baseline_path
        and sha(baseline_path) == baseline_sha,
        "exact Root-approved original numeric receipt required",
    )
    baseline = read(baseline_path)
    require(
        baseline["status"] == "independent_saved_cell_checks_passed_pending_visual_review"
        and baseline["report"] == str(output)
        and baseline["accepted_case_NC_replays"] == 0
        and baseline["failed_NC_reads"] == 0
        and baseline["reference_NC_unique_files"] == 14,
        "original complete independent numeric proof required; no unproved reuse",
    )
    sys.path.insert(0, str(root))
    from analysis.arrival import model_sensitivity_completion_report as report

    checked = report.verify_report_sources(root)
    pins, run = checked["files"], checked["run_summary"]
    counts = program_contract(checked, pins, report)
    reviews = science_parents(root, pins, report, run)
    require(
        baseline["source_gate_sha256"] == pins[report.GATE]
        and baseline["execution_authority_gate_sha256"] == pins[report.EXECUTION_GATE]
        and baseline["numerical_worker_spec_gate_sha256"] == pins[report.NUMERICAL_GATE]
        and baseline["counts"] == counts
        and baseline["scientific_reviews"] == reviews,
        "numerical-source or scientific-review migration forbids evidence reuse",
    )
    correction = correction_proof(
        root, output, receipt_path, baseline["report_checksums_sha256"], report.old.QUALIFICATIONS
    )
    before = closed_report(output)
    summary, inputs = read(output / "summary.json"), read(output / "inputs.json")
    require(
        inputs["files"] == pins
        and inputs["reference_summary"]
        == {"seed_base": 2916110800, "seed_stride": 1000, "draws": 800}
        and summary["schema_version"] == 4
        and summary["selection"] == "none"
        and summary["views"] == baseline["views"] == counts["accepted_logical_fits"] + 14
        and all(type(summary[k]) is int and summary[k] == v for k, v in counts.items())
        and summary["confirmation_outcomes_parsed"] is False
        and summary["reserved_outcomes"] == "sealed",
        "corrected reader must preserve all scientific/exposure/accounting identities",
    )
    tables = {name: rows(output / (name + ".csv")) for name in TABLES}
    numeric = baseline["numeric_checks"]
    require(
        summary["table_rows"] == numeric["table_rows"] == {k: len(v) for k, v in tables.items()}
        and numeric["csv_cells"] == sum(len(row) for values in tables.values() for row in values),
        "prior fully checked cell inventory must be byte-identical",
    )
    ppc_misses = sum(
        not Decimal(r["replicated_q05"]) <= Decimal(r["observed"]) <= Decimal(r["replicated_q95"])
        for r in tables[TABLES[3]]
    )
    require(ppc_misses == numeric["ppc_outside_cells"], "independent aggregatePPC count differs")
    text = (output / "findings.md").read_text()
    require(
        all(q in text for q in correction["qualifications"])
        and OLD_QUALIFICATION_SENTENCE not in text
        and report.unresolved_note(run) in text
        and text.index(report.unresolved_note(run)) < text.index("## What the tables show")
        and report.method_note(run) in text,
        "all corrected and unchanged qualifications required",
    )
    require(
        f"{counts['accepted_logical_fits']} usable fits and 14 historical posterior views" in text
        and f"{ppc_misses} observed" in text
        and f"among {len(tables[TABLES[3]])} checks" in text
        and f"{len(tables[TABLES[1]])} supported typed intervals" in text
        and (
            f"{sum(r['common_supported'] == 'True' for r in tables[TABLES[2]])} "
            f"of {len(tables[TABLES[2]])} change cells"
        )
        in text,
        "every changed/current descriptive count must match current saved tables",
    )
    ranges = []
    for target, kind in report.old.FORMS:
        for prior in [True, False]:
            chosen = [
                r
                for r in tables[TABLES[2]]
                if r["target"] == target
                and r["kind"] == kind
                and r["role"] != "base"
                and r["common_supported"] == "True"
                and (r["scenario"] == "prior") == prior
            ]
            if not chosen:
                continue
            key = "signed_median_shift_minutes" if target == "T-CAL" else "median_log_shift"
            values = [Decimal(r[key]) for r in chosen]
            low, high = float(min(values)), float(max(values))
            units = "minutes" if target == "T-CAL" else "log units"
            group = "Prior assumptions" if prior else "Data stresses and sequence deletions"
            require(
                f"| {target} | {kind} | {group} | {len(chosen)} | {low:.4g} to {high:.4g} {units} |"
                in text,
                "independent corrected-reader range differs",
            )
            ranges.append(
                dict(
                    target=target,
                    kind=kind,
                    group=group,
                    cells=len(values),
                    minimum=low,
                    maximum=high,
                    units=units,
                )
            )
    require(
        ranges == baseline["descriptive_ranges"],
        "descriptive numerical ranges must remain unchanged",
    )
    dispositions = read(output / "probe-dispositions.json")
    require(
        dispositions["probes"] == summary["probe_dispositions"]
        and dispositions["unresolved_cases"] == run["unresolved_cases"]
        and [p["order"] for p in dispositions["probes"]] == list(range(55)),
        "all55 reviewed probe dispositions retained",
    )
    for picture in baseline["figure_files"]:
        require(
            sha(Path(picture["path"])) == picture["sha256"],
            "visual evidence reuse requires identical PNGs",
        )
    final = report.verify_report_sources(root)
    require(
        final["files"] == pins
        and final["run_summary"] == run
        and closed_report(output) == before
        and sha(baseline_path) == baseline_sha,
        "source/report/baselineproof drift during correctedQC",
    )
    report.old._unchanged(root, correction["source_files"])
    result = {
        **baseline,
        "status": "independent_corrected_reader_checks_passed_pending_visual_review",
        "report_checksums_sha256": before["output-checksums.json"],
        "qualification_correction": correction,
        "numeric_evidence_reused": True,
        "original_numeric_receipt": str(baseline_path),
        "original_numeric_receipt_sha256": baseline_sha,
        "original_numeric_checker_sha256": (
            "d48da6ff2a9431cd0d9b8764769b3838db0c05af3b17101248f111817dff1bc9"
        ),
        "original_reference_NC_unique_files": baseline["reference_NC_unique_files"],
        "original_reference_NC_group_opens": baseline["reference_NC_group_opens"],
        "reference_NC_unique_files": 0,
        "reference_NC_group_opens": 0,
        "new_reference_NC_reads": 0,
        "unchanged_mathematical_artifacts_reused": sorted(
            REPORT_FILES - {"findings.md", "summary.json", "output-checksums.json"}
        ),
        "base_PPC_counts_independently_recomputed": correction["base_counts"],
        "visual_review_required": True,
        "figure_bytes_identical_to_original_review": True,
    }
    return result


def correction_self_test(root):
    import copy
    from tempfile import TemporaryDirectory

    sys.path.insert(0, str(root))
    from analysis.arrival import model_sensitivity_completion_report as report

    with TemporaryDirectory(prefix="tsunami-correction-checker-", dir="/private/tmp") as temp:
        fake = Path(temp)
        output = fake / "artifacts/models/arrival-timing/exploration-sensitivity-report-v1"
        output.mkdir(parents=True)
        for name in REPORT_FILES - {"output-checksums.json"}:
            (output / name).write_text("unchanged synthetic artifact")
        (output / "findings.md").write_text("\n\n".join(report.old.QUALIFICATIONS))
        (output / "summary.json").write_text(
            json.dumps(
                {
                    "qualifications": list(report.old.QUALIFICATIONS),
                    "scientific_values_unchanged": [0.1, -4.2],
                }
            )
        )
        ppc = []
        for kind, misses in [("distance-scale", [11, 10]), ("mean-curvature", [8, 9])]:
            for scale, n in zip(["modeled-response", "native-minutes"], misses, strict=True):
                for i in range(15):
                    ppc.append(
                        dict(
                            target="NCEI-native-duration",
                            kind=kind,
                            role="base",
                            scale=scale,
                            observed=2 if i < n else 0,
                            replicated_q05=-1,
                            replicated_q95=1,
                        )
                    )
        with (output / "conditional-predictive-checks.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(ppc[0]))
            writer.writeheader()
            writer.writerows(ppc)

        def seal():
            manifest = {n: sha(output / n) for n in REPORT_FILES - {"output-checksums.json"}}
            (output / "output-checksums.json").write_text(json.dumps(manifest, sort_keys=True))
            return closed_report(output)

        before = seal()
        sibling = fake / CORRECTION_FOLDER
        sibling.mkdir()
        snapshots = {}
        for name, leaf in {
            "findings.md": "original-findings.md",
            "summary.json": "original-summary.json",
            "output-checksums.json": "original-output-checksums.json",
        }.items():
            path = sibling / leaf
            path.write_bytes((output / name).read_bytes())
            snapshots[name] = dict(path=str(path.relative_to(fake)), sha256=sha(path))
        counts = base_ppc_counts(rows(output / "conditional-predictive-checks.csv"))
        new = corrected_qualification(counts)
        for name in ["findings.md", "summary.json"]:
            path = output / name
            path.write_bytes(
                path.read_bytes().replace(OLD_QUALIFICATION_SENTENCE.encode(), new.encode(), 1)
            )
        after = seal()
        source = {}
        for name in [CORRECTION_SCRIPT, CORRECTION_TEST]:
            path = fake / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic tested source")
            source[name] = sha(path)
        source[str((output / "conditional-predictive-checks.csv").relative_to(fake))] = sha(
            output / "conditional-predictive-checks.csv"
        )
        value: dict[str, Any] = dict(
            schema_version=1,
            status="corrected_sensitivity_predictive_check_qualification",
            report_path=str(output.relative_to(fake)),
            source_files=source,
            before_files=before,
            after_files=after,
            original_manifest_sha256=before["output-checksums.json"],
            snapshots=snapshots,
            replacement=dict(old_sentence=OLD_QUALIFICATION_SENTENCE, new_text=new),
            base_counts=counts,
            changed_files=["findings.md", "summary.json", "output-checksums.json"],
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
        )
        receipt = sibling / "receipt.json"
        receipt.write_text(json.dumps(value))
        correction_proof(
            fake, output, receipt, before["output-checksums.json"], report.old.QUALIFICATIONS
        )
        for mutation in [
            "count",
            "replacement",
            "source",
            "before",
            "snapshot",
            "changed",
            "after",
        ]:
            bad = copy.deepcopy(value)
            if mutation == "count":
                bad["base_counts"]["distance-scale"]["native-minutes"]["misses"] -= 1
            elif mutation == "replacement":
                bad["replacement"]["new_text"] += " Curvature wins."
            elif mutation == "source":
                bad["source_files"][CORRECTION_TEST] = "0" * 64
            elif mutation == "before":
                bad["original_manifest_sha256"] = "0" * 64
            elif mutation == "snapshot":
                bad["snapshots"]["summary.json"]["path"] = "foreign.json"
            elif mutation == "changed":
                bad["changed_files"].append("inputs.json")
            else:
                bad["after_files"]["inputs.json"] = "0" * 64
            receipt.write_text(json.dumps(bad))
            try:
                correction_proof(
                    fake,
                    output,
                    receipt,
                    before["output-checksums.json"],
                    report.old.QUALIFICATIONS,
                )
            except (ValueError, KeyError):
                pass
            else:
                raise AssertionError("bad correction accepted: " + mutation)
        receipt.write_text(json.dumps(value))
        return dict(valid_byte_exact_correction=True, negative_checks=7, actual_report_read=False)


def self_test(root):
    """Only synthetic producer metadata and pure saved tables; no actual body/NC reads."""
    import copy
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace

    sys.path.insert(0, str(root))
    from pytest import MonkeyPatch

    from analysis.arrival import model_sensitivity_completion_report as report
    from tests.test_arrival_model_sensitivity_completion_report import fixture
    from tests.test_arrival_model_sensitivity_report import views as synthetic_views

    require(
        change({"log_q50": 2.0}, {"log_q50": 1.0}, True, True) == (1.0, math.e, True),
        "Decimal ratio oracle",
    )
    require(
        change({"q50": -8.0}, {"q50": -3.0}, False, True) == (-5.0, None, None),
        "signed shift oracle",
    )
    require(change({}, {}, True, False) == (None, None, None), "unsupported blank oracle")
    require(equal("", None) and not equal("0", None), "blank is not zero")
    results, negatives = [], 0
    for exhausted in [False, True]:
        with TemporaryDirectory(prefix="tsunami-schema4-checker-", dir="/private/tmp") as temp:
            fake_root = Path(temp)
            with MonkeyPatch.context() as monkeypatch:
                fixture(fake_root, monkeypatch, exhausted47=exhausted)
                checked = report.verify_report_sources(fake_root)
                # The reduced source fixture omits public receipt identities.
                by_order = {e["order"]: e for e in checked["accepted"]}
                for order in [34, *([] if exhausted else [47])]:
                    e = by_order[order]
                    checked["run_summary"]["successful_numerical_repair_mapping"][
                        e["case_id"]
                    ].update({k: e[k] for k in ["receipt", "receipt_sha256"]})
                counts = program_contract(checked, checked["files"], report)
                science_parents(fake_root, checked["files"], report, checked["run_summary"])
                body_reads = []
                original_read = report.old._read

                def no_scientific_body(
                    root, pins, name, body_reads=body_reads, original_read=original_read
                ):
                    if "/jobs/" in name and name.endswith("/summary.json"):
                        body_reads.append(name)
                        raise AssertionError("scientific body read before rejected source")
                    return original_read(root, pins, name)

                monkeypatch.setattr(report.old, "_read", no_scientific_body)
                source = fake_root / report.CONSUMED[0]
                source_bytes = source.read_bytes()
                source.write_bytes(b"changed synthetic source")
                try:
                    try:
                        report.verify_report_sources(fake_root)
                    except ValueError:
                        negatives += 1
                    else:
                        raise AssertionError("source drift admitted")
                    require(not body_reads, "metadata rejection must precede saved bodies")
                finally:
                    source.write_bytes(source_bytes)
                    monkeypatch.setattr(report.old, "_read", original_read)
                native_calls = []

                def original_open(path, *args, native_calls=native_calls, **kwargs):
                    native_calls.append(str(path))

                fake_refs = SimpleNamespace(xr=SimpleNamespace(open_dataset=original_open))
                with reference_only_nc(fake_refs, fake_root, ["reference.nc"]) as opened:
                    fake_refs.xr.open_dataset(fake_root / "reference.nc")
                    for forbidden in ["accepted.nc", "failed.nc"]:
                        try:
                            fake_refs.xr.open_dataset(fake_root / forbidden)
                        except ValueError:
                            negatives += 1
                        else:
                            raise AssertionError("non-reference NC allowed")
                    require(
                        opened == ["reference.nc"] and len(native_calls) == 1,
                        "reference guard must reject before native reader",
                    )
                require(fake_refs.xr.open_dataset is original_open, "reader guard must restore API")
                for mutation in [
                    "calls",
                    "usable",
                    "failure",
                    "mapping",
                    "protocol",
                    "spec",
                    "gap",
                    "theta",
                ]:
                    bad = copy.deepcopy(checked)
                    run = bad["run_summary"]
                    if mutation == "calls":
                        run["actual_sampler_calls"] -= 1
                    elif mutation == "usable":
                        run["accepted_logical_fits"] -= 1
                    elif mutation == "failure":
                        run["retained_failures"].pop()
                    elif mutation == "mapping":
                        run["successful_numerical_repair_mapping"]["foreign"] = {}
                    elif mutation == "protocol":
                        run["repair_job"]["sampler"]["tune"] = 2000
                    elif mutation == "spec":
                        run["accepted"][-1]["worker_spec_gate"] = report.EXECUTION_GATE
                    elif mutation == "gap":
                        run["unresolved_cases"][0]["order"] = 35
                    else:
                        run["unresolved_cases"][0]["posterior"] = "foreign.nc"
                    try:
                        program_contract(bad, bad["files"], report)
                    except (ValueError, KeyError):
                        negatives += 1
                    else:
                        raise AssertionError("synthetic schema corruption accepted: " + mutation)
                full = synthetic_views()
                sensitivity = [v for v in full if v["role"] == "sensitivity"]
                missing = [36, 47] if exhausted else [36]
                excluded = {sensitivity[n]["view_id"] for n in missing}
                selected = [v for v in full if v["view_id"] not in excluded]
                native_tables = report.sensitivity_tables(selected, tuple(missing))
                for name, table in native_tables.items():
                    report.old.write_table(fake_root / (name + ".csv"), table)
                tables = {name: rows(fake_root / (name + ".csv")) for name in TABLES}
                numeric = check_cells(selected, tables, counts["accepted_logical_fits"] + 14)
                for mutation in ["quantile", "ppc", "unresolved-zero", "cohort", "extra-cell"]:
                    bad = copy.deepcopy(tables)
                    if mutation == "quantile":
                        bad[TABLES[1]][0]["q50"] = str(float(bad[TABLES[1]][0]["q50"]) + 1)
                    elif mutation == "ppc":
                        cell = bad[TABLES[3]][0]
                        cell["observed_outside_replicated_90"] = str(
                            cell["observed_outside_replicated_90"] != "True"
                        )
                    elif mutation == "cohort":
                        bad[TABLES[4]][0]["training_record_ids"] = "[]"
                    elif mutation == "extra-cell":
                        bad[TABLES[0]][0]["foreign-column"] = "0"
                    else:
                        bad[TABLES[1]][0]["view_id"] = sensitivity[36]["view_id"]
                    try:
                        check_cells(selected, bad, len(selected))
                    except (ValueError, KeyError):
                        negatives += 1
                    else:
                        raise AssertionError(
                            "synthetic scientific cell corruption accepted: " + mutation
                        )
                results.append(
                    dict(
                        case47_outcome=checked["run_summary"]["case47_outcome"],
                        counts=counts,
                        views=len(selected),
                        table_rows=numeric["table_rows"],
                    )
                )
    correction_checks = correction_self_test(root)
    print(
        json.dumps(
            dict(
                status="checker_schema4_synthetic_self_tests_passed",
                correction_checks=correction_checks,
                branches=results,
                negative_checks=negatives,
                actual_report_read=False,
                NC_reads=0,
                production_collection=False,
            ),
            allow_nan=False,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--correction-receipt", type=Path)
    parser.add_argument("--original-manifest-sha256")
    parser.add_argument("--baseline-qc-receipt", type=Path)
    parser.add_argument("--baseline-qc-sha256")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.root.resolve())
        return
    parser.error(
        "--report and --receipt are required for explicit actual QC"
    ) if args.report is None or args.receipt is None else None
    if args.baseline_qc_receipt:
        result = recheck_corrected(
            args.root.resolve(),
            args.report.absolute(),
            args.correction_receipt,
            args.baseline_qc_receipt,
            args.baseline_qc_sha256,
        )
    else:
        result = run(
            args.root.resolve(),
            args.report.absolute(),
            args.correction_receipt,
            args.original_manifest_sha256,
        )
    require(
        args.receipt.parent.resolve() == Path("/private/tmp") and not args.receipt.exists(),
        "new /private/tmp receipt only",
    )
    with args.receipt.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "receipt": str(args.receipt),
                "visual_review_required": True,
            }
        )
    )


if __name__ == "__main__":
    main()
