"""Versioned 55-case report admission for one reviewed repair and 56 actual calls."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analysis.arrival import model_sensitivity_repair as repair
from analysis.arrival import model_sensitivity_report as old
from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_completion as completion

GATE = old.GATE
OUTPUT = "artifacts/models/arrival-timing/exploration-sensitivity-report-v1"
REFERENCE_SUMMARY, TABLES, QUALIFICATIONS = old.REFERENCE_SUMMARY, old.TABLES, old.QUALIFICATIONS
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
            completion.SELF,
            completion.TEST,
            "analysis/arrival/model_sensitivity_completion_report.py",
            "scripts/summarize_arrival_completed_sensitivities.py",
            "tests/test_arrival_model_sensitivity_completion_report.py",
        }
    )
)
METHOD_NOTE = (
    "These 55 accepted logical sensitivity fits required 56 sampler calls. "
    "One original pre-2007 NCEI linear fit failed diagnostics. Its raw draws remain "
    "retained and its summary is not used. The separately reviewed fit of the same model "
    "used four chains, 2,000 retained draws, 2,000 tuning draws, target_accept=0.99 and "
    "the original seed. Its cohort, priors and likelihood are unchanged. The predictive "
    "summary retains the original seed + 1 and 800 draws. No native data were changed or "
    "imputed. The failed call is counted in computation costs and contributes no posterior "
    "draws or predictive variation to the 69 views."
)


def verify_report_sources(root: Path) -> dict[str, Any]:
    """Close final acceptance, public completion metadata and14 references before bodies."""
    root = root.resolve()
    gate = json.loads(old._path(root, GATE).read_text())
    required = set(CONSUMED) | {
        old.PLAN,
        old.fit.GATE,
        completion.COMPLETION_SUMMARY,
        completion.GATE,
        completion.BASELINE,
        completion.REPAIR_REVIEW,
        repair.GATE,
    }
    if (
        gate.get("status") != "accepted_all_exploration_sensitivity_computations"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("reference_summary") != REFERENCE_SUMMARY
        or not required <= set(gate.get("files", {}))
        or completion.r.STATE in gate.get("files", {})
    ):
        raise ValueError("complete independent55-case repair-aware scientific review required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    old._unchanged(root, pins)
    completed = completion.verify_completion_sources(root)  # Public metadata only; no STATE.
    old._require(pins, completed["files"])
    admission = completed["repair_admission"]["original_admission"]
    old._require(pins, admission["files"])
    old._require(pins, completed["repair_admission"]["files"])
    old.refs.verify_reference_sources(root, pins)
    summary = old._read(root, pins, completion.COMPLETION_SUMMARY)
    plan = old._read(root, pins, old.PLAN)
    jobs = admission["gate"]["jobs"]
    if (
        summary != completed["summary"]
        or completed["jobs"] != jobs
        or plan.get("jobs") != jobs
        or len(jobs) != 55
        or [j.get("order") for j in jobs] != list(range(55))
        or len({j["id"] for j in jobs}) != 55
        or plan.get("files") != admission["files"]
        or plan.get("gate_sha256") != pins[old.fit.GATE]
        or summary.get("status") != "sensitivity_computations_complete"
        or any(
            type(summary.get(k)) is not int or summary[k] != v
            for k, v in {
                "logical_cases": 55,
                "actual_sampler_calls": 56,
                "calls_charged": 56,
                "calls_started": 56,
                "max_sampler_call_slots": 110,
            }.items()
        )
        or summary.get("monitor_failures") != []
        or summary.get("confirmation_outcomes_parsed") is not False
        or summary.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("immutable original55 jobs and explicit56 actual calls required")
    for field, name in {
        "original_plan": old.PLAN,
        "original_baseline": completion.BASELINE,
        "completion_gate": completion.GATE,
        "repair_gate": repair.GATE,
        "repair_review": completion.REPAIR_REVIEW,
    }.items():
        if summary.get(field) != name or summary.get(field + "_sha256") != pins[name]:
            raise ValueError("literal complete source-bound completion prerequisites required")
    accepted = summary.get("accepted")
    if (
        not isinstance(accepted, list)
        or len(accepted) != 55
        or any(not isinstance(e, dict) for e in accepted)
        or gate.get("accepted") != accepted
    ):
        raise ValueError("scientifically accepted55 public descriptors must match exactly")
    repair_job = repair.repair_job(jobs[34])
    if completed["repair_admission"]["job"] != repair_job:
        raise ValueError("one literal same-model repair job required")
    for order, (job, entry) in enumerate(zip(jobs, accepted, strict=True)):
        repaired = order == 34
        folder = repair.OUTPUT if repaired else old.fit.OUTPUT + "/jobs/" + job["id"]
        raw = repair.STORE if repaired else old.fit.STORE + "/" + job["id"] + ".nc"
        receipt = folder + "/attempt-evidence.json"
        if (
            entry.get("order") != order
            or entry.get("case_id") != job["id"]
            or entry.get("original_job") != job
            or entry.get("source_role") != ("numerical_repair" if repaired else "original")
            or entry.get("execution_job") != (repair_job if repaired else job)
            or entry.get("posterior") != raw
            or entry.get("posterior_sha256") != pins.get(raw)
            or entry.get("charged_slots") != 1
            or entry.get("receipt") != receipt
            or entry.get("receipt_sha256") != pins.get(receipt)
        ):
            raise ValueError("exact54 original/one repair source, job and raw bindings required")
        old._require(pins, entry.get("files"))
        required_case = (
            {folder + "/" + n for n in CASE_FILES}
            | {raw}
            | {folder + suffix for suffix in ["-spec.json", ".log", ".supervisor.json"]}
        )
        if not required_case <= set(entry["files"]) or old._read(root, pins, receipt) != {
            "case_id": job["id"],
            "files": entry["files"],
        }:
            raise ValueError("complete literal raw/summary/process/attempt proof required")
    baseline = old._read(root, pins, completion.BASELINE)
    if (
        baseline != completed["baseline"]
        or baseline.get("next_case") != 34
        or baseline.get("calls_charged") != 35
        or baseline.get("calls_started") != 35
        or len(baseline.get("attempts", [])) != 35
    ):
        raise ValueError("retained original34 accepted/35 charged failure baseline required")
    failed = baseline["attempts"][-1]
    failed_folder = old.fit.OUTPUT + "/jobs/" + jobs[34]["id"]
    failed_raw = old.fit.STORE + "/" + jobs[34]["id"] + ".nc"
    old._require(pins, old._read(root, pins, failed["receipt"]).get("files"))
    failure = old._read(root, pins, failed_folder + "/result.json")
    if (
        failed.get("case_id") != jobs[34]["id"]
        or failed.get("outcome") == "accepted"
        or failed.get("charged_slots") != 1
        or failed.get("start_markers") != 1
        or failed.get("receipt") != failed_folder + "/attempt-evidence.json"
        or failed.get("receipt_sha256") != pins.get(failed["receipt"])
        or failure.get("status") != "diagnostic_failure"
        or failure.get("job") != jobs[34]
        or failed_raw not in pins
        or failure.get("posterior") != failed_raw
        or failure.get("posterior_sha256") != pins[failed_raw]
    ):
        raise ValueError("original nonconverged failed raw must remain retained and separate")
    mapping = {
        jobs[34]["id"]: dict(
            repair_job=repair_job,
            repair_gate_sha256=pins[repair.GATE],
            repair_review_sha256=pins[completion.REPAIR_REVIEW],
            failed_attempt_receipt_sha256=failed["receipt_sha256"],
            original_baseline_sha256=pins[completion.BASELINE],
            posterior=repair.STORE,
            posterior_sha256=accepted[34]["posterior_sha256"],
        )
    }
    if (
        summary.get("numerical_repair_mapping") != mapping
        or gate.get("numerical_repair_mapping") != mapping
    ):
        raise ValueError("exact reviewed numerical repair mapping required")
    old._unchanged(root, pins)
    return dict(
        gate=gate,
        files=pins,
        jobs=jobs,
        accepted=accepted,
        admission=admission,
        repair_admission=completed["repair_admission"],
        run_summary=summary,
    )


def collect_views(root: Path):
    """Use54 original producer proofs and one separate repair; preserve69-view recipes."""
    root = root.resolve()
    checked = verify_report_sources(root)
    pins, admission = checked["files"], checked["admission"]
    views = []
    for job, entry in zip(checked["jobs"], checked["accepted"], strict=True):
        if entry["source_role"] == "numerical_repair":
            proof = repair.case_artifacts(
                root, entry["execution_job"], checked["repair_admission"]["files"], accepted=entry
            )
            files, receipt = proof["files"], proof["manifest"]
            folder = repair.OUTPUT
        else:
            files, receipt = old.fit.case_artifacts(root, job, admission["files"], accepted=entry)
            folder = old.fit.OUTPUT + "/jobs/" + job["id"]
        old._require(pins, {**files, str(receipt.relative_to(root)): sha256(receipt)})
        summary = old._read(root, pins, folder + "/summary.json")
        inputs = old._read(root, pins, folder + "/inputs.json")
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
            actual_sampler_calls=56,
            retained_failed_calls=1,
            base_references=8,
            reused_training_posteriors=6,
            calls_charged=run["calls_charged"],
            reference_summary=REFERENCE_SUMMARY,
            table_rows={name: len(rows) for name, rows in tables.items()},
            qualifications=QUALIFICATIONS,
            numerical_repair_method=METHOD_NOTE,
            numerical_repair_mapping=run["numerical_repair_mapping"],
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
    old._unchanged(root, pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
