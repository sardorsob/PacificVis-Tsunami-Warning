"""Closed 55-probe report with 54 usable fits, one unresolved case and 57 calls."""

# pyright: basic
from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from analysis.arrival import model_sensitivity_repair as repair
from analysis.arrival import model_sensitivity_report as old
from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_completion as first_completion

GATE = old.GATE
OUTPUT = "artifacts/models/arrival-timing/exploration-sensitivity-report-v1"
NUMERICAL_OUTPUT = old.fit.OUTPUT + "/numerical-protocol-v2"
CONTROL = old.fit.OUTPUT + "/remaining-sensitivities-v1"
COMPLETION_SUMMARY = CONTROL + "/run-summary.json"
NUMERICAL_GATE = str(Path(old.fit.GATE).parent) + "/numerical-protocol-v2/review-acceptance.json"
EXECUTION_GATE = (
    str(Path(old.fit.GATE).parent) + "/remaining-sensitivities-v1/review-acceptance.json"
)
REPORT_COUNTS = dict(
    planned_cases=55,
    completed_probes=55,
    accepted_logical_fits=54,
    unresolved_case_count=1,
    actual_sampler_calls=57,
    calls_charged=57,
    calls_started=57,
    retained_failed_calls=3,
    max_sampler_call_slots=110,
)
REFERENCE_SUMMARY, TABLES, QUALIFICATIONS = old.REFERENCE_SUMMARY, old.TABLES, old.QUALIFICATIONS
REPORT_PROOF_CONTRACT = {
    "accepted_cases": "independent_scientific_review_plus_fresh_complete_producer_bytes",
    "recompute_accepted_case_summaries": False,
    "recompute_historical_reference_summaries": True,
}
SCIENTIFIC_REVIEWS = {
    "first34": old.fit.OUTPUT + "/batch-034-review-acceptance.json",
    "repair_v1": first_completion.REPAIR_REVIEW,
    "baseline_v2": NUMERICAL_OUTPUT + "/baseline-review.json",
    "unresolved_case": CONTROL + "/disposition-review.json",
    "remaining": CONTROL + "/scientific-review.json",
}
SCIENCE_STATUSES = {
    "first34": "accepted_sensitivity_thirty_four_case_checkpoint",
    "repair_v1": "accepted_sensitivity_same_model_numerical_repair",
    "baseline_v2": "accepted_sensitivity_remaining_numerical_protocol_plan",
    "unresolved_case": "accepted_sensitivity_unresolved_case_disposition",
    "remaining": "accepted_remaining_sensitivity_computations",
}
CASE_FILES = (
    "job.json",
    "inputs.json",
    "membership.json",
    "sampling-start.json",
    "result.json",
    "diagnostics.json",
    "sampling-diagnostics.csv",
    "summary.json",
    "parameters.csv",
    "derived.csv",
    "curves.csv",
    "conditional-ppc.csv",
    "record-intervals.csv",
)
CONSUMED = tuple(
    sorted(
        set(old.CONSUMED)
        | set(repair.CONSUMED)
        | {
            first_completion.SELF,
            first_completion.TEST,
            "analysis/arrival/model_sensitivity_numerical_fit.py",
            "scripts/fit_arrival_sensitivity_numerical.py",
            "tests/test_arrival_model_sensitivity_numerical_fit.py",
            "scripts/run_arrival_sensitivity_numerical.py",
            "scripts/run_arrival_sensitivity_remaining.py",
            "tests/test_run_arrival_sensitivity_remaining.py",
            "tests/test_run_arrival_sensitivity_numerical.py",
            "analysis/arrival/model_sensitivity_completion_report.py",
            "scripts/summarize_arrival_completed_sensitivities.py",
            "tests/test_arrival_model_sensitivity_completion_report.py",
        }
    )
)
UNRESOLVED_NOTE = (
    "The NCEI linear 2014-onward sensitivity remains computationally unresolved after "
    "two failed attempts. Its original run had 30 divergences; the reviewed numerical "
    "attempt retained one divergence among 8,000 draws and failed the unchanged zero-divergence "
    "screen. No third attempt is authorized. Neither attempt supplies posterior parameters, "
    "curves or predictive checks. This leaves a gap in the linear-model stress checks: "
    "the available results cannot establish robustness for this comparison or be used to "
    "favor curvature. Its 150 original observations remain in the other applicable fits "
    "and full-data analyses; this disposition deletes no data."
)
METHOD_NOTE = (
    "All 55 planned probes have a recorded disposition: 54 usable sensitivity fits and "
    "one computationally unresolved case. They required 57 sampler calls, including three "
    "retained failures. The pre-2007 NCEI linear fit succeeded after its separately reviewed "
    "repair. Both attempts for the 2014-onward linear fit failed diagnostics. A reviewed "
    "common numerical protocol used four chains, 2,000 retained draws, 2,000 tuning draws "
    "and target_accept=0.99 for the unsuccessful second attempt and the first attempts of "
    "the remaining 18 prespecified cases; the first repair used the same settings. "
    "Original models, priors, masks, cohorts and seeds remain unchanged. These are not "
    "independent repeat experiments. Predictive summaries retain original seed + 1 and "
    "800 draws. The three failed outputs remain retained as diagnostic evidence and "
    "contribute no posterior draws to the 68 usable report views. Accepted-case summaries "
    "rely on independent scientific review and fresh complete producer bytes; the 14 "
    "historical reference summaries are recomputed. No native data were changed or imputed."
)


def numerical_api() -> Any:
    return importlib.import_module("analysis.arrival.model_sensitivity_numerical_fit")


def completion_api() -> Any:
    return importlib.import_module("scripts.run_arrival_sensitivity_remaining")


def producer_paths(root, entry, admission):
    producer, job = entry.get("producer"), entry["execution_job"]
    if producer == "original":
        return (
            root / old.fit.OUTPUT / "jobs" / job["id"],
            root / old.fit.STORE / (job["id"] + ".nc"),
        )
    if producer == "repair_v1":
        return repair.case_paths(root, job)
    if producer == "numerical_protocol":
        return numerical_api().case_paths(root, job, admission)
    raise ValueError("unknown sensitivity producer")


def physical_inventory(root, folder, raw):
    paths = [
        folder,
        *folder.rglob("*"),
        raw,
        *(folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]),
    ]
    actual = {}
    for path in paths:
        if path.resolve() != path or not path.exists():
            raise ValueError("literal complete producer paths required")
        if path.is_file():
            actual[str(path.relative_to(root))] = sha256(
                old._path(root, str(path.relative_to(root)))
            )
        elif path != folder:
            raise ValueError("unknown producer directory")
    return actual


def fresh_producer_bytes(root, accepted, failures, admission, pins):
    """Hash complete literal inventories, including raw bytes; never parse NetCDF."""
    for entry in accepted:
        folder, raw = producer_paths(root, entry, admission)
        required = {str((folder / n).relative_to(root)) for n in CASE_FILES}
        required |= {
            str(raw.relative_to(root)),
            *(
                str(folder.with_name(folder.name + s).relative_to(root))
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ),
        }
        if set(entry["files"]) != required:
            raise ValueError("complete exact accepted producer inventory required")
        expected = {**entry["files"], entry["receipt"]: entry["receipt_sha256"]}
        old._require(pins, expected)
        if physical_inventory(root, folder, raw) != expected:
            raise ValueError("accepted producer bytes or physical inventory changed")
        if old._read(root, pins, entry["receipt"]) != {
            "case_id": entry["case_id"],
            "files": entry["files"],
        }:
            raise ValueError("literal accepted attempt receipt required")
    for failure in failures:
        if failure.get("producer") == "numerical_protocol":
            folder, raw = numerical_api().case_paths(root, failure["execution_job"], admission)
        elif failure.get("producer") in {None, "original"}:
            folder = root / old.fit.OUTPUT / "jobs" / failure["case_id"]
            raw = root / old.fit.STORE / (failure["case_id"] + ".nc")
        else:
            raise ValueError("unknown failed producer")
        old._require(pins, failure["physical_files"])
        old._require(pins, failure["files"])
        if physical_inventory(root, folder, raw) != failure["physical_files"]:
            raise ValueError("retained failed producer bytes or inventory changed")


def verify_report_sources(root: Path) -> dict[str, Any]:
    """Admit science, the unresolved disposition and all bytes before scientific bodies."""
    root = root.resolve()
    gate = json.loads(old._path(root, GATE).read_text())
    required = set(CONSUMED) | {
        old.PLAN,
        old.fit.GATE,
        COMPLETION_SUMMARY,
        NUMERICAL_GATE,
        EXECUTION_GATE,
        *SCIENTIFIC_REVIEWS.values(),
    }
    if (
        gate.get("status") != "accepted_completed_sensitivity_program_with_unresolved_case"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("reference_summary") != REFERENCE_SUMMARY
        or gate.get("report_proof_contract") != REPORT_PROOF_CONTRACT
        or gate.get("scientific_reviews") != SCIENTIFIC_REVIEWS
        or any(type(gate.get(k)) is not int or gate[k] != v for k, v in REPORT_COUNTS.items())
        or not required <= set(gate.get("files", {}))
        or first_completion.r.STATE in gate.get("files", {})
    ):
        raise ValueError("complete independent54-valid/one-unresolved report contract required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    old._unchanged(root, pins)
    completed = completion_api().verify_completion_sources(root, summary_path=COMPLETION_SUMMARY)
    old._require(pins, completed["files"])
    remaining = completed["admission"]
    numerical, admission = remaining["worker_admission"], remaining["original_admission"]
    for closure in [remaining["files"], numerical["files"], admission["files"]]:
        old._require(pins, closure)
    old.refs.verify_reference_sources(root, pins)
    summary = old._read(root, pins, COMPLETION_SUMMARY)
    jobs, plan = admission["gate"]["jobs"], old._read(root, pins, old.PLAN)
    if (
        summary != completed["summary"]
        or summary.get("schema_version") != 3
        or summary.get("run_id") != "remaining-sensitivities-v1"
        or summary.get("status") != "sensitivity_program_complete_with_unresolved_case"
        or plan.get("jobs") != jobs
        or len(jobs) != 55
        or [j.get("order") for j in jobs] != list(range(55))
        or len({j.get("id") for j in jobs}) != 55
        or plan.get("files") != admission["files"]
        or plan.get("gate_sha256") != pins[old.fit.GATE]
        or any(type(summary.get(k)) is not int or summary[k] != v for k, v in REPORT_COUNTS.items())
        or summary.get("confirmation_outcomes_parsed") is not False
        or summary.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("schema3 exact55 probes/54 usable/one unresolved/57 calls required")
    for field, name in {
        "original_plan": old.PLAN,
        "worker_spec_gate": NUMERICAL_GATE,
        "execution_authority_gate": EXECUTION_GATE,
        "baseline_state": CONTROL + "/baseline-state.json",
        "baseline_registry": CONTROL + "/baseline-registry.json",
        "disposition_review": SCIENTIFIC_REVIEWS["unresolved_case"],
        "pilot_review": CONTROL + "/pilot-review-acceptance.json",
    }.items():
        if summary.get(field) != name or summary.get(field + "_sha256") != pins.get(name):
            raise ValueError("literal schema3 completion prerequisites required")
    accepted, failures, unresolved = [
        summary.get(k) for k in ["accepted", "retained_failures", "unresolved_cases"]
    ]
    orders = [i for i in range(55) if i != 36]
    if (
        not isinstance(accepted, list)
        or [e.get("order") for e in accepted] != orders
        or gate.get("accepted") != accepted
        or accepted[:36] != remaining["accepted_prefix"]
        or not isinstance(failures, list)
        or [(f.get("order"), f.get("attempt")) for f in failures] != [(34, 1), (36, 1), (36, 2)]
        or failures != remaining["failed_attempts"]
        or gate.get("retained_failures") != failures
        or not isinstance(unresolved, list)
        or len(unresolved) != 1
        or unresolved != remaining["unresolved_cases"]
        or gate.get("unresolved_cases") != unresolved
    ):
        raise ValueError("ordered54 valid fits and three retained failed calls required")
    missing = unresolved[0]
    if (
        missing.get("order") != 36
        or missing.get("case_id") != jobs[36]["id"]
        or missing.get("original_job") != jobs[36]
        or missing.get("status") != "computationally_unresolved"
        or missing.get("failed_attempts") != failures[1:]
        or missing.get("no_third_attempt") is not True
        or missing.get("posterior") is not None
        or missing.get("posterior_sha256") is not None
        or any(k in missing for k in ["summary", "parameters", "curves", "conditional_ppc"])
        or any(f.get("original_job") != jobs[36] for f in failures[1:])
        or failures[1].get("execution_job") != jobs[36]
        or failures[2].get("execution_job") != numerical["jobs"][0]
        or failures[2]["execution_job"].get("original_job") != jobs[36]
    ):
        raise ValueError("unresolved case36 must bind both failed attempts and no usable posterior")
    if remaining["jobs"] != numerical["jobs"][1:]:
        raise ValueError("only18 untouched original37..54 execution descriptors permitted")
    for order, entry in zip(orders, accepted, strict=True):
        job = jobs[order]
        producer = (
            "repair_v1" if order == 34 else "numerical_protocol" if order >= 37 else "original"
        )
        role = (
            "numerical_repair"
            if order == 34
            else "numerical_protocol"
            if order >= 37
            else "original"
        )
        execution = (
            repair.repair_job(job)
            if order == 34
            else numerical["jobs"][order - 36]
            if order >= 37
            else job
        )
        folder, raw = producer_paths(root, entry, numerical)
        receipt = str((folder / "attempt-evidence.json").relative_to(root))
        if (
            entry.get("order") != order
            or entry.get("case_id") != job["id"]
            or entry.get("original_job") != job
            or entry.get("execution_job") != execution
            or entry.get("producer") != producer
            or entry.get("source_role") != role
            or entry.get("posterior") != str(raw.relative_to(root))
            or entry.get("posterior_sha256") != pins.get(str(raw.relative_to(root)))
            or entry.get("charged_slots") != 1
            or entry.get("receipt") != receipt
            or entry.get("receipt_sha256") != pins.get(receipt)
            or (
                order >= 37
                and (
                    entry.get("execution_gate") != EXECUTION_GATE
                    or entry.get("worker_spec_gate") != NUMERICAL_GATE
                )
            )
        ):
            raise ValueError("ordered same-model producer/job/raw/receipt bindings required")
    mapping = summary.get("successful_numerical_repair_mapping", {})
    if (
        set(mapping) != {jobs[34]["id"]}
        or gate.get("successful_numerical_repair_mapping") != mapping
        or mapping[jobs[34]["id"]].get("posterior") != accepted[34]["posterior"]
        or mapping[jobs[34]["id"]].get("posterior_sha256") != accepted[34]["posterior_sha256"]
        or gate.get("protocol_amendment") != summary.get("protocol_amendment")
        or summary.get("protocol_amendment")
        != dict(
            protocol=remaining["gate"]["protocol"],
            first_attempt_original_case_ids=[j["id"] for j in jobs[37:]],
            execution_jobs=remaining["jobs"],
        )
        or len(summary.get("completion_attempts", [])) != 18
    ):
        raise ValueError("only successful repair34 and18 first-attempt protocol cases required")
    for label, path in SCIENTIFIC_REVIEWS.items():
        review = old._read(root, pins, path)
        if (
            review.get("status") != SCIENCE_STATUSES[label]
            or review.get("independent_checker") is not True
            or review.get("confirmation_outcomes_parsed") is not False
            or review.get("reserved_outcomes") != "sealed"
        ):
            raise ValueError(
                "all five underlying independent scientific/disposition reviews required"
            )
        old._require(pins, review.get("files"))
        if label == "unresolved_case":
            if review.get("no_third_case36_attempt") is not True:
                raise ValueError("independent unresolved disposition must forbid third attempt")
            for failed in failures:
                old._require(
                    review["files"],
                    {
                        **failed["files"],
                        **failed["physical_files"],
                        failed["receipt"]: failed["receipt_sha256"],
                    },
                )
        if label == "remaining":
            if review.get("execution_jobs") != remaining["jobs"] or any(
                type(review.get(k)) is not int or review[k] != v for k, v in REPORT_COUNTS.items()
            ):
                raise ValueError(
                    "independent remaining science must cover18 jobs/54 valid/one unresolved"
                )
            old._require(review["files"], remaining["files"])
            for entry in accepted[36:]:
                old._require(
                    review["files"], {**entry["files"], entry["receipt"]: entry["receipt_sha256"]}
                )
    fresh_producer_bytes(root, accepted, failures, numerical, pins)
    old._unchanged(root, pins)
    return dict(
        gate=gate,
        files=pins,
        jobs=jobs,
        accepted=accepted,
        failures=failures,
        unresolved=unresolved,
        admission=admission,
        numerical_admission=numerical,
        run_summary=summary,
    )


def collect_views(root: Path):
    """Use only54 reviewed fit summaries; recompute14 historical reference summaries."""
    root = root.resolve()
    checked = verify_report_sources(root)
    pins, admission = checked["files"], checked["admission"]
    views = []
    for entry in checked["accepted"]:
        job = entry["original_job"]
        folder_path, _ = producer_paths(root, entry, checked["numerical_admission"])
        folder = str(folder_path.relative_to(root))
        summary = old._read(root, pins, folder + "/summary.json")
        inputs = old._read(root, pins, folder + "/inputs.json")
        if (
            not old.fit._summary_valid(summary)
            or summary.get("membership") != job["training_record_ids"]
        ):
            raise ValueError("valid reviewed summary with original membership required")
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
                summary=summary,
                prior_specification=old._priors(
                    root, job["target"], job["kind"], job["prior_variant"], inputs
                ),
                provenance=dict(
                    receipt=entry["receipt"],
                    receipt_sha256=entry["receipt_sha256"],
                    prediction_seed=job["seed"] + 1,
                    new_sampler_calls=1,
                    source_role=entry["source_role"],
                    execution_job=entry["execution_job"],
                    posterior=entry["posterior"],
                    posterior_sha256=entry["posterior_sha256"],
                ),
            )
        )
    lanes, contract = old.load_lanes(root)
    if contract != admission["contract"]:
        raise ValueError("reference and sensitivity source contracts differ")
    provenance = []
    for order, descriptor in enumerate(old.refs.descriptors()):
        lane, kind, indices, posterior, proof = old.refs.load_reference(
            root, descriptor["key"], lanes, pins
        )
        seed = REFERENCE_SUMMARY["seed_base"] + REFERENCE_SUMMARY["seed_stride"] * order
        summary = old.summarize_posterior(
            lane, kind, posterior, indices=indices, seed=seed, draws=REFERENCE_SUMMARY["draws"]
        )
        if not old.fit._summary_valid(summary):
            raise ValueError("finite valid historical reference summary required")
        original, chosen = lanes[lane.target], set(summary["membership"])
        proof = {
            **proof,
            "summary_seed": seed,
            "summary_draws": REFERENCE_SUMMARY["draws"],
            "descriptor_order": order,
        }
        provenance.append(proof)
        views.append(
            dict(
                view_id=descriptor["key"],
                target=lane.target,
                kind=kind,
                role=descriptor["role"],
                scenario=descriptor["role"],
                prior_variant="base",
                distance_mode=descriptor["distance_mode"],
                training_record_ids=summary["membership"],
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
                summary=summary,
                prior_specification=old._priors(root, lane.target, kind, "base"),
                provenance=proof,
            )
        )
    fresh_producer_bytes(
        root, checked["accepted"], checked["failures"], checked["numerical_admission"], pins
    )
    old._unchanged(root, pins)
    return views, provenance, pins, checked["run_summary"]


def probe_dispositions(run):
    """Retain all planned slots without creating a posterior view for an unresolved probe."""
    rows: list[dict[str, Any]] = [
        dict(
            case_id=e["case_id"],
            order=e["order"],
            original_job=e["original_job"],
            status="accepted_scientific_computation",
            receipt=e["receipt"],
            receipt_sha256=e["receipt_sha256"],
            posterior=e["posterior"],
            posterior_sha256=e["posterior_sha256"],
        )
        for e in run["accepted"]
    ]
    rows += [
        dict(
            case_id=e["case_id"],
            order=e["order"],
            original_job=e["original_job"],
            status=e["status"],
            posterior=None,
            no_third_attempt=e["no_third_attempt"],
            failed_attempt_receipts=[
                dict(attempt=f["attempt"], receipt=f["receipt"], receipt_sha256=f["receipt_sha256"])
                for f in e["failed_attempts"]
            ],
        )
        for e in run["unresolved_cases"]
    ]
    rows.sort(key=lambda row: row["order"])
    if [r["order"] for r in rows] != list(range(55)) or len({r["case_id"] for r in rows}) != 55:
        raise ValueError("all55 original probe dispositions required")
    return rows


# Version-adapted copies of the frozen pure report functions below. Numerical
# calculations are unchanged; only54/68 cardinality and the one unresolved
# heatmap row differ. Differential tests compare every surviving table row.
def sensitivity_tables(views: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Pure within-form summaries; differences of marginal medians, not paired draws.

    Changes have no posterior interval: subtracting independent marginal bounds
    would not be an interval for a difference. Unsupported cells keep None.
    """
    if len(views) != 68 or len({v["view_id"] for v in views}) != 68:
        raise ValueError("exact68unique views required")
    base = {(v["target"], v["kind"]): v for v in views if v["role"] == "base"}
    if set(base) != set(old.FORMS) or sum(v["role"] == "base" for v in views) != 8:
        raise ValueError("exact eight source/form base references required")
    if (
        sum(v["role"] == "sensitivity" for v in views) != 54
        or sum(v["role"].startswith("reuse-") for v in views) != 6
    ):
        raise ValueError("54 usable plus six existing deletion views required")
    tables = {name: [] for name in TABLES}
    for view in views:
        old._valid_summary(view)
        same_base = base[view["target"], view["kind"]]
        if set(view["training_record_ids"] + view["omitted_record_ids"]) != set(
            same_base["training_record_ids"]
        ):
            raise ValueError("every view must partition its full source-specific base cohort")
        identity, summary = old._identity(view), view["summary"]
        positive = view["target"] != "T-CAL"
        modeled_units = "log reference ratio" if positive else "signed minutes"
        for group in ["parameters", "derived"]:
            for row in summary[group]:
                if "distance_km" in row and not row["within_training_distance_range"]:
                    continue
                units = (
                    "dimensionless"
                    if row.get("quantity", "").endswith("elasticity")
                    else modeled_units
                )
                tables[TABLES[0]].append(
                    {
                        **identity,
                        "row_type": group,
                        **row,
                        "units": units,
                        "interval_type": "90% marginal posterior interval",
                        "prior_specification": json.dumps(
                            view["prior_specification"], sort_keys=True
                        ),
                    }
                )
        for row in summary["curves"]:
            if row["within_training_distance_range"]:
                tables[TABLES[1]].append(
                    {
                        **identity,
                        **row,
                        "units": "minutes",
                        "interval_type": "90% posterior band for population median"
                        if row["curve"] == "population_median"
                        else "90% new-event report predictive quantiles",
                    }
                )
        originals = {
            r["distance_km"]: r
            for r in same_base["summary"]["curves"]
            if r["curve"] == "population_median"
        }
        for row in summary["curves"]:
            if row["curve"] != "population_median":
                continue
            original = originals[row["distance_km"]]
            supported = (
                row["within_training_distance_range"] and original["within_training_distance_range"]
            )
            change = (
                None
                if not supported
                else (
                    row["log_q50"] - original["log_q50"]
                    if positive
                    else row["q50"] - original["q50"]
                )
            )
            with np.errstate(over="ignore", under="ignore"):
                ratio = None if change is None or not positive else float(np.exp(change))
            representable = ratio is None or math.isfinite(ratio) and ratio > 0
            tables[TABLES[2]].append(
                {
                    **identity,
                    "distance_km": row["distance_km"],
                    "baseline_view_id": same_base["view_id"],
                    "common_supported": bool(supported),
                    "median_log_shift": change if positive else None,
                    "native_median_ratio": ratio if representable else None,
                    "native_ratio_representable": representable if supported and positive else None,
                    "signed_median_shift_minutes": change if not positive else None,
                    "comparison": "difference_of_marginal_posterior_medians_no_difference_interval",
                    "support_rule": (
                        "intersection_of_training_distance_ranges_not_dense_coverage_proof"
                    ),
                }
            )
        for row in summary["conditional_ppc"]:
            observed = row["observed"]
            low, high = row["replicated_q05"], row["replicated_q95"]
            if any(x is None or not math.isfinite(x) for x in [observed, low, high]):
                raise ValueError("finite observed and replicated PPC quantiles required")
            tables[TABLES[3]].append(
                {
                    **identity,
                    **row,
                    "observed_outside_replicated_90": not low <= observed <= high,
                    "units": "minutes" if row["scale"] == "native-minutes" else modeled_units,
                    "check_scope": "conditional_fitted_events_in_sample_not_held_out",
                }
            )
        tables[TABLES[4]].append(
            {
                **identity,
                **summary["support"],
                "event_counts": json.dumps(summary["support"]["event_counts"], sort_keys=True),
                "sequence_counts": json.dumps(
                    summary["support"]["sequence_counts"], sort_keys=True
                ),
                "training_record_ids": json.dumps(view["training_record_ids"]),
                "omitted_record_ids": json.dumps(view["omitted_record_ids"]),
                "excluded_record_ids": json.dumps(view["excluded_record_ids"]),
                "omitted_count": len(view["omitted_record_ids"]),
                "excluded_count": len(view["excluded_record_ids"]),
                "new_sampler_calls": 1 if view["role"] == "sensitivity" else 0,
                "selection_interpretation": (
                    "conditional_on_reporting_no_missingness_identification"
                ),
            }
        )
    return tables


def figures(tables, output: Path):
    """Two figure families only; consume trusted supplied tables, no data loaders.

    Takeaway: show assumption sensitivity within each supported source/form.
    Audience: scientific readers. Destination: report. Baseline bands describe
    population medians, and heatmap cells are descriptive marginal-median shifts.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    output = Path(output)
    curve_rows = tables[TABLES[1]]
    colors = {
        "power_0.5": "#0072B2",
        "power_1.5": "#0072B2",
        "joint_wider": "#D55E00",
        "t4_matched": "#009E73",
        "gamma_wider_only": "#CC79A7",
    }
    styles: dict[str, Any] = {
        "power_0.5": "-",
        "power_1.5": "--",
        "joint_wider": "-",
        "t4_matched": "-",
        "gamma_wider_only": ":",
    }
    labels = {
        "power_0.5": "Prior power 0.5",
        "power_1.5": "Prior power 1.5",
        "joint_wider": "Joint wider",
        "t4_matched": "Matched Student-t4",
        "gamma_wider_only": "Gamma SD 0.8 only",
    }
    with plt.rc_context(
        {
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
        }
    ):
        fig, axes = plt.subplots(4, 2, figsize=(13, 15), layout="constrained")
        for ax, (target, kind) in zip(axes.flat, old.FORMS, strict=True):
            rows = [
                r
                for r in curve_rows
                if r["target"] == target and r["kind"] == kind and r["curve"] == "population_median"
            ]
            baseline = sorted(
                [r for r in rows if r["role"] == "base"], key=lambda r: r["distance_km"]
            )
            d = [r["distance_km"] for r in baseline]
            ax.fill_between(
                d,
                [r["q05"] for r in baseline],
                [r["q95"] for r in baseline],
                color="0.85",
                label="Base 90% posterior band",
            )
            ax.plot(d, [r["q50"] for r in baseline], color="0.2", linewidth=2)
            for variant in labels:
                chosen = sorted(
                    [
                        r
                        for r in rows
                        if r["role"] == "sensitivity"
                        and r["scenario"] == "prior"
                        and r["prior_variant"] == variant
                    ],
                    key=lambda r: r["distance_km"],
                )
                if chosen:
                    ax.plot(
                        [r["distance_km"] for r in chosen],
                        [r["q50"] for r in chosen],
                        color=colors[variant],
                        linestyle=styles[variant],
                        linewidth=1.5,
                    )
            ax.set(
                xscale="log",
                xlabel="Distance (km; log scale)",
                ylabel="Reported duration (minutes; log scale)",
                title=(
                    f"{'NCEI' if target == 'NCEI-native-duration' else 'NTWC ' + target} · {kind}"
                ),
            )
            if target != "T-CAL":
                ax.set_yscale("log")
            else:
                ax.set_ylabel("Signed T-CAL (minutes)")
                ax.axhline(0, color="0.75", linewidth=0.7)
            ax.grid(axis="y", color="0.9", linewidth=0.5)
        fig.suptitle(
            "Prior assumptions and population medians\n"
            "Base posterior bands; alternative median lines; supported distances only",
            fontsize=15,
        )
        handles = [Line2D([], [], color="0.2", linewidth=2, label="Base (90% posterior band)")]
        handles += [
            Line2D([], [], color=colors[v], linestyle=styles[v], label=labels[v]) for v in labels
        ]
        fig.legend(
            handles=handles,
            loc="outside lower center",
            ncol=3,
            frameon=False,
            title="Source: NCEI reported durations; NTWC T-OBS and T-CAL",
            title_fontsize=10,
        )
        for ext in ["png", "svg"]:
            fig.savefig(output / f"prior-population-median-curves.{ext}", dpi=160)
        plt.close(fig)
        scenarios = [
            *old.NONPRIOR_SCENARIOS,
            "reuse-tohoku",
            "reuse-chile2010",
            "reuse-influential2014",
        ]
        rows = tables[TABLES[2]]
        arrays = []
        for kind in ["distance-scale", "mean-curvature"]:
            lookup = {
                (r["scenario"], r["distance_km"]): r
                for r in rows
                if r["target"] == "NCEI-native-duration" and r["kind"] == kind
            }
            expected_missing = (
                {("era-2014plus", float(d)) for d in old.GRID_KM}
                if kind == "distance-scale"
                else set()
            )
            expected_cells = {(scenario, float(d)) for scenario in scenarios for d in old.GRID_KM}
            if expected_cells - set(lookup) != expected_missing:
                raise ValueError("only reviewed unresolved linear2014 cells may be missing")
            arrays.append(
                np.array(
                    [
                        [
                            lookup[s, float(d)]["median_log_shift"]
                            if (s, float(d)) in lookup and lookup[s, float(d)]["common_supported"]
                            else np.nan
                            for d in old.GRID_KM
                        ]
                        for s in scenarios
                    ],
                    dtype=float,
                )
            )
        finite = np.concatenate([a[np.isfinite(a)] for a in arrays])
        limit = max(float(np.max(np.abs(finite))) if finite.size else 0, 1e-6)
        fig, axes = plt.subplots(1, 2, figsize=(16, 9), layout="constrained", sharey=True)
        cmap = plt.get_cmap("RdBu_r").with_extremes(bad="0.92")
        for ax, kind, values in zip(
            axes, ["distance-scale", "mean-curvature"], arrays, strict=True
        ):
            image = ax.imshow(
                np.ma.masked_invalid(values),
                cmap=cmap,
                norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit),
                aspect="auto",
            )
            ax.set_xticks(range(9), ["20", "50", "100", "500", "1k", "2k", "5k", "10k", "20k"])
            ax.set_yticks(range(14), [old.SCENARIO_LABELS[s] for s in scenarios])
            ax.set(title=kind, xlabel="Distance (km)")
            if kind == "distance-scale":
                row = scenarios.index("era-2014plus")
                ax.add_patch(
                    Rectangle(
                        (-0.5, row - 0.5),
                        len(old.GRID_KM),
                        1,
                        facecolor="0.96",
                        edgecolor="0.45",
                        hatch="////",
                        linewidth=0.7,
                    )
                )
                ax.text(
                    (len(old.GRID_KM) - 1) / 2,
                    row,
                    "Unresolved",
                    ha="center",
                    va="center",
                    fontsize=11,
                    bbox=dict(facecolor="white", edgecolor="none", pad=2),
                )
        fig.colorbar(image, ax=list(axes), label="Log change in population median versus full base")
        fig.suptitle(
            "NCEI data stresses within each mean form\n"
            "Hatched: unresolved linear 2014-onward fit; gray: outside common distance support",
            fontsize=15,
        )
        fig.supxlabel(
            "Source: NCEI native reported durations; marginal posterior medians", fontsize=10
        )
        for ext in ["png", "svg"]:
            fig.savefig(output / f"ncei-data-stress-log-changes.{ext}", dpi=160)
        plt.close(fig)


def report(root: Path, output: Path):
    root, output = root.resolve(), Path(output).absolute()
    if output.resolve() != output or not output.is_relative_to(root) or output.exists():
        raise ValueError("new nonsymlink project-local report directory required")
    views, provenance, pins, run = collect_views(root)
    tables = sensitivity_tables(views)
    dispositions = probe_dispositions(run)
    old._unchanged(root, pins)
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        dict(
            files=pins,
            reference_summary=REFERENCE_SUMMARY,
            successful_numerical_repair_mapping=run["successful_numerical_repair_mapping"],
            protocol_amendment=run["protocol_amendment"],
            report_proof_contract=REPORT_PROOF_CONTRACT,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
        ),
    )
    for name, rows in tables.items():
        old.write_table(output / (name + ".csv"), rows)
    write_json(output / "reference-provenance.json", {"references": provenance})
    write_json(
        output / "summary.json",
        dict(
            status="pending_independent_scientific_and_figure_review",
            views=68,
            new_fits=54,
            **REPORT_COUNTS,
            unresolved_cases=run["unresolved_cases"],
            probe_dispositions=dispositions,
            unresolved_comparison=UNRESOLVED_NOTE,
            base_references=8,
            reused_training_posteriors=6,
            reference_summary=REFERENCE_SUMMARY,
            table_rows={name: len(rows) for name, rows in tables.items()},
            qualifications=QUALIFICATIONS,
            numerical_repair_method=METHOD_NOTE,
            successful_numerical_repair_mapping=run["successful_numerical_repair_mapping"],
            protocol_amendment=run["protocol_amendment"],
            report_proof_contract=REPORT_PROOF_CONTRACT,
            selection="none",
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
        ),
    )
    write_json(
        output / "probe-dispositions.json",
        {"probes": dispositions, "unresolved_cases": run["unresolved_cases"]},
    )
    figures(tables, output)
    text = (
        old.findings(tables, run)
        .replace("55 new fits", "54 usable fits")
        .replace("all 69 views", "all 68 usable views")
        .replace("all 55 attempt proofs", "all 57 attempt proofs and the unresolved disposition")
        .replace(
            "scripts/summarize_arrival_sensitivities.py",
            "scripts/summarize_arrival_completed_sensitivities.py",
        )
    )
    (output / "findings.md").write_text(
        text.replace(
            "# Sensitivity of reported arrival durations\n",
            "# Sensitivity of reported arrival durations\n\n" + UNRESOLVED_NOTE + "\n",
            1,
        )
        + "\n## Numerical computation and call accounting\n\n"
        + METHOD_NOTE
        + "\n"
    )
    verify_report_sources(root)
    old._unchanged(root, pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
