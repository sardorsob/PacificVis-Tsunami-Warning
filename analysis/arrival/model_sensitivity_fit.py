"""One gated MS-5 fit, retaining raw posterior bytes before any assessment."""

# pyright: basic
from __future__ import annotations

import importlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_data import CONTRACT, load_lanes
from analysis.arrival.model_sensitivity_design import (
    build_sensitivity_design,
    case_indices,
    case_lane,
)
from analysis.arrival.model_sensitivity_priors import build_sensitivity_model
from analysis.arrival.model_sensitivity_summary import summarize_posterior
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.model_validation_report import csv_rows, write_table
from analysis.arrival.models import read_prior

GATE = "artifacts/models/arrival-timing/sensitivity-design-v1/review-acceptance.json"
OUTPUT = "artifacts/models/arrival-timing/exploration-sensitivity-v1"
STORE = "data/processed/models/arrival-sensitivity-v1"
COMPARISON_REVIEW = (
    "artifacts/models/arrival-timing/curvature-sequence-predictive-comparison-v1/"
    "review-acceptance.json"
)
CV_REVIEW = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/review-acceptance.json"
CONSUMED = [
    "analysis/arrival/model_sensitivity_fit.py",
    "scripts/fit_arrival_sensitivity.py",
    "analysis/arrival/model_sensitivity_inputs.py",
    "analysis/arrival/model_sensitivity_design.py",
    "analysis/arrival/model_sensitivity_priors.py",
    "analysis/arrival/model_sensitivity_summary.py",
    "analysis/arrival/model_curvature_prior.py",
    "analysis/arrival/model_curvature.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/models.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/model_validation_report.py",
    "analysis/arrival/evidence.py",
    "scripts/run_arrival_model_validation.py",
    "config/arrival-model-contract-v1.toml",
    "config/arrival-model-priors-v1.toml",
    "config/arrival-mean-curvature-v1.toml",
    "pyproject.toml",
    "uv.lock",
]


def sensitivity_jobs(design: dict[str, Any]) -> list[dict[str, Any]]:
    """Exactly55 ordered original cases, each one new four-chain sampling call."""
    cases = design.get("cases", [])
    if (
        not isinstance(cases, list)
        or len(cases) != 55
        or any(not isinstance(case, dict) for case in cases)
        or any(
            type(case.get("order")) is not int
            or case["order"] != j
            or not isinstance(case.get("id"), str)
            or re.fullmatch(r"ms5-[a-z0-9.-]+", case["id"]) is None
            for j, case in enumerate(cases)
        )
        or len({case["id"] for case in cases}) != 55
    ):
        raise ValueError("exact55distinct ordered sensitivity cases required")
    return [
        {**case, "draws": 2000, "tune": 1000, "cores": 2, "seed": 2886110800 + 1000 * j}
        for j, case in enumerate(cases)
    ]


def _unchanged(root, pins):
    if any(sha256(checked_path(root, name)) != digest for name, digest in pins.items()):
        raise ValueError("accepted sensitivity source identity changed")


def verify_gate(root: Path) -> dict[str, Any]:
    """Close all code, comparison/CV and source references before native loaders."""
    if not (root / GATE).is_file():
        raise ValueError("independently accepted exploration sensitivity design required")
    gate = json.loads((root / GATE).read_text())
    bindings = gate.get("path_bindings", {})
    if (
        gate.get("status") != "accepted_exploration_sensitivity_design"
        or gate.get("independent_checker") is not True
        or gate.get("max_sampler_call_slots") != 110
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("prior_predictions_reviewed") is not True
        or gate.get("comparison_reviewed") is not True
        or gate.get("comparison_review") != COMPARISON_REVIEW
        or bindings.get("output") != OUTPUT
        or bindings.get("store") != STORE
        or not set(CONSUMED) | {COMPARISON_REVIEW, CV_REVIEW} <= set(gate.get("files", {}))
    ):
        raise ValueError(
            "complete independently accepted sensitivity/comparison prerequisites required"
        )
    jobs = gate.get("jobs", [])
    runtime = {"draws", "tune", "cores", "seed"}
    if (
        not isinstance(jobs, list)
        or any(type(job.get(k)) is not int for job in jobs for k in runtime)
        or jobs
        != sensitivity_jobs(
            {"cases": [{k: v for k, v in job.items() if k not in runtime} for job in jobs]}
        )
    ):
        raise ValueError("exact55ordered bounded sensitivity jobs required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    _unchanged(root, pins)

    def require(entries):
        if not entries or any(pins.get(p) != h for p, h in entries.items()):
            raise ValueError("complete transitive reviewed closure required before outcome loading")

    for name, status in [
        (COMPARISON_REVIEW, "accepted_curvature_sequence_predictive_comparison"),
        (CV_REVIEW, "accepted_all_curvature_sequence_computations"),
    ]:
        receipt = json.loads((root / name).read_text())
        if (
            receipt.get("status") != status
            or receipt.get("independent_checker") is not True
            or receipt.get("confirmation_outcomes_parsed") is not False
            or receipt.get("reserved_outcomes") != "sealed"
        ):
            raise ValueError("independently accepted comparison and complete curvature CV required")
        require(receipt.get("files", {}))
        if name == COMPARISON_REVIEW and receipt["files"].get(CV_REVIEW) != pins[CV_REVIEW]:
            raise ValueError("comparison must pin the same accepted complete curvature CV")
    contract = tomllib.loads((root / CONTRACT).read_text())
    require(contract.get("inputs", {}))
    source_io = importlib.import_module("analysis.arrival.model_sensitivity_inputs")
    if not set(source_io.required_sensitivity_paths()) <= set(pins):
        raise ValueError("complete sensitivity source inputs and helper closure required")
    source_io.verify_sensitivity_inputs(root, pins)
    _unchanged(root, pins)
    return {"gate": gate, "files": pins, "contract": contract}


def _new_paths(root, job, output, store):
    case_id = job.get("id")
    if (
        not isinstance(case_id, str)
        or re.fullmatch(r"ms5-[a-z0-9.-]+", case_id) is None
        or output != root / OUTPUT / "jobs" / case_id
        or store != root / STORE / (case_id + ".nc")
    ):
        raise ValueError("literal canonical sensitivity case output/raw paths required")
    for path in [output, store]:
        if path.exists() or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise ValueError("new nonsymlink case paths required; never overwrite retained bytes")


def _summary_valid(summary):
    if any(summary.get("nonfinite_values", {}).values()):
        return False
    if any(summary.get("unrepresentable_native_draws", {}).values()):
        return False
    for group in ["parameters", "derived", "curves", "record_intervals"]:
        if not summary.get(group) or any(
            not row.get("quantile_valid") or row.get("native_representable") is False
            for row in summary[group]
        ):
            return False
    return bool(summary.get("conditional_ppc")) and all(
        row.get("replicated_quantile_valid")
        and row.get("replicated_native_representable") is not False
        and row.get("observed_quantile_valid")
        for row in summary["conditional_ppc"]
    )


def _case_data(root, job, admission):
    gate, pins = admission["gate"], admission["files"]
    if job not in gate["jobs"]:
        raise ValueError("one exact frozen sensitivity job required")
    lanes, frozen = load_lanes(root)
    if frozen != admission["contract"] or set(lanes) != {"NCEI-native-duration", "T-OBS", "T-CAL"}:
        raise ValueError("identical three-source frozen exploration inputs required")
    source_io = importlib.import_module("analysis.arrival.model_sensitivity_inputs")
    metadata = source_io.load_sensitivity_inputs(root, lanes, pins)
    design = build_sensitivity_design(lanes, metadata)
    if sensitivity_jobs(design) != gate["jobs"]:
        raise ValueError("trusted source inputs must reproduce all55exact cohorts/masks/jobs")
    original = lanes[job["target"]]
    ids = case_indices(original, job)
    lane = case_lane(original, job, metadata)
    return lane, ids, frozen


def _case_priors(root, job):
    base = (
        read_curvature_prior(root, "base")
        if job["kind"] == "mean-curvature"
        else read_prior(root, job["target"], "base")
    )
    wider = None
    if job["prior_variant"] == "joint_wider":
        wider = (
            read_curvature_prior(root, "joint_wider")
            if job["kind"] == "mean-curvature"
            else read_prior(root, job["target"], "wider")
        )
    return base, wider


def fit_sensitivity_job(
    root: Path, job: dict[str, Any], output: Path, store: Path
) -> dict[str, Any]:
    """Sample once after admission; save original NetCDF before diagnostics/PPCs."""
    root = root.resolve()
    _new_paths(root, job, output, store)
    admission = verify_gate(root)
    pins = admission["files"]
    lane, ids, frozen = _case_data(root, job, admission)
    base, wider = _case_priors(root, job)
    model = build_sensitivity_model(
        lane, job["kind"], base, job["prior_variant"], wider_prior=wider, indices=ids
    )
    if list(model.coords.get("record") or []) != [lane.record_ids[int(i)] for i in ids]:
        raise ValueError("model graph must contain exactly the designated training records")
    _unchanged(root, pins)
    _new_paths(root, job, output, store)
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("xb"):
        pass
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "source_files": frozen,
            "base_prior": base,
            "wider_prior": wider,
            "comparison_review": COMPARISON_REVIEW,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_json(
        output / "membership.json",
        {
            "training": [lane.record_ids[int(i)] for i in ids],
            "omitted": job["omitted_record_ids"],
            "excluded": job["excluded_record_ids"],
            "target": lane.target,
            "distance_mode": job["distance_mode"],
            "support": job["support"],
            "prediction_scope": "conditional_fitted_events_and_new_event_curves",
        },
    )
    result = {
        "job": job,
        "posterior": str(store.relative_to(root)),
        "records": len(ids),
        "events": len({lane.event_ids[int(i)] for i in ids}),
        "code_and_config": pins,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "scoring_or_forecast_imputation": False,
    }
    try:
        write_json(output / "sampling-start.json", job)
        with model:
            tree = pm.sample(
                draws=2000,
                tune=1000,
                chains=4,
                cores=2,
                target_accept=0.95,
                nuts_sampler="nutpie",
                random_seed=job["seed"],
                progressbar=False,
            )
        tree["observed_data"] = xr.DataTree(
            xr.Dataset(
                {
                    "response": (("record",), lane.response[ids]),
                    "native_minutes": (("record",), lane.y[ids]),
                    "distance_km": (("record",), lane.distance_km[ids]),
                    "reference_minutes": (("record",), lane.reference_minutes[ids]),
                    "event_id": (("record",), [lane.event_ids[int(i)] for i in ids]),
                    "sequence": (("record",), [lane.sequences[int(i)] for i in ids]),
                    "site_id": (("record",), [lane.site_ids[int(i)] for i in ids]),
                },
                coords={"record": [lane.record_ids[int(i)] for i in ids]},
                attrs={"target": lane.target, "scope": "literal_case_training_only"},
            )
        )
        tree.to_netcdf(store, engine="h5netcdf")
        result["posterior_sha256"] = sha256(store)
        posterior = tree["posterior"].to_dataset()
        diagnostics, table = sampling_diagnostics(tree)
        table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
        write_json(output / "diagnostics.json", diagnostics)
        result["diagnostics"] = diagnostics
        if "nutpie" not in str(posterior.attrs).lower():
            result["status"] = "backend_failure"
        elif posterior.sizes.get("chain") != 4 or posterior.sizes.get("draw") != 2000:
            result["status"] = "posterior_shape_failure"
        elif not diagnostics.get("screen_passed"):
            result["status"] = "diagnostic_failure"
        else:
            summary = summarize_posterior(
                lane, job["kind"], posterior, indices=ids, seed=job["seed"] + 1, draws=800
            )
            json.dumps(summary, allow_nan=False)
            write_json(output / "summary.json", summary)
            result.update(summary="summary.json", summary_sha256=sha256(output / "summary.json"))
            for key in ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]:
                write_table(output / (key.replace("_", "-") + ".csv"), summary[key])
            result["status"] = (
                "computed_pending_scientific_review"
                if _summary_valid(summary)
                else "summary_nonfinite_failure"
            )
        _unchanged(root, pins)
    except Exception as exc:
        result.update(
            status="sampling_or_evaluation_failure", error_type=type(exc).__name__, error=str(exc)
        )
        if store.stat().st_size:
            result["posterior_sha256"] = sha256(store)
        try:
            _unchanged(root, pins)
        except Exception:
            result["status"] = "source_identity_failure"
    write_json(output / "result.json", result)
    return result


def case_artifacts(root: Path, job: dict[str, Any], pins: dict[str, str], accepted=None):
    """Read back one complete successful case; return its closed immutable inventory.

    The controller creates the sibling spec/log/supervisor and attempt receipt.
    This verifier adds no scientific fit and writes no file.
    """
    admission = verify_gate(root)
    if admission["files"] != pins:
        raise ValueError("identical accepted sensitivity source closure required")
    lane, ids, frozen = _case_data(root, job, admission)
    folder = root / OUTPUT / "jobs" / job["id"]
    raw = root / STORE / (job["id"] + ".nc")
    manifest = folder / "attempt-evidence.json"
    spec = folder.with_name(job["id"] + "-spec.json")
    supervisor = folder.with_name(folder.name + ".supervisor.json")
    names = [
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
    ]
    mandatory = [folder / name for name in names] + [
        raw,
        spec,
        folder.with_name(folder.name + ".log"),
        supervisor,
    ]
    if not all(path.is_file() and not path.is_symlink() for path in mandatory):
        raise ValueError("complete mandatory sensitivity fit/process evidence required")
    initial_files = {str(path.relative_to(root)): sha256(path) for path in mandatory}
    for name in ["job.json", "sampling-start.json"]:
        if json.loads((folder / name).read_text()) != job:
            raise ValueError("original literal job/start proof required")
    if json.loads(spec.read_text()) != job:
        raise ValueError("exact controller job spec required")
    inputs = json.loads((folder / "inputs.json").read_text())
    membership = json.loads((folder / "membership.json").read_text())
    base, wider = _case_priors(root, job)
    if (
        inputs.get("files") != pins
        or inputs.get("source_files") != frozen
        or inputs.get("base_prior") != base
        or inputs.get("wider_prior") != wider
        or inputs.get("comparison_review") != COMPARISON_REVIEW
        or inputs.get("confirmation_outcomes_parsed") is not False
        or inputs.get("reserved_outcomes") != "sealed"
        or membership.get("training") != [lane.record_ids[int(i)] for i in ids]
        or membership.get("omitted") != job["omitted_record_ids"]
        or membership.get("excluded") != job["excluded_record_ids"]
        or membership.get("support") != job["support"]
        or membership.get("target") != lane.target
        or membership.get("distance_mode") != job["distance_mode"]
        or membership.get("prediction_scope") != "conditional_fitted_events_and_new_event_curves"
    ):
        raise ValueError("complete frozen native-input and exact masked cohort proof required")
    result = json.loads((folder / "result.json").read_text())
    if (
        result.get("job") != job
        or result.get("status") != "computed_pending_scientific_review"
        or result.get("code_and_config") != pins
        or result.get("posterior") != str(raw.relative_to(root))
        or result.get("posterior_sha256") != sha256(raw)
        or result.get("records") != len(ids)
        or result.get("events") != len({lane.event_ids[int(i)] for i in ids})
        or result.get("confirmation_outcomes_parsed") is not False
        or result.get("reserved_outcomes") != "sealed"
        or result.get("scoring_or_forecast_imputation") is not False
        or result.get("summary") != "summary.json"
        or result.get("summary_sha256") != sha256(folder / "summary.json")
    ):
        raise ValueError("complete valid source-bound fit result and retained raw hash required")
    process = json.loads(supervisor.read_text())
    if (
        process.get("returncode") != 0
        or process.get("reason") != "worker_exit"
        or process.get("charged_slots") != 1
        or process.get("start_markers") != 1
        or process.get("job_sha256") != sha256(spec)
        or process.get("plan_sha256") != sha256(root / OUTPUT / "plan.json")
        or process.get("monitor_failures")
    ):
        raise ValueError("successful single-call process and controller-plan proof required")
    with xr.open_datatree(raw, engine="h5netcdf") as tree:
        observed = tree["observed_data"].to_dataset()
        if (
            observed.record.values.tolist() != [lane.record_ids[int(i)] for i in ids]
            or observed.attrs.get("target") != lane.target
            or observed.attrs.get("scope") != "literal_case_training_only"
        ):
            raise ValueError("literal raw observed record order required")
        for name, values in [
            ("response", lane.response),
            ("native_minutes", lane.y),
            ("distance_km", lane.distance_km),
            ("reference_minutes", lane.reference_minutes),
        ]:
            np.testing.assert_array_equal(observed[name].values, values[ids])
        for name, values in [
            ("event_id", lane.event_ids),
            ("sequence", lane.sequences),
            ("site_id", lane.site_ids),
        ]:
            if observed[name].values.tolist() != [values[int(i)] for i in ids]:
                raise ValueError("literal raw observed event/sequence/site IDs required")
        posterior = tree["posterior"].to_dataset()
        if (
            posterior.sizes.get("chain") != 4
            or posterior.sizes.get("draw") != 2000
            or "nutpie" not in str(posterior.attrs).lower()
        ):
            raise ValueError("original four-chain2000draw nutpie population posterior required")
        diagnostics, table = sampling_diagnostics(tree)
        if (
            not diagnostics.get("screen_passed")
            or diagnostics != result.get("diagnostics")
            or diagnostics != json.loads((folder / "diagnostics.json").read_text())
            or (folder / "sampling-diagnostics.csv").read_text() != table.to_csv(na_rep="unknown")
        ):
            raise ValueError("replayed complete population diagnostics required")
        summary = summarize_posterior(
            lane, job["kind"], posterior, indices=ids, seed=job["seed"] + 1, draws=800
        )
    if not _summary_valid(summary) or summary != json.loads((folder / "summary.json").read_text()):
        raise ValueError("replayed finite same-cohort posterior summary required")
    for group in ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]:
        rows = csv_rows(summary[group])
        columns = list(dict.fromkeys(key for row in rows for key in row))
        expected = [{key: row.get(key, "") for key in columns} for row in rows]
        expected.sort(key=lambda row: tuple(row[key] for key in columns))
        if read_rows(folder / (group.replace("_", "-") + ".csv")) != expected:
            raise ValueError("summary CSV and canonical seeded summary differ")
    paths = {p for p in folder.rglob("*") if p.is_file() and p != manifest} | set(mandatory)
    files = {str(path.relative_to(root)): sha256(path) for path in paths}
    if accepted is not None and (
        accepted.get("charged_slots") != 1
        or accepted.get("files") != files
        or accepted.get("receipt") != str(manifest.relative_to(root))
        or not manifest.is_file()
        or accepted.get("receipt_sha256") != sha256(manifest)
        or json.loads(manifest.read_text()) != {"case_id": job["id"], "files": files}
    ):
        raise ValueError("complete immutable accepted sensitivity attempt receipt required")
    if any(sha256(root / name) != digest for name, digest in initial_files.items()):
        raise ValueError("sensitivity fit artifact changed during verification")
    _unchanged(root, pins)
    return files, manifest
