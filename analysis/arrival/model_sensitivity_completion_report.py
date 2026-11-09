"""Closed 55-case report with two retained failures and 57 actual sampler calls."""

# pyright: basic
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from analysis.arrival import model_sensitivity_repair as repair
from analysis.arrival import model_sensitivity_report as old
from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_completion as first_completion

GATE = old.GATE
OUTPUT = "artifacts/models/arrival-timing/exploration-sensitivity-report-v1"
NUMERICAL_OUTPUT = old.fit.OUTPUT + "/numerical-protocol-v2"
COMPLETION_SUMMARY = NUMERICAL_OUTPUT + "/run-summary.json"
NUMERICAL_GATE = str(Path(old.fit.GATE).parent) + "/numerical-protocol-v2/review-acceptance.json"
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
    "numerical_v2": NUMERICAL_OUTPUT + "/scientific-review.json",
}
SCIENCE_STATUSES = {
    "first34": "accepted_sensitivity_thirty_four_case_checkpoint",
    "repair_v1": "accepted_sensitivity_same_model_numerical_repair",
    "baseline_v2": "accepted_sensitivity_remaining_numerical_protocol_plan",
    "numerical_v2": "accepted_sensitivity_numerical_protocol_computations",
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
            "tests/test_run_arrival_sensitivity_numerical.py",
            "analysis/arrival/model_sensitivity_completion_report.py",
            "scripts/summarize_arrival_completed_sensitivities.py",
            "tests/test_arrival_model_sensitivity_completion_report.py",
        }
    )
)
METHOD_NOTE = (
    "These 55 accepted logical sensitivity fits required 57 sampler calls. "
    "Two original NCEI linear fits (pre-2007 and 2014 onward) failed diagnostics. "
    "Both raw outputs remain retained; neither failed summary is used. The second failure "
    "occurred after the first separately reviewed repair. A reviewed common numerical "
    "protocol used four chains, 2,000 retained draws, 2,000 tuning draws and "
    "target_accept=0.99 for the second repair and the first attempts of the remaining "
    "18 prespecified cases. The first repair used the same numerical settings. "
    "Original models, priors, masks, cohorts and seeds remain unchanged; these are not "
    "independent repeat experiments. Predictive summaries retain original seed + 1 and "
    "800 draws. No native data were changed or imputed. Both failed calls count toward "
    "computation costs and contribute no posterior draws to the 69 report views. "
    "Accepted-case summaries rely on independent scientific review and fresh complete "
    "producer bytes; the 14 historical reference summaries are recomputed."
)


def numerical_api() -> Any:
    return importlib.import_module("analysis.arrival.model_sensitivity_numerical_fit")


def completion_api() -> Any:
    return importlib.import_module("scripts.run_arrival_sensitivity_numerical")


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
        folder = root / old.fit.OUTPUT / "jobs" / failure["case_id"]
        raw = root / old.fit.STORE / (failure["case_id"] + ".nc")
        old._require(pins, failure["physical_files"])
        old._require(pins, failure["files"])
        if physical_inventory(root, folder, raw) != failure["physical_files"]:
            raise ValueError("retained failed producer bytes or inventory changed")


def verify_report_sources(root: Path) -> dict[str, Any]:
    """Admit independent science and all producer bytes before scientific table bodies."""
    root = root.resolve()
    gate = json.loads(old._path(root, GATE).read_text())
    required = set(CONSUMED) | {
        old.PLAN,
        old.fit.GATE,
        COMPLETION_SUMMARY,
        NUMERICAL_GATE,
        *SCIENTIFIC_REVIEWS.values(),
    }
    if (
        gate.get("status") != "accepted_all_exploration_sensitivity_computations"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("reference_summary") != REFERENCE_SUMMARY
        or gate.get("report_proof_contract") != REPORT_PROOF_CONTRACT
        or gate.get("scientific_reviews") != SCIENTIFIC_REVIEWS
        or not required <= set(gate.get("files", {}))
        or first_completion.r.STATE in gate.get("files", {})
    ):
        raise ValueError("complete independent57-call report science/byte-proof contract required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    old._unchanged(root, pins)
    completed = completion_api().verify_completion_sources(root, summary_path=COMPLETION_SUMMARY)
    old._require(pins, completed["files"])
    numerical = completed["admission"]
    admission = numerical["original_admission"]
    old._require(pins, admission["files"])
    old._require(pins, numerical["files"])
    old.refs.verify_reference_sources(root, pins)
    summary = old._read(root, pins, COMPLETION_SUMMARY)
    jobs, plan = admission["gate"]["jobs"], old._read(root, pins, old.PLAN)
    if (
        summary != completed["summary"]
        or summary.get("schema_version") != 2
        or summary.get("run_id") != "numerical-protocol-v2"
        or summary.get("status") != "sensitivity_computations_complete"
        or plan.get("jobs") != jobs
        or len(jobs) != 55
        or [j.get("order") for j in jobs] != list(range(55))
        or len({j["id"] for j in jobs}) != 55
        or plan.get("files") != admission["files"]
        or plan.get("gate_sha256") != pins[old.fit.GATE]
        or any(
            type(summary.get(k)) is not int or summary[k] != v
            for k, v in {
                "logical_cases": 55,
                "actual_sampler_calls": 57,
                "calls_charged": 57,
                "calls_started": 57,
                "max_sampler_call_slots": 110,
            }.items()
        )
        or summary.get("confirmation_outcomes_parsed") is not False
        or summary.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("schema2 original55 logical cases and explicit57 actual calls required")
    for field, name in {
        "original_plan": old.PLAN,
        "gate_path": NUMERICAL_GATE,
        "baseline_state": NUMERICAL_OUTPUT + "/baseline-state.json",
        "baseline_registry": NUMERICAL_OUTPUT + "/baseline-registry.json",
        "baseline_review": SCIENTIFIC_REVIEWS["baseline_v2"],
        "pilot_review": NUMERICAL_OUTPUT + "/pilot-review-acceptance.json",
    }.items():
        if summary.get(field) != name or summary.get(field + "_sha256") != pins.get(name):
            raise ValueError("literal schema2 completion prerequisites required")
    accepted, failures = summary.get("accepted"), summary.get("retained_failures")
    if (
        not isinstance(accepted, list)
        or len(accepted) != 55
        or gate.get("accepted") != accepted
        or not isinstance(failures, list)
        or [f.get("order") for f in failures] != [34, 36]
        or failures != numerical["failed_attempts"]
        or gate.get("retained_failures") != failures
        or accepted[:36] != numerical["accepted_prefix"]
    ):
        raise ValueError(
            "exact35original/one first repair/19numerical and two retained failures required"
        )
    for order, (job, entry) in enumerate(zip(jobs, accepted, strict=True)):
        producer = (
            "repair_v1" if order == 34 else "numerical_protocol" if order >= 36 else "original"
        )
        role = (
            "numerical_repair"
            if order in {34, 36}
            else "numerical_protocol"
            if order >= 37
            else "original"
        )
        execution = (
            repair.repair_job(job)
            if order == 34
            else numerical["jobs"][order - 36]
            if order >= 36
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
                order >= 36
                and (
                    entry.get("run_id") != "numerical-protocol-v2"
                    or entry.get("execution_gate") != NUMERICAL_GATE
                )
            )
        ):
            raise ValueError("ordered same-model producer/job/raw/receipt bindings required")
    mapping = summary.get("numerical_repair_mapping", {})
    if (
        set(mapping) != {jobs[34]["id"], jobs[36]["id"]}
        or gate.get("numerical_repair_mapping") != mapping
        or any(
            mapping[jobs[i]["id"]].get("posterior") != accepted[i]["posterior"]
            or mapping[jobs[i]["id"]].get("posterior_sha256") != accepted[i]["posterior_sha256"]
            for i in [34, 36]
        )
        or gate.get("protocol_amendment") != summary.get("protocol_amendment")
        or summary.get("protocol_amendment")
        != {
            "protocol": numerical["gate"]["protocol"],
            "first_attempt_original_case_ids": [j["id"] for j in jobs[37:]],
            "execution_jobs": numerical["jobs"],
        }
        or len(summary.get("completion_attempts", [])) != 19
    ):
        raise ValueError("two explicit repair mappings and common remaining19 protocol required")
    for label, path in SCIENTIFIC_REVIEWS.items():
        review = old._read(root, pins, path)
        if (
            review.get("status") != SCIENCE_STATUSES[label]
            or review.get("independent_checker") is not True
            or review.get("confirmation_outcomes_parsed") is not False
            or review.get("reserved_outcomes") != "sealed"
        ):
            raise ValueError("all four underlying independent scientific reviews required")
        old._require(pins, review.get("files"))
        if label == "numerical_v2":
            if review.get("execution_jobs") != numerical["jobs"] or any(
                type(review.get(k)) is not int or review[k] != v
                for k, v in {
                    "logical_cases": 55,
                    "actual_sampler_calls": 57,
                    "calls_charged": 57,
                    "calls_started": 57,
                }.items()
            ):
                raise ValueError("independent numerical science must cover all19 jobs and57 calls")
            old._require(review["files"], numerical["files"])
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
        admission=admission,
        numerical_admission=numerical,
        run_summary=summary,
    )


def collect_views(root: Path):
    """Use reviewed producer bytes without replaying55 fits; recompute14 reference summaries."""
    root = root.resolve()
    checked = verify_report_sources(root)
    pins, admission = checked["files"], checked["admission"]
    views = []
    for job, entry in zip(checked["jobs"], checked["accepted"], strict=True):
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


def report(root: Path, output: Path):
    root, output = root.resolve(), Path(output).absolute()
    if output.resolve() != output or not output.is_relative_to(root) or output.exists():
        raise ValueError("new nonsymlink project-local report directory required")
    views, provenance, pins, run = collect_views(root)
    tables = old.sensitivity_tables(views)
    old._unchanged(root, pins)
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        dict(
            files=pins,
            reference_summary=REFERENCE_SUMMARY,
            numerical_repair_mapping=run["numerical_repair_mapping"],
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
            views=69,
            new_fits=55,
            accepted_logical_fits=55,
            actual_sampler_calls=57,
            retained_failed_calls=2,
            base_references=8,
            reused_training_posteriors=6,
            calls_charged=run["calls_charged"],
            reference_summary=REFERENCE_SUMMARY,
            table_rows={name: len(rows) for name, rows in tables.items()},
            qualifications=QUALIFICATIONS,
            numerical_repair_method=METHOD_NOTE,
            numerical_repair_mapping=run["numerical_repair_mapping"],
            protocol_amendment=run["protocol_amendment"],
            report_proof_contract=REPORT_PROOF_CONTRACT,
            selection="none",
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
        ),
    )
    old.figures(tables, output)
    text = old.findings(tables, run).replace(
        "scripts/summarize_arrival_sensitivities.py",
        "scripts/summarize_arrival_completed_sensitivities.py",
    )
    (output / "findings.md").write_text(
        text + "\n## Numerical computation and call accounting\n\n" + METHOD_NOTE + "\n"
    )
    verify_report_sources(root)
    old._unchanged(root, pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
