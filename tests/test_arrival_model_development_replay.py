"""Synthetic replay guards only; no real posterior, outcome, Gate or sampler."""

# pyright: basic
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import h5netcdf
import numpy as np
import pytest

from analysis.arrival import model_development_recovery as G
from analysis.arrival import model_development_replay as R
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_sensitivity_priors import build_sensitivity_model
from tests.test_arrival_model_development_recovery import fixture, posterior, small_lane


def oracle() -> dict[str, Any]:
    labels = ["truth", *(f"chain-{c}-draw-{d}" for c, d in G.protocol()["oracle_positions"])]
    return dict(
        passed=True,
        points=[
            dict(
                point=label,
                passed=True,
                logp_absolute_error=1e-9,
                logp_prior_offset_corrected_error=0.0,
                prior_normalizer_offset=1e-9,
                prior_offset_drift=0.0,
                gradient_max_absolute_error=1.5987211554602254e-14,
            )
            for label in labels
        ],
        prior_only_checks=[
            dict(point=label, offset=1e-9) for label in ["truth", "fixed_prior_shift", *labels[1:]]
        ],
        selected_prior_scale_dtypes=dict(alpha="float32", sigma="float64"),
        normal_log_scale_offset_prediction=1e-9,
        normalizer_source=(
            "pymc.distributions.continuous.Normal.logp/HalfNormal.logp symbolic log(sigma)"
        ),
        measure="modeled_response_plus_selected_prior_and_transform_Jacobian",
        prior_normalizer_scope="bounded_data_independent_PyMC_prior_constant_not_likelihood_adjustment",
    )


def prepared(root, monkeypatch):
    jobs, calls, _ = fixture(root, monkeypatch, target="T-OBS", kind="pooled")
    job = next(j for j in jobs if j["model_key"] == "T-OBS:pooled:selected" and j["case"] == "A")
    monkeypatch.setattr(G, "numerical_oracles", lambda *a: oracle())
    output, raw = G.case_paths(root, job)
    assert G.run_recovery_job(root, job, output, raw)["status"] == G.SUCCESS
    pins = dict(G.verify_gate(root)["files"])
    for name in R.CONSUMED:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((Path(__file__).resolve().parents[1] / name).read_bytes())
        pins[name] = sha256(p)
    return job, output, raw, pins, calls


def test_observed_delta_old_verifier_red_new_predicates_green(tmp_path, monkeypatch):
    job, output, _, pins, calls = prepared(tmp_path, monkeypatch)
    changed = oracle()
    changed["points"][2]["gradient_max_absolute_error"] = 2.842170943040401e-14
    monkeypatch.setattr(G, "numerical_oracles", lambda *a: copy.deepcopy(changed))
    with pytest.raises(ValueError, match="density/gradient oracles must replay"):
        G.case_artifacts(tmp_path, job, pins)
    proof = R.case_artifacts(tmp_path, job, pins)
    assert proof["proof_contract"] == R.PROOF_CONTRACT
    assert proof["original_exact_oracle_equal"] is False
    assert proof["diagnostic_comparison"]["diagnostic_deltas"] == [
        dict(
            path="points[2].gradient_max_absolute_error",
            saved=1.5987211554602254e-14,
            fresh=2.842170943040401e-14,
            absolute_delta=1.2434497875801753e-14,
        )
    ]
    assert len(proof["files"]) == 18 and len(calls) == 1
    assert json.loads((output / "result.json").read_text())["status"] == G.SUCCESS
    assert not list(output.glob("proof*"))


def test_every_whitelisted_delta_is_reported_without_cross_run_tolerance():
    saved, fresh = oracle(), oracle()
    for row in fresh["points"]:
        for key in R.POINT_DIAGNOSTICS:
            row[key] += 1e-10
    for row in fresh["prior_only_checks"]:
        row["offset"] += 1e-10
    comparison = R.compare_diagnostics(saved, fresh, G.protocol())
    assert len(comparison["diagnostic_deltas"]) == 25
    assert comparison["cross_run_numeric_tolerance_used"] is False
    assert comparison["original_scientific_predicates_passed"] is True
    assert R.compare_diagnostics(saved, saved, G.protocol())["original_exact_oracle_equal"]


@pytest.mark.parametrize(
    "fault",
    [
        "top_schema",
        "row_schema",
        "prior_schema",
        "labels",
        "prior_labels",
        "dtype",
        "normalizer_constant",
        "measure",
        "top_bool",
        "row_bool",
        "nonfinite",
        "bool_float",
        "int_float",
        "negative_absolute",
        "negative_gradient",
        "negative_drift",
        "raw_bound",
        "corrected_bound",
        "offset_bound",
        "prior_drift",
    ],
)
def test_saved_diagnostic_corruption_rejects(fault):
    saved = oracle()
    if fault == "top_schema":
        saved["foreign"] = 0
    elif fault == "row_schema":
        saved["points"][0]["foreign"] = 0
    elif fault == "prior_schema":
        saved["prior_only_checks"][0]["foreign"] = 0
    elif fault == "labels":
        saved["points"][1]["point"] = "truth"
    elif fault == "prior_labels":
        saved["prior_only_checks"][1]["point"] = "truth"
    elif fault == "dtype":
        saved["selected_prior_scale_dtypes"]["alpha"] = "float64"
    elif fault == "normalizer_constant":
        saved["normal_log_scale_offset_prediction"] += 1e-16
    elif fault == "measure":
        saved["measure"] = "native_unchanged_claim"
    elif fault == "top_bool":
        saved["passed"] = 1
    elif fault == "row_bool":
        saved["points"][0]["passed"] = 1
    elif fault == "nonfinite":
        saved["points"][0]["gradient_max_absolute_error"] = float("nan")
    elif fault == "bool_float":
        saved["prior_only_checks"][0]["offset"] = True
    elif fault == "int_float":
        saved["points"][0]["prior_offset_drift"] = 0
    elif fault == "negative_absolute":
        saved["points"][0]["logp_absolute_error"] = -1e-14
    elif fault == "negative_gradient":
        saved["points"][0]["gradient_max_absolute_error"] = -1e-14
    elif fault == "negative_drift":
        saved["points"][0]["prior_offset_drift"] = -1e-14
    elif fault == "raw_bound":
        saved["points"][0]["logp_absolute_error"] = 2e-6
    elif fault == "corrected_bound":
        saved["points"][0]["logp_prior_offset_corrected_error"] = 3e-7
    elif fault == "offset_bound":
        saved["prior_only_checks"][0]["offset"] = 2e-6
    else:
        saved["points"][0]["prior_normalizer_offset"] = 3e-7
    with pytest.raises(ValueError):
        R.compare_diagnostics(saved, oracle(), G.protocol())


@pytest.mark.parametrize("fresh_fault", ["passed", "row_passed", "raw", "prior", "infinite"])
def test_fresh_original_predicate_failure_rejects(fresh_fault):
    fresh = oracle()
    if fresh_fault == "passed":
        fresh["passed"] = False
    elif fresh_fault == "row_passed":
        fresh["points"][0]["passed"] = False
    elif fresh_fault == "raw":
        fresh["points"][0]["logp_absolute_error"] = 2e-6
    elif fresh_fault == "prior":
        fresh["prior_only_checks"][0]["offset"] = 2e-6
    else:
        fresh["points"][0]["gradient_max_absolute_error"] = float("inf")
    with pytest.raises(ValueError):
        R.compare_diagnostics(oracle(), fresh, G.protocol())


def test_signed_offsets_allowed_without_gradient_max_substitute():
    old, fresh = oracle(), oracle()
    for value in [old, fresh]:
        for row in value["prior_only_checks"]:
            row["offset"] = -1e-9
        for row in value["points"]:
            row["prior_normalizer_offset"] = -1e-9
            # The unchanged fresh oracle owns componentwise atol+rtol; no new scalar test.
            row["gradient_max_absolute_error"] = 3e-5
    assert R.compare_diagnostics(old, fresh, G.protocol())["original_exact_oracle_equal"]


def test_real_frozen_componentwise_gradient_failure_cannot_be_promoted(monkeypatch):
    lane = small_lane("T-OBS")
    truth = G._truth(lane.target, "pooled", "A")
    fake, _ = G.simulate(lane, "pooled", truth, 123)
    base = dict(alpha_sd=0.5, beta_sd=0.25, sigma_sd=0.4, tau_sd=0.4)
    model = build_sensitivity_model(
        fake, "pooled", base, "base", indices=np.flatnonzero(fake.included)
    )
    original = model.compile_dlogp()
    monkeypatch.setattr(model, "compile_dlogp", lambda: lambda p: original(p) + 0.01)
    fresh = G.numerical_oracles(
        model,
        fake,
        "pooled",
        truth,
        dict(family="normal", distribution_scales=base),
        posterior(lane.target, "pooled", truth),
    )
    assert fresh["passed"] is False
    with pytest.raises(ValueError, match="scientific oracle must pass"):
        R.compare_diagnostics(oracle(), fresh, G.protocol())


@pytest.mark.parametrize(
    "fault",
    ["inputs", "prior", "diagnostics", "summary", "csv", "truth", "membership", "model", "native"],
)
def test_entire_original_prefix_and_suffix_still_reject_resealed_corruption(
    tmp_path, monkeypatch, fault
):
    job, output, raw, pins, calls = prepared(tmp_path, monkeypatch)
    if fault == "native":
        with h5netcdf.File(raw, "r+") as tree:
            value = tree.groups["observed_data"].variables["native_minutes"]
            value[0] += 1
        result = json.loads((output / "result.json").read_text())
        result["posterior_sha256"] = sha256(raw)
        write_json(output / "result.json", result)
    elif fault in {"csv", "truth", "diagnostics"}:
        name = {
            "csv": "parameters.csv",
            "truth": "truth-quantiles.csv",
            "diagnostics": "sampling-diagnostics.csv",
        }[fault]
        (output / name).write_text("wrong\n999\n")
    else:
        name = {
            "inputs": "inputs.json",
            "model": "inputs.json",
            "prior": "prior-settings.json",
            "summary": "summary.json",
            "membership": "membership.json",
        }[fault]
        value = json.loads((output / name).read_text())
        if fault == "inputs":
            value["files"] = dict(list(value["files"].items())[:1])
        elif fault == "model":
            value["model_spec"]["kind"] = "event"
        elif fault == "prior":
            value["family"] = "unapproved"
        elif fault == "summary":
            value["parameters"][0]["q50"] = 999
        else:
            value["training_record_ids"].reverse()
        write_json(output / name, value)
    G.fit._manifest(output)
    with pytest.raises(ValueError):
        R.case_artifacts(tmp_path, job, pins)
    assert len(calls) == 1


def test_replay_source_pins_precede_gate_or_design_reads(tmp_path, monkeypatch):
    job, _, _, pins, _ = prepared(tmp_path, monkeypatch)
    pins.pop(R.TEST)
    monkeypatch.setattr(G, "verify_gate", lambda *a: pytest.fail("gate before replay source pins"))
    with pytest.raises(ValueError, match="replay source pins"):
        R.case_artifacts(tmp_path, job, pins)


def test_changed_accepted_inventory_and_late_source_drift_rejected(tmp_path, monkeypatch):
    job, _, _, pins, _ = prepared(tmp_path, monkeypatch)
    proof = R.case_artifacts(tmp_path, job, pins)
    with pytest.raises(ValueError, match="accepted recovery inventory"):
        R.case_artifacts(tmp_path, job, pins, accepted={"files": {}})

    def changed(*args):
        (tmp_path / R.SELF).write_text("changed after admission")
        return oracle()

    monkeypatch.setattr(G, "numerical_oracles", changed)
    with pytest.raises(ValueError):
        R.case_artifacts(tmp_path, job, pins)
    assert len(proof["files"]) == 18


def test_alias_root_rejects_before_scientific_admission(tmp_path, monkeypatch):
    pins = {}
    for name in R.CONSUMED:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic source")
        pins[name] = sha256(p)
    alias = tmp_path.with_name(tmp_path.name + "-alias")
    alias.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(G, "verify_gate", lambda *a: pytest.fail("nonliteral root admitted"))
    with pytest.raises(ValueError):
        R.case_artifacts(alias, {}, pins)


def test_metadata_import_remains_scientific_library_free():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from analysis.arrival import model_development_replay; "
            "assert not {'numpy','pymc','pytensor','arviz'} & set(sys.modules)",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
