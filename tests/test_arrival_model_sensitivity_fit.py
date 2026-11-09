"""Temporary synthetic admission and patched sampler checks; no posterior fit."""

# pyright: basic
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pymc as pm
import pytest
import xarray as xr

from analysis.arrival import model_sensitivity_fit as worker
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_sensitivity_design import build_sensitivity_design
from tests.test_arrival_model_sensitivity_design import synthetic_inputs


def fixture(root, monkeypatch, *, failure=None):
    lanes, metadata = synthetic_inputs()
    design = build_sensitivity_design(lanes, metadata)
    jobs = worker.sensitivity_jobs(design)
    for name in worker.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source")
    (root / "native.csv").write_text("synthetic only; loader is patched")
    contract = {"inputs": {"native.csv": sha256(root / "native.csv")}}
    (root / worker.CONTRACT).write_text(
        '[inputs]\n"native.csv" = "' + contract["inputs"]["native.csv"] + '"\n'
    )
    write_json(
        root / worker.CV_REVIEW,
        {
            "status": "accepted_all_curvature_sequence_computations",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {"native.csv": sha256(root / "native.csv")},
        },
    )
    write_json(
        root / worker.COMPARISON_REVIEW,
        {
            "status": "accepted_curvature_sequence_predictive_comparison",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {worker.CV_REVIEW: sha256(root / worker.CV_REVIEW)},
        },
    )
    gate = {
        "status": "accepted_exploration_sensitivity_design",
        "independent_checker": True,
        "max_sampler_call_slots": 110,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "prior_predictions_reviewed": True,
        "comparison_reviewed": True,
        "comparison_review": worker.COMPARISON_REVIEW,
        "path_bindings": {"output": worker.OUTPUT, "store": worker.STORE},
        "jobs": jobs,
        "files": {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()},
    }
    write_json(root / worker.GATE, gate)
    calls, loads = [], []
    original_import = worker.importlib.import_module
    source_io = SimpleNamespace(
        required_sensitivity_paths=lambda: [],
        verify_sensitivity_inputs=lambda *a: loads.append("source_preflight"),
        load_sensitivity_inputs=lambda *a: metadata,
    )
    monkeypatch.setattr(
        worker.importlib,
        "import_module",
        lambda name, *a, **kw: (
            source_io
            if name == "analysis.arrival.model_sensitivity_inputs"
            else original_import(name, *a, **kw)
        ),
    )
    monkeypatch.setattr(
        worker, "load_lanes", lambda *a: loads.append("native_load") or (lanes, contract)
    )
    prior = {"alpha_sd": 0.5, "beta_sd": 0.25, "tau_sd": 0.4, "sigma_sd": 0.4}
    monkeypatch.setattr(worker, "read_prior", lambda *a: prior)
    monkeypatch.setattr(worker, "read_curvature_prior", lambda *a: {**prior, "gamma_sd": 0.5})

    def build(lane, kind, base, variant, *, wider_prior, indices):
        assert [lane.record_ids[int(i)] for i in indices] == jobs[current[0]]["training_record_ids"]
        return pm.Model(coords={"record": [lane.record_ids[int(i)] for i in indices]})

    current = [0]
    monkeypatch.setattr(worker, "build_sensitivity_model", build)

    def sample(**kwargs):
        job = jobs[current[0]]
        folder, raw = paths(root, job)
        assert json.loads((folder / "sampling-start.json").read_text()) == job
        assert (folder / "inputs.json").is_file() and (folder / "membership.json").is_file()
        assert raw.exists() and raw.stat().st_size == 0
        assert kwargs == {
            "draws": 2000,
            "tune": 1000,
            "chains": 4,
            "cores": 2,
            "target_accept": 0.95,
            "nuts_sampler": "nutpie",
            "random_seed": job["seed"],
            "progressbar": False,
        }
        calls.append(job)
        names = ["alpha"] + ([] if job["kind"] == "pooled" else ["beta"])
        if job["kind"] == "mean-curvature":
            names.append("gamma")
        if job["kind"] in {"event", "distance-scale", "mean-curvature"}:
            names.append("tau_event")
        values: dict[str, Any] = {
            name: (("chain", "draw"), np.full((4, 2000), 0.1)) for name in names
        }
        if job["target"] == "NCEI-native-duration":
            values["sigma_anchor"] = (
                ("chain", "draw", "scale_anchor_km"),
                np.full((4, 2000, 3), 0.3),
            )
        else:
            values["sigma"] = (("chain", "draw"), np.full((4, 2000), 0.3))
        post = xr.Dataset(
            values,
            coords={
                "chain": range(4),
                "draw": range(2000),
                **(
                    {"scale_anchor_km": [500, 2000, 5000]}
                    if job["target"] == "NCEI-native-duration"
                    else {}
                ),
            },
            attrs={"inference_library": "other" if failure == "backend" else "nutpie"},
        )
        if failure == "posterior_nonfinite":
            post["alpha"].values[0, 0] = np.nan
        if failure == "source":
            (root / "native.csv").write_text("changed after sampler start")
        return xr.DataTree.from_dict({"posterior": post})

    monkeypatch.setattr(worker.pm, "sample", sample)

    def diagnostics(tree):
        _, raw = paths(root, jobs[current[0]])
        assert raw.stat().st_size > 0
        with xr.open_datatree(raw, engine="h5netcdf") as saved:
            assert "observed_data" in saved.children
        return {
            "screen_passed": failure != "diagnostics",
            "finite_diagnostics": True,
        }, pd.DataFrame(
            {"r_hat": [1.0], "ess_bulk": [2000], "ess_tail": [2000], "mcse_mean": [0.001]},
            index=["alpha"],
        )

    monkeypatch.setattr(worker, "sampling_diagnostics", diagnostics)
    if failure == "summary_exception":

        def failed_summary(*a, **kw):
            assert paths(root, jobs[current[0]])[1].stat().st_size > 0
            raise RuntimeError("synthetic downstream failure after raw save")

        monkeypatch.setattr(worker, "summarize_posterior", failed_summary)
    elif failure == "summary_nonfinite":
        real_summary = worker.summarize_posterior

        def nonfinite_summary(*a, **kw):
            result = real_summary(*a, **kw)
            result["nonfinite_values"]["conditional_measure"] = 1
            return result

        monkeypatch.setattr(worker, "summarize_posterior", nonfinite_summary)
    return jobs, gate, calls, loads, current


def paths(root, job):
    return root / worker.OUTPUT / "jobs" / job["id"], root / worker.STORE / (job["id"] + ".nc")


def test_jobs_have_exact55_orders_seeds_and_no_hidden_extra_calls():
    lanes, inputs = synthetic_inputs()
    design = build_sensitivity_design(lanes, inputs)
    before = deepcopy(design)
    jobs = worker.sensitivity_jobs(design)
    assert design == before
    assert len(jobs) == 55 and len({j["id"] for j in jobs}) == 55
    assert [j["seed"] for j in jobs] == [2886110800 + 1000 * j for j in range(55)]
    assert all((j["draws"], j["tune"], j["cores"]) == (2000, 1000, 2) for j in jobs)


@pytest.mark.parametrize(
    "change", ["comparison", "comparison_closure", "cv", "prior", "jobs", "native", "paths"]
)
def test_future_gate_gaps_block_every_native_loader_and_sampler(tmp_path, monkeypatch, change):
    jobs, gate, calls, loads, _ = fixture(tmp_path, monkeypatch)
    if change == "comparison":
        gate["comparison_reviewed"] = False
    elif change == "comparison_closure":
        gate["files"].pop(worker.CV_REVIEW)
    elif change == "cv":
        value = json.loads((tmp_path / worker.CV_REVIEW).read_text())
        value["status"] = "pending"
        write_json(tmp_path / worker.CV_REVIEW, value)
        gate["files"][worker.CV_REVIEW] = sha256(tmp_path / worker.CV_REVIEW)
    elif change == "prior":
        gate["prior_predictions_reviewed"] = False
    elif change == "jobs":
        gate["jobs"][0]["seed"] += 1
    elif change == "native":
        gate["files"].pop("native.csv")
    else:
        gate["path_bindings"]["store"] = "alternate"
    write_json(tmp_path / worker.GATE, gate)
    with pytest.raises(ValueError):
        worker.fit_sensitivity_job(tmp_path, jobs[0], *paths(tmp_path, jobs[0]))
    assert calls == [] and "native_load" not in loads


def test_missing_gate_and_wrong_or_symlink_paths_never_load_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "load_lanes", lambda *a: pytest.fail("outcomes loaded"))
    job = {"id": "ms5-test"}
    with pytest.raises(ValueError, match="accepted exploration"):
        worker.fit_sensitivity_job(tmp_path, job, *paths(tmp_path, job))
    with pytest.raises(ValueError, match="canonical"):
        worker.fit_sensitivity_job(tmp_path, job, tmp_path / "copied", paths(tmp_path, job)[1])
    folder, raw = paths(tmp_path, job)
    folder.parent.mkdir(parents=True)
    folder.symlink_to(tmp_path / "uncreated")
    with pytest.raises(ValueError, match="nonsymlink"):
        worker.fit_sensitivity_job(tmp_path, job, folder, raw)


def test_success_saves_original_raw_observations_and_never_overwrites(tmp_path, monkeypatch):
    jobs, _, calls, loads, _ = fixture(tmp_path, monkeypatch)
    job = jobs[0]
    folder, raw = paths(tmp_path, job)
    result = worker.fit_sensitivity_job(tmp_path, job, folder, raw)
    assert result["status"] == "computed_pending_scientific_review"
    assert len(calls) == 1 and loads.index("source_preflight") < loads.index("native_load")
    with xr.open_datatree(raw, engine="h5netcdf") as saved:
        assert saved["observed_data"].record.values.tolist() == job["training_record_ids"]
        assert not any("event_effect" in str(name) for name in saved["posterior"].data_vars)
    before = raw.read_bytes()
    with pytest.raises(ValueError, match="never overwrite"):
        worker.fit_sensitivity_job(tmp_path, job, folder, raw)
    assert raw.read_bytes() == before and len(calls) == 1


@pytest.mark.parametrize(
    "failure,status",
    [
        ("backend", "backend_failure"),
        ("diagnostics", "diagnostic_failure"),
        ("posterior_nonfinite", "sampling_or_evaluation_failure"),
        ("summary_exception", "sampling_or_evaluation_failure"),
        ("summary_nonfinite", "summary_nonfinite_failure"),
        ("source", "source_identity_failure"),
    ],
)
def test_failed_assessment_keeps_first_raw_bytes_diagnostics_and_result(
    tmp_path, monkeypatch, failure, status
):
    jobs, _, calls, _, _ = fixture(tmp_path, monkeypatch, failure=failure)
    folder, raw = paths(tmp_path, jobs[0])
    result = worker.fit_sensitivity_job(tmp_path, jobs[0], folder, raw)
    assert result["status"] == status and len(calls) == 1 and raw.stat().st_size > 0
    assert result["posterior_sha256"] == sha256(raw)
    assert (folder / "sampling-diagnostics.csv").is_file()
    assert json.loads((folder / "result.json").read_text())["status"] == status


def test_publisher_case_uses_exact_recomputed_distance_reference_and_mask(tmp_path, monkeypatch):
    jobs, _, calls, _, current = fixture(tmp_path, monkeypatch)
    current[0] = next(j for j, job in enumerate(jobs) if job["scenario"] == "publisher-distance")
    job = jobs[current[0]]
    folder, raw = paths(tmp_path, job)
    result = worker.fit_sensitivity_job(tmp_path, job, folder, raw)
    assert result["status"] == "computed_pending_scientific_review" and len(calls) == 1
    lanes, metadata = synthetic_inputs()
    ids = [lanes[job["target"]].record_ids.index(record) for record in job["training_record_ids"]]
    with xr.open_datatree(raw, engine="h5netcdf") as saved:
        observed = saved["observed_data"].to_dataset()
        np.testing.assert_array_equal(
            observed.distance_km.values, metadata.publisher_distance_km[ids]
        )
        np.testing.assert_array_equal(observed.native_minutes.values, lanes[job["target"]].y[ids])


@pytest.mark.parametrize("variant", ["t4_matched", "power_0.5", "power_1.5"])
def test_controller_artifact_verifier_replays_raw_diagnostics_summary_and_full_id_receipt(
    tmp_path, monkeypatch, variant
):
    jobs, _, _, _, current = fixture(tmp_path, monkeypatch)
    current[0] = next(
        j
        for j, job in enumerate(jobs)
        if job["kind"] == "mean-curvature" and job["prior_variant"] == variant
    )
    job = jobs[current[0]]
    folder, raw = paths(tmp_path, job)
    result = worker.fit_sensitivity_job(tmp_path, job, folder, raw)
    pins = result["code_and_config"]
    write_json(tmp_path / worker.OUTPUT / "plan.json", {"jobs": jobs, "files": pins})
    spec = folder.with_name(job["id"] + "-spec.json")
    write_json(spec, job)
    folder.with_name(folder.name + ".log").write_text("patched sampler; no MCMC")
    assert folder.with_name(folder.name + ".log").name == job["id"] + ".log"
    assert folder.with_name(folder.name + ".supervisor.json").name == job["id"] + ".supervisor.json"
    write_json(
        folder.with_name(folder.name + ".supervisor.json"),
        {
            "returncode": 0,
            "reason": "worker_exit",
            "charged_slots": 1,
            "start_markers": 1,
            "job_sha256": sha256(spec),
            "plan_sha256": sha256(tmp_path / worker.OUTPUT / "plan.json"),
            "monitor_failures": [],
        },
    )
    files, receipt = worker.case_artifacts(tmp_path, job, pins)
    write_json(receipt, {"case_id": job["id"], "files": files})
    accepted = {
        "charged_slots": 1,
        "files": files,
        "receipt": str(receipt.relative_to(tmp_path)),
        "receipt_sha256": sha256(receipt),
    }
    assert worker.case_artifacts(tmp_path, job, pins, accepted)[0] == files
    (folder / "curves.csv").write_text("corrupt table")
    with pytest.raises(ValueError, match="summary CSV"):
        worker.case_artifacts(tmp_path, job, pins, accepted)


def test_decimal_ids_have_distinct_full_process_names():
    lanes, inputs = synthetic_inputs()
    jobs = worker.sensitivity_jobs(build_sensitivity_design(lanes, inputs))
    selected = [
        job
        for job in jobs
        if job["kind"] == "mean-curvature" and job["prior_variant"] in {"power_0.5", "power_1.5"}
    ]
    folders = [paths(Path("/synthetic-project"), job)[0] for job in selected]
    logs = [folder.with_name(folder.name + ".log").name for folder in folders]
    assert len(logs) == len(set(logs)) == 2
    assert all(job["id"] + ".log" in logs for job in selected)


@pytest.mark.parametrize("scenario,count", [("omit-lata-only", 1063), ("component-assessed", 1050)])
def test_case_masks_preserve_exact_omission_and_original_exclusion_bookkeeping(
    tmp_path, monkeypatch, scenario, count
):
    jobs, _, _, _, current = fixture(tmp_path, monkeypatch)
    current[0] = next(
        j
        for j, job in enumerate(jobs)
        if job["kind"] == "mean-curvature" and job["scenario"] == scenario
    )
    job = jobs[current[0]]
    folder, raw = paths(tmp_path, job)
    result = worker.fit_sensitivity_job(tmp_path, job, folder, raw)
    assert result["status"] == "computed_pending_scientific_review" and result["records"] == count
    membership = json.loads((folder / "membership.json").read_text())
    assert membership["training"] == job["training_record_ids"]
    assert len(membership["omitted"]) == 1064 - count and len(membership["excluded"]) == 6


def test_gate_cohort_edit_cannot_replace_trusted_source_design_before_sampling(
    tmp_path, monkeypatch
):
    jobs, gate, calls, _, _ = fixture(tmp_path, monkeypatch)
    gate["jobs"][0]["training_record_ids"].pop()
    write_json(tmp_path / worker.GATE, gate)
    with pytest.raises(ValueError, match="reproduce all55exact"):
        worker.fit_sensitivity_job(tmp_path, jobs[0], *paths(tmp_path, jobs[0]))
    assert calls == [] and not paths(tmp_path, jobs[0])[1].exists()
