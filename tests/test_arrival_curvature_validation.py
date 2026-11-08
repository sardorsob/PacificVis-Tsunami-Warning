"""Known scalar transformations and an explicit prior gate before protected loading."""

# pyright: basic
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_curvature_validation as worker


def test_diagnostic_quantities_include_curvature_and_total_spread():
    truth = {
        "alpha": 0.1,
        "beta": -0.05,
        "gamma": 0.4,
        "tau_event": 0.05,
        "sigma_anchor": [0.6, 0.6, 0.1],
    }
    dataset = xr.Dataset(
        {
            k: (("chain", "draw"), np.full((2, 4), truth[k]))
            for k in ["alpha", "beta", "gamma", "tau_event"]
        }
    )
    dataset["sigma_anchor"] = xr.DataArray(
        np.broadcast_to(truth["sigma_anchor"], (2, 4, 3)), dims=("chain", "draw", "anchor")
    )
    dataset["event_effect"] = xr.DataArray(
        np.full((2, 4, 2), 0.2), dims=("chain", "draw", "event"), coords={"event": ["e1", "e2"]}
    )
    values, truths = worker.curvature_quantities(dataset, {"e1": 0.2, "e2": 0.2}, truth)
    assert len(values) == 12 and set(values) == set(truths)
    assert truths["median_elasticity_1000km"] == pytest.approx(0.95 - 0.4 / 3)
    assert truths["median_ratio_100km"] == pytest.approx(
        np.exp(0.1 - 0.05 * np.log(0.1) + 0.4 * np.log(4))
    )
    assert truths["predictive_log_SD_1000km"] == pytest.approx(np.sqrt(0.05**2 + 0.6**2))
    for name, array in values.items():
        np.testing.assert_allclose(array, truths[name])


def test_missing_prior_gate_cannot_parse_any_analysis_outcome(tmp_path: Path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("outcome loader entered before accepted prior gate")

    monkeypatch.setattr(worker, "load_lanes", forbidden)
    job = {
        "model": "mean-curvature",
        "target": "NCEI-native-duration",
        "phase": "pilot",
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 2816110800,
        "truth": {},
    }
    with pytest.raises(FileNotFoundError):
        worker.fit_curvature_synthetic_job(
            tmp_path, job, tmp_path / "output", tmp_path / "draws.nc"
        )


def test_original_native_and_log_outcomes_cannot_change_synthetic_inference_route(
    tmp_path, monkeypatch
):
    # Routing-only test: a fixed sampler and diagnostics stand in for inference.
    from dataclasses import replace
    from types import SimpleNamespace

    import pandas as pd

    from tests.test_arrival_model_scale import grouped_lane

    lane = grouped_lane()
    altered = replace(
        lane,
        response=np.full(3, 9999.0),
        y=np.full(3, 8888.0),
        rows=tuple({**r, "target_minutes": "8888"} for r in lane.rows),
    )
    source = [lane]
    monkeypatch.setattr(
        worker, "load_lanes", lambda root: ({"NCEI-native-duration": source[0]}, {"inputs": {}})
    )
    monkeypatch.setattr(worker, "verify_curvature_prior", lambda root: None)
    monkeypatch.setattr(worker, "CONSUMED", [])
    prior = {"alpha_sd": 0.5, "beta_sd": 0.25, "gamma_sd": 0.5, "tau_sd": 0.4, "sigma_sd": 0.4}
    monkeypatch.setattr(worker, "read_curvature_prior", lambda *args: prior)
    monkeypatch.setattr(worker, "prior_reference_sds", lambda root: {k: 1.0 for k in names})
    monkeypatch.setattr(
        worker, "subprocess", SimpleNamespace(check_output=lambda *a, **k: "fixture\n")
    )
    monkeypatch.setattr(
        worker,
        "sampling_diagnostics",
        lambda tree: ({"screen_passed": True}, pd.DataFrame({"mock": [True]})),
    )
    monkeypatch.setattr(worker, "rank_summary", lambda *a: {"rank_ready": True, "rank": 50})
    truth = {
        "alpha": 0.1,
        "beta": -0.05,
        "gamma": 0.4,
        "tau_event": 0.05,
        "sigma_anchor": [0.6, 0.6, 0.1],
    }
    dataset = xr.Dataset(
        {
            k: (("chain", "draw"), np.full((4, 20), truth[k]))
            for k in ["alpha", "beta", "gamma", "tau_event"]
        }
    )
    dataset["sigma_anchor"] = xr.DataArray(
        np.broadcast_to(truth["sigma_anchor"], (4, 20, 3)),
        dims=("chain", "draw", "scale_anchor_km"),
    )
    dataset["event_effect"] = xr.DataArray(
        np.zeros((4, 20, 2)), dims=("chain", "draw", "event"), coords={"event": ["e1", "e2"]}
    )
    names = worker.curvature_quantities(dataset, {"e1": 0.0, "e2": 0.0}, truth)[0]
    del dataset["event_effect"]
    dataset.attrs["inference_library"] = "nutpie-mock-for-route-test"
    log_targets = []

    def fixed_sample(**kwargs):
        model = worker.pm.modelcontext(None)
        log_targets.append(float(model.compile_logp()(model.initial_point())))
        return xr.DataTree.from_dict({"posterior": dataset.copy(deep=True)})

    monkeypatch.setattr(worker.pm, "sample", fixed_sample)
    job = {
        "model": "mean-curvature",
        "target": "NCEI-native-duration",
        "phase": "pilot",
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 2816110800,
        "truth": truth,
        "first_event_id": "e1",
    }
    import json

    results = []
    trees = []
    for j, item in enumerate([lane, altered]):
        source[0] = item
        out = tmp_path / f"out{j}"
        store = tmp_path / f"draws{j}.nc"
        worker.fit_curvature_synthetic_job(tmp_path, job, out, store)
        results.append(json.loads((out / "result.json").read_text()))
        tree = xr.open_datatree(store)
        trees.append(tree.load())
    assert log_targets[0] == log_targets[1]
    assert results[0]["diagnostics"] == results[1]["diagnostics"]
    assert results[0]["estimates"] == results[1]["estimates"]
    xr.testing.assert_equal(
        trees[0]["observed_data"].to_dataset(), trees[1]["observed_data"].to_dataset()
    )
    xr.testing.assert_equal(trees[0]["posterior"].to_dataset(), trees[1]["posterior"].to_dataset())
    for tree in trees:
        tree.close()


@pytest.mark.parametrize("proof", [{}, {"only-a-path": "not-a-checksum"}])
def test_prior_receipt_must_cover_essential_proof_before_outcome_loader(
    tmp_path, monkeypatch, proof
):
    import json

    gate = tmp_path / worker.PRIOR_GATE
    gate.parent.mkdir(parents=True)
    gate.write_text(
        json.dumps(
            {
                "status": "accepted_for_synthetic_validation",
                "model": "mean-curvature",
                "independent_checker": True,
                "reserved_outcomes": "sealed",
                "confirmation_outcomes_parsed": False,
                "files": proof,
            }
        )
    )
    monkeypatch.setattr(worker, "load_lanes", lambda *args: pytest.fail("outcomes opened"))
    with pytest.raises(ValueError, match="proof"):
        worker.verify_curvature_prior(tmp_path)


def test_retained_augmented_partial_cannot_be_overwritten(tmp_path):
    partial = tmp_path / "draws-augmented.nc"
    partial.write_bytes(b"retained partial sentinel")
    job = {
        "model": "mean-curvature",
        "target": "NCEI-native-duration",
        "phase": "pilot",
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 2816110800,
        "truth": {},
    }
    with pytest.raises(ValueError, match="new project paths"):
        worker.fit_curvature_synthetic_job(
            tmp_path, job, tmp_path / "output", tmp_path / "draws.nc"
        )
    assert partial.read_bytes() == b"retained partial sentinel"
