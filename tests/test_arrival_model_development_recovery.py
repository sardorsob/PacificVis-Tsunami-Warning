"""Pure/gated synthetic full-design smokes; no historical Y/posterior or sampler."""

# pyright: basic
import json
from dataclasses import replace

import numpy as np
import pymc as pm
import pytensor.tensor as pt
import pytest
import xarray as xr

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival import model_development_recovery as recovery
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_data import lane_arrays
from analysis.arrival.model_sensitivity_priors import (
    _population_spec,
    _prior_settings,
    build_sensitivity_model,
)
from tests.test_arrival_model_development_fit import fixture as fit_fixture
from tests.test_arrival_model_development_references import damage_native_metadata, native_metadata

FORMS = [
    ("NCEI-native-duration", "distance-scale"),
    ("NCEI-native-duration", "mean-curvature"),
    *[(target, kind) for target in ["T-OBS", "T-CAL"] for kind in ["pooled", "distance", "event"]],
]


def small_lane(target):
    rows = [
        dict(
            record_id=f"record-{i:02d}",
            event_id=f"event-{i % 3}",
            physical_site_id=f"site-{i}",
            target=target,
            distance_km=str([20, 100, 500, 1000, 2000, 5000, 10000, 20000][i % 8]),
            target_minutes=str((-1 if i % 2 else 1) * 20 if target == "T-CAL" else 20 + i),
        )
        for i in range(12)
    ]
    return lane_arrays(
        target, rows, {f"event-{i}": f"seq-{i}" for i in range(3)}, {f"event-{i}" for i in range(3)}
    )


def posterior(target, kind, truth, *, perturb=False):
    variables = {}
    for name, (_, shape) in _population_spec(target, kind).items():
        value = np.broadcast_to(truth[name], (4, 2000, *shape)).copy().astype(float)
        if perturb:
            for chain in range(4):
                value[chain] = (
                    value[chain] * (1 + 0.01 * chain)
                    if name in {"sigma", "sigma_anchor", "tau_event"}
                    else value[chain] + 0.01 * chain
                )
        variables[name] = (
            ("chain", "draw", "scale_anchor_km") if shape else ("chain", "draw"),
            value,
        )
    post = xr.Dataset(
        variables,
        coords={"chain": np.arange(4), "draw": np.arange(2000)},
        attrs={"inference_library": "nutpie"},
    )
    return (
        post.assign_coords(scale_anchor_km=[500, 2000, 5000])
        if target == "NCEI-native-duration"
        else post
    )


@pytest.mark.parametrize("target,kind", FORMS)
def test_all_truths_simulate_independently_of_every_historical_response(target, kind):
    lane = small_lane(target)
    changed = replace(
        lane,
        y=lane.y * 123 + 5,
        response=lane.response + 999,
        rows=tuple(
            {**row, "target_minutes": "999999", "unneeded_outcome": "different"}
            for row in lane.rows
        ),
    )
    for case in ["A", "B"]:
        truth = recovery._truth(target, kind, case)
        assert set(truth) == set(_population_spec(target, kind))
        left, effects = recovery.simulate(lane, kind, truth, 123)
        right, other = recovery.simulate(changed, kind, truth, 123)
        np.testing.assert_array_equal(left.response, right.response)
        np.testing.assert_array_equal(left.y, right.y)
        assert effects == other and recovery._design_sha(lane) == recovery._design_sha(changed)
        assert all("unneeded_outcome" not in row for row in right.rows)
        if target == "T-CAL":
            np.testing.assert_array_equal(left.y, left.response)
        else:
            np.testing.assert_allclose(
                np.log(left.y), left.response + np.log(left.reference_minutes)
            )


@pytest.mark.parametrize(
    "target,kind,variant",
    [(target, kind, "base") for target, kind in FORMS]
    + [
        ("NCEI-native-duration", "mean-curvature", "t4_matched"),
        ("T-OBS", "pooled", "power_0.5"),
        ("T-CAL", "event", "joint_wider"),
        ("NCEI-native-duration", "mean-curvature", "gamma_wider_only"),
    ],
)
def test_independent_dense_density_and_all_transformed_gradients(target, kind, variant):
    lane = small_lane(target)
    truth = recovery._truth(target, kind, "B")
    fake, _ = recovery.simulate(lane, kind, truth, 123)
    base = (
        dict(alpha_sd=30.0, beta_sd=15.0, tau_sd=30.0, sigma_sd=30.0)
        if target == "T-CAL"
        else dict(alpha_sd=0.5, beta_sd=0.25, tau_sd=0.4, sigma_sd=0.4)
    )
    if kind == "mean-curvature":
        base["gamma_sd"] = 0.5
    wider = {key: value * 2 for key, value in base.items()} if variant == "joint_wider" else None
    family, scales = _prior_settings(kind, base, variant, wider)
    model = build_sensitivity_model(
        fake, kind, base, variant, wider_prior=wider, indices=np.flatnonzero(fake.included)
    )
    result = recovery.numerical_oracles(
        model,
        fake,
        kind,
        truth,
        dict(family=family, distribution_scales=scales),
        posterior(target, kind, truth, perturb=True),
    )
    assert result["passed"] and len(result["points"]) == 4
    assert [row["point"] for row in result["prior_only_checks"][:2]] == [
        "truth",
        "fixed_prior_shift",
    ]
    assert all(row["logp_absolute_error"] <= 1e-6 for row in result["points"])
    assert all(row["logp_prior_offset_corrected_error"] <= 2e-7 for row in result["points"])
    if target == "T-CAL" and kind == "event" and variant == "base":
        assert result["selected_prior_scale_dtypes"]["alpha"] == "float32"
        assert (
            abs(
                result["prior_only_checks"][0]["offset"]
                - result["normal_log_scale_offset_prediction"]
            )
            < 1e-12
        )


def test_prior_only_offset_cannot_absorb_a_joint_likelihood_error():
    target, kind = "T-OBS", "pooled"
    truth = recovery._truth(target, kind, "A")
    fake, _ = recovery.simulate(small_lane(target), kind, truth, 123)
    base = dict(alpha_sd=0.5, beta_sd=0.25, tau_sd=0.4, sigma_sd=0.4)
    model = build_sensitivity_model(fake, kind, base, "base", indices=np.flatnonzero(fake.included))
    with model:
        pm.Potential("unexplained_joint_density_offset", pt.as_tensor_variable(0.01))
    family, scales = _prior_settings(kind, base, "base", None)
    result = recovery.numerical_oracles(
        model,
        fake,
        kind,
        truth,
        dict(family=family, distribution_scales=scales),
        posterior(target, kind, truth),
    )
    assert not result["passed"]
    assert all(row["logp_absolute_error"] > 0.009 for row in result["points"])


def fixture(root, monkeypatch, *, target="NCEI-native-duration", kind="mean-curvature"):
    fit_fixture(root, monkeypatch, target=target, kind=kind, role="full_development")
    freeze = json.loads((root / data.FREEZE).read_text())
    for name in recovery.CONSUMED:
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic recovery source")
    files = {
        str(path.relative_to(root)): sha256(path) for path in root.rglob("*") if path.is_file()
    }
    jobs = recovery.jobs(freeze)
    gate = dict(
        status="accepted_frozen_arrival_development_recovery_execution",
        independent_checker=True,
        specification_freeze=data.FREEZE,
        specification_freeze_sha256=files[data.FREEZE],
        completed_check=data.CHECK_REVIEW,
        completed_check_sha256=files[data.CHECK_REVIEW],
        reserved_outcomes="sealed",
        resources=fit.resources(),
        protocol=recovery.protocol(),
        max_sampler_call_slots=6,
        files=files,
        jobs=jobs,
    )
    write_json(root / recovery.GATE, gate)
    calls = []

    def sample(**kwargs):
        job = next(job for job in jobs if job["sampler_seed"] == kwargs["random_seed"])
        actual_target = job["model_key"].split(":")[0]
        actual_kind = job["model_key"].split(":")[1]
        output, raw = recovery.case_paths(root, job)
        assert raw.exists() and raw.stat().st_size == 0
        assert json.loads((output / "sampling-start.json").read_text()) == job
        assert kwargs == dict(
            draws=2000,
            tune=1000,
            chains=4,
            cores=2,
            target_accept=0.95,
            nuts_sampler="nutpie",
            random_seed=job["sampler_seed"],
            progressbar=False,
        )
        calls.append(kwargs)
        post = posterior(actual_target, actual_kind, job["truth"])
        post["alpha"] = post.alpha + 1  # Deliberately outside truth; no inclusion pass rule.
        stats = native_metadata(post)
        return xr.DataTree.from_dict({"posterior": post, "sample_stats": stats})

    monkeypatch.setattr(recovery.pm, "sample", sample)
    monkeypatch.setattr(recovery, "sampling_diagnostics", fit.sampling_diagnostics)
    monkeypatch.setattr(recovery, "numerical_oracles", lambda *args: {"passed": True, "points": []})
    summary_calls = []

    def summary(lane, actual_kind, post, *, indices, seed, draws):
        assert draws == 800 and seed in {job["conditional_seed"] for job in jobs}
        summary_calls.append(seed)
        return {name: [{"q50": float(post.alpha.values[0, 0])}] for name in recovery.TABLES}

    monkeypatch.setattr(recovery, "summarize_posterior", summary)
    monkeypatch.setattr(recovery, "_summary_valid", lambda value: True)
    return jobs, calls, summary_calls


@pytest.mark.parametrize("target,kind", FORMS)
def test_fixed_six_jobs_raw_first_and_semantic_replay(tmp_path, monkeypatch, target, kind):
    jobs, calls, summary_calls = fixture(tmp_path, monkeypatch, target=target, kind=kind)
    assert len(jobs) == 6 and [job["case"] for job in jobs] == ["A", "B"] * 3
    job = next(
        job
        for job in jobs
        if job["model_key"] == f"{target}:{kind}:selected" and job["case"] == "B"
    )
    output, raw = recovery.case_paths(tmp_path, job)
    result = recovery.run_recovery_job(tmp_path, job, output, raw)
    assert result["status"] == recovery.SUCCESS and result["calibration_or_coverage_claim"] is False
    assert len(calls) == 1 and summary_calls == [job["conditional_seed"]]
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
        assert observed.sizes["record"] == (
            1215 if target == "NCEI-native-duration" else 258 if target == "T-OBS" else 169
        )
    pins = recovery.verify_gate(tmp_path)["files"]
    inventory = recovery.case_artifacts(tmp_path, job, pins)
    assert inventory["posterior_sha256"] == sha256(raw)
    assert len(calls) == 1 and summary_calls == [job["conditional_seed"]] * 2
    truth_table = (output / "truth-quantiles.csv").read_text()
    assert "False" in truth_table  # A missed interval remains a successful computation smoke.


@pytest.mark.parametrize("failure", ["gate", "check", "truth", "seed", "protocol", "resources"])
def test_all_admission_failures_precede_design_read(tmp_path, monkeypatch, failure):
    jobs, calls, _ = fixture(tmp_path, monkeypatch)
    gate = json.loads((tmp_path / recovery.GATE).read_text())
    if failure == "gate":
        gate["status"] = "pending"
    elif failure == "check":
        gate["files"].pop(data.CHECK_REVIEW)
    elif failure == "truth":
        gate["jobs"][0]["truth"]["alpha"] = 999
    elif failure == "seed":
        gate["jobs"][0]["conditional_seed"] += 1
    elif failure == "protocol":
        gate["protocol"]["scope"] = "coverage"
    else:
        gate["resources"]["global_max_bytes"] = 1
    write_json(tmp_path / recovery.GATE, gate)
    monkeypatch.setattr(
        data, "load_full_development_lanes", lambda *a: pytest.fail("design read before gate")
    )
    output, raw = recovery.case_paths(tmp_path, jobs[0])
    with pytest.raises(ValueError):
        recovery.run_recovery_job(tmp_path, jobs[0], output, raw)
    assert calls == [] and not output.exists()


def test_unrepresentable_simulation_stops_without_clipping_or_reseed(monkeypatch):
    lane = small_lane("T-OBS")
    monkeypatch.setattr(
        recovery, "simulate_response", lambda *a, **k: (np.full(len(lane.rows), 1000.0), {})
    )
    with pytest.raises(ValueError, match="no clipping or reseed"):
        recovery.simulate(lane, "event", recovery._truth(lane.target, "event", "A"), 123)


@pytest.mark.parametrize(
    "corruption", ["inputs", "prior", "diagnostics", "summary", "csv", "oracle", "truth_table"]
)
def test_resealed_semantic_corruptions_rejected(tmp_path, monkeypatch, corruption):
    jobs, calls, _ = fixture(tmp_path, monkeypatch)
    job = jobs[0]
    output, raw = recovery.case_paths(tmp_path, job)
    assert recovery.run_recovery_job(tmp_path, job, output, raw)["status"] == recovery.SUCCESS
    if corruption == "inputs":
        value = json.loads((output / "inputs.json").read_text())
        value["files"] = dict(list(value["files"].items())[:1])
        write_json(output / "inputs.json", value)
    elif corruption == "prior":
        value = json.loads((output / "prior-settings.json").read_text())
        value["family"] = "changed"
        write_json(output / "prior-settings.json", value)
    elif corruption == "diagnostics":
        (output / "sampling-diagnostics.csv").write_text("r_hat\n99\n")
    elif corruption == "summary":
        value = json.loads((output / "summary.json").read_text())
        value["parameters"][0]["q50"] = 999
        write_json(output / "summary.json", value)
    elif corruption == "csv":
        (output / "parameters.csv").write_text("q50\n999\n")
    elif corruption == "oracle":
        write_json(output / "numerical-oracles.json", {"passed": True, "points": ["changed"]})
    else:
        (output / "truth-quantiles.csv").write_text("truth\n999\n")
    fit._manifest(output)
    with pytest.raises(ValueError):
        recovery.case_artifacts(tmp_path, job, recovery.verify_gate(tmp_path)["files"])
    assert len(calls) == 1


def test_raw_preserved_on_diagnostic_failure(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        recovery,
        "sampling_diagnostics",
        lambda tree: (_ for _ in ()).throw(ValueError("after save")),
    )
    output, raw = recovery.case_paths(tmp_path, jobs[0])
    result = recovery.run_recovery_job(tmp_path, jobs[0], output, raw)
    assert result["status"] == "needs_numerical_review" and result["posterior_sha256"] == sha256(
        raw
    )
    assert len(calls) == 1 and raw.stat().st_size > 0


@pytest.mark.parametrize("fault", ["backend_note", "settings"])
def test_invalid_native_smoke_is_saved_before_rejection_without_summary(
    tmp_path, monkeypatch, fault
):
    jobs, calls, summary_calls = fixture(tmp_path, monkeypatch)
    sample = recovery.pm.sample

    def wrong_sample(**kwargs):
        tree = sample(**kwargs)
        post, stats = tree["posterior"].to_dataset(), tree["sample_stats"].to_dataset()
        damage_native_metadata(post, stats, fault)
        tree["posterior"], tree["sample_stats"] = xr.DataTree(post), xr.DataTree(stats)
        return tree

    monkeypatch.setattr(recovery.pm, "sample", wrong_sample)
    output, raw = recovery.case_paths(tmp_path, jobs[0])
    result = recovery.run_recovery_job(tmp_path, jobs[0], output, raw)
    assert result["status"] == "needs_numerical_review"
    assert raw.stat().st_size > 0 and result["posterior_sha256"] == sha256(raw)
    assert len(calls) == 1 and summary_calls == []
    assert not (output / "diagnostics.json").exists()
    assert not (output / "summary.json").exists()
