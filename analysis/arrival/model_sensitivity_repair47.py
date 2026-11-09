"""One final same-model repair of original case47; no third attempt or data change."""

# pyright: basic
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from analysis.arrival import model_sensitivity_numerical_fit as kernel
from analysis.arrival.evidence import sha256, write_json

fit, source, np, xr, re = kernel.fit, kernel.source, kernel.np, kernel.xr, kernel.re
_require = kernel._require
_case, _metadata, _observed = kernel._case, kernel._metadata, kernel._observed
_population, _inventory = kernel._population, kernel._inventory
TABLES, LEAVES, PLAN = kernel.TABLES, kernel.LEAVES, kernel.PLAN
RUN_ID = "finish-sensitivities-v1"
CONTROL = fit.OUTPUT + "/" + RUN_ID
GATE = str(Path(fit.GATE).parent) + "/" + RUN_ID + "/review-acceptance.json"
SELF, CLI, TEST = (
    "analysis/arrival/model_sensitivity_repair47.py",
    "scripts/fit_arrival_sensitivity_repair47.py",
    "tests/test_arrival_model_sensitivity_repair47.py",
)
RUNNER, RUNNER_TEST = (
    "scripts/run_arrival_sensitivity_finish.py",
    "tests/test_run_arrival_sensitivity_finish.py",
)
PROTOCOL = dict(
    draws=2000, tune=4000, chains=4, cores=2, target_accept=0.999, nuts_sampler="nutpie"
)
ORIGINAL_ID = "ms5-ncei-mean-curvature-base-era-2014plus"
CONSUMED = tuple(sorted(set(kernel.CONSUMED) | {SELF, CLI, TEST, RUNNER, RUNNER_TEST}))


def repair_job(original):
    _require(
        original.get("id") == ORIGINAL_ID
        and original.get("order") == 47
        and original.get("kind") == "mean-curvature"
        and original.get("target") == "NCEI-native-duration"
        and original.get("prior_variant") == "base"
        and original.get("seed") == 2886157800,
        "only original base-curvature case47 with unchanged seed may be repaired",
    )
    return kernel.execution_jobs([original], kernel.RUN_ID, {original["id"]: 2}, PROTOCOL)[0]


def case_paths(root, job):
    _require(
        job == repair_job(job.get("original_job", {})), "one exact case47 final repair required"
    )
    return kernel.case_paths(root, job)  # Pure native-path validation; never oldGate admission.


def preflight(root):
    root = root.resolve()
    gate = json.loads(source._path(root, GATE).read_text())
    _require(
        gate.get("status") == "accepted_sensitivity_case47_repair_and_final_seven_execution"
        and gate.get("independent_checker") is True
        and gate.get("run_id") == RUN_ID
        and gate.get("confirmation_outcomes_parsed") is False
        and gate.get("reserved_outcomes") == "sealed"
        and set(CONSUMED) <= set(gate.get("files", {}))
        and "context/runs/arrival-model-fitting-v1/sensitivity-state.json" not in gate["files"],
        "complete genuine50 source authority required before native/model readers",
    )
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    source._unchanged(root, pins)
    return gate, pins


def _authority(root):
    return importlib.import_module("scripts.run_arrival_sensitivity_finish").verify_gate(root)


def verify_gate(root):
    gate, pins = preflight(root)
    admission = _authority(root)
    _require(
        admission["gate"] == gate and admission["initial_files"] == pins,
        "worker and finish controller must admit identical genuine50 source authority",
    )
    job = repair_job(admission["original_admission"]["gate"]["jobs"][47])
    _require(
        admission["repair_job"] == job and job in admission["jobs"],
        "exact one approved final repair required",
    )
    return {**admission, "files": pins, "gate_path": GATE}


def fit_repair(root: Path, job: dict[str, Any], output: Path, store: Path) -> dict[str, Any]:
    root = root.resolve()
    admission = verify_gate(root)
    _require(
        (output, store) == case_paths(root, job)
        and all(not p.exists() and p.resolve() == p for p in [output, store]),
        "new literal numerical paths required; never overwrite/retry",
    )
    _require(job == admission["repair_job"], "repair47 only; tail jobs use their old worker")
    lane, ids, frozen, base, model = _case(root, job, admission)
    inputs, membership = _metadata(job, admission, lane, ids, frozen, base)
    source._unchanged(root, admission["files"])
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("xb"):
        pass
    for name, value in [
        ("job.json", job),
        ("inputs.json", inputs),
        ("membership.json", membership),
    ]:
        write_json(output / name, value)
    result: dict[str, Any] = dict(
        job=job,
        original_job=job["original_job"],
        posterior=str(store.relative_to(root)),
        records=len(ids),
        events=len(set(np.asarray(lane.event_ids)[ids])),
        code_and_config=admission["files"],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scoring_or_forecast_imputation=False,
    )
    try:
        write_json(output / "sampling-start.json", job)
        with model:
            tree = fit.pm.sample(
                **{k: v for k, v in job["sampler"].items() if k != "seed"},
                random_seed=job["sampler"]["seed"],
                progressbar=False,
            )
        tree["observed_data"] = xr.DataTree(_observed(lane, ids))
        tree.to_netcdf(store, engine="h5netcdf")
        result["posterior_sha256"] = sha256(store)
        post = _population(tree, job)
        diagnostics, table = fit.sampling_diagnostics(tree)
        write_json(output / "diagnostics.json", diagnostics)
        table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
        result["diagnostics"] = diagnostics
        result["status"] = "diagnostic_failure"
        if diagnostics.get("screen_passed") is True:
            summary = fit.summarize_posterior(
                lane,
                job["original_job"]["kind"],
                post,
                indices=ids,
                seed=job["original_job"]["seed"] + 1,
                draws=800,
            )
            write_json(output / "summary.json", summary)
            for group in TABLES:
                fit.write_table(output / (group.replace("_", "-") + ".csv"), summary[group])
            result.update(
                summary="summary.json",
                summary_sha256=sha256(output / "summary.json"),
                status="computed_pending_scientific_review"
                if fit._summary_valid(summary)
                else "summary_nonfinite_failure",
            )
        tree.close()
        source._unchanged(root, admission["files"])
    except Exception as error:
        result.update(
            status="sampling_or_evaluation_failure",
            error_type=type(error).__name__,
            error=str(error),
        )
        if store.exists() and store.stat().st_size:
            result["posterior_sha256"] = sha256(store)
    write_json(output / "result.json", result)
    return result


def case_artifacts(root, job, pins, accepted=None) -> dict[str, Any]:
    root = root.resolve()
    admission = verify_gate(root)
    _require(pins == admission["files"], "identical full numerical admission required")
    _require(job == admission["repair_job"], "repair47 only; no tail admission through new worker")
    lane, ids, frozen, base, _ = _case(root, job, admission)
    folder, raw = case_paths(root, job)
    manifest = folder / "attempt-evidence.json"
    mandatory = {
        folder / n
        for n in [*LEAVES, "summary.json", *[g.replace("_", "-") + ".csv" for g in TABLES]]
    } | {
        raw,
        *(folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]),
    }
    _require(
        all(p.is_file() and p.resolve() == p for p in mandatory),
        "complete literal numerical worker/raw/process evidence required",
    )
    initial = _inventory(root, folder, raw)
    _require(
        set(initial) == {str(p.relative_to(root)) for p in mandatory},
        "no unknown numerical files allowed",
    )
    for p in [
        folder / "job.json",
        folder / "sampling-start.json",
        folder.with_name(folder.name + "-spec.json"),
    ]:
        _require(json.loads(p.read_text()) == job, "exact execution/start/spec required")
    inputs, membership = _metadata(job, admission, lane, ids, frozen, base)
    _require(
        json.loads((folder / "inputs.json").read_text()) == inputs
        and json.loads((folder / "membership.json").read_text()) == membership,
        "unchanged original input/cohort proof required",
    )
    result = json.loads((folder / "result.json").read_text())
    process = json.loads(folder.with_name(folder.name + ".supervisor.json").read_text())
    expected = dict(
        job=job,
        original_job=job["original_job"],
        posterior=str(raw.relative_to(root)),
        posterior_sha256=sha256(raw),
        records=len(ids),
        events=len(set(np.asarray(lane.event_ids)[ids])),
        code_and_config=pins,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scoring_or_forecast_imputation=False,
        status="computed_pending_scientific_review",
        summary="summary.json",
        summary_sha256=sha256(folder / "summary.json"),
    )
    _require(
        all(result.get(k) == v for k, v in expected.items()),
        "successful exact original-model result/raw/summary binding required",
    )
    expected_process = dict(
        returncode=0,
        reason="worker_exit",
        charged_slots=1,
        start_markers=1,
        job_sha256=sha256(folder.with_name(folder.name + "-spec.json")),
        plan_sha256=pins[PLAN],
        numerical_gate_sha256=pins[GATE],
        execution_authority_gate_sha256=pins[GATE],
    )
    _require(
        all(process.get(k) == v for k, v in expected_process.items())
        and not process.get("monitor_failures")
        and re.fullmatch(r"[0-9a-f]{40}", process.get("invocation_git_sha", "")) is not None,
        "single successful source-bound numerical process required",
    )
    with xr.open_datatree(raw, engine="h5netcdf") as tree:
        actual = tree["observed_data"].to_dataset()
        expected_obs = _observed(lane, ids)
        _require(
            actual.identical(expected_obs),
            "literal observed identities and native numeric arrays required",
        )
        post = _population(tree, job)
        diagnostics, table = fit.sampling_diagnostics(tree)
        _require(
            diagnostics.get("screen_passed") is True
            and diagnostics
            == result.get("diagnostics")
            == json.loads((folder / "diagnostics.json").read_text())
            and (folder / "sampling-diagnostics.csv").read_text() == table.to_csv(na_rep="unknown"),
            "complete raw diagnostics must replay",
        )
        summary = fit.summarize_posterior(
            lane,
            job["original_job"]["kind"],
            post,
            indices=ids,
            seed=job["original_job"]["seed"] + 1,
            draws=800,
        )
    _require(
        fit._summary_valid(summary)
        and summary == json.loads((folder / "summary.json").read_text()),
        "original seed+1/800 summary must replay",
    )
    for group in TABLES:
        rows = fit.csv_rows(summary[group])
        columns = list(dict.fromkeys(k for row in rows for k in row))
        expected_rows = sorted(
            [{k: row.get(k, "") for k in columns} for row in rows],
            key=lambda row: tuple(row[k] for k in columns),
        )
        _require(
            fit.read_rows(folder / (group.replace("_", "-") + ".csv")) == expected_rows,
            "all five summary CSVs must replay",
        )
    _require(_inventory(root, folder, raw) == initial, "numerical artifacts changed during replay")
    if accepted is not None:
        _require(
            accepted.get("case_id") == job["original_job"]["id"]
            and accepted.get("charged_slots") == 1
            and accepted.get("files") == initial
            and accepted.get("receipt") == str(manifest.relative_to(root))
            and accepted.get("receipt_sha256")
            == sha256(source._path(root, str(manifest.relative_to(root))))
            and json.loads(manifest.read_text())
            == {"case_id": job["original_job"]["id"], "files": initial},
            "complete immutable accepted numerical receipt required",
        )
    source._unchanged(root, pins)
    return dict(
        files=initial, manifest=manifest, result=result, posterior=raw, posterior_sha256=sha256(raw)
    )
