"""Whole-sequence orchestration with dummy posteriors; no scientific sampling."""

# pyright: basic
import json
from dataclasses import replace

import numpy as np
import pytest
import xarray as xr
from scipy.stats import norm

from analysis.arrival import model_curvature_sequence as worker
from analysis.arrival.evidence import sha256
from analysis.arrival.model_bridge_sampling import bridge_indices
from tests.test_arrival_models import tiny_lane


def fixture(root, monkeypatch, *, diagnostic_failure=False):
    source = root / "stub.py"
    source.write_text("frozen")
    pins = {"stub.py": sha256(source)}
    lane = replace(tiny_lane(), target="NCEI-native-duration")
    monkeypatch.setattr(worker, "verify_gate", lambda *a: pins)
    monkeypatch.setattr(
        worker, "load_lanes", lambda *a: ({"NCEI-native-duration": lane}, {"fixture": True})
    )
    monkeypatch.setattr(
        worker,
        "read_curvature_prior",
        lambda *a: {"alpha_sd": 0.5, "beta_sd": 0.25, "gamma_sd": 0.5},
    )
    calls = []

    def sample(_root, job, ids, _lane, frozen, output, store, _pins):
        calls.append((job.copy(), ids.tolist()))
        output.mkdir(parents=True)
        alpha = 0.0 if job["phase"] == "training" else 10.0
        post = xr.Dataset(
            {
                p: (("chain", "draw"), np.full((4, 2000), v))
                for p, v in [("alpha", alpha), ("beta", 0.1), ("gamma", 0.2), ("tau_event", 0.2)]
            }
        )
        post["sigma_anchor"] = xr.DataArray(
            np.full((4, 2000, 3), 0.4),
            dims=("chain", "draw", "scale_anchor_km"),
            coords={"scale_anchor_km": [500, 2000, 5000]},
        )
        tree = xr.DataTree.from_dict(
            {
                "posterior": post,
                "observed_data": xr.Dataset(
                    {
                        "response": (("record",), lane.response[ids]),
                        "native_minutes": (("record",), lane.y[ids]),
                    },
                    coords={"record": [lane.record_ids[int(i)] for i in ids]},
                ),
            }
        )
        tree.to_netcdf(store)
        result = {
            "job": job,
            "records": len(ids),
            "posterior": str(store.relative_to(root)),
            "posterior_sha256": sha256(store),
            "diagnostics": {"screen_passed": not diagnostic_failure},
        }
        return result, post

    monkeypatch.setattr(worker, "sample_ensemble", sample)
    job = {
        "target": "NCEI-native-duration",
        "kind": "mean-curvature",
        "prior": "base",
        "sequence": "q1",
        "draws": 2000,
        "tune": 1000,
        "cores": 2,
        "seed": 2856110800,
    }
    return lane, job, calls


def test_fold_purges_sequence_augments_one_event_and_applies_native_jacobian_once(
    tmp_path, monkeypatch
):
    lane, job, calls = fixture(tmp_path, monkeypatch)
    worker.run_fold(tmp_path, job, tmp_path / "fold", tmp_path / "raw")
    assert [v[1] for v in calls] == [[1], [0, 1], [1, 2]]
    assert [v[0]["event"] for v in calls] == [None, "e1", "e3"]
    assert [v[0]["seed"] for v in calls] == [job["seed"] + j for j in range(3)]
    result = json.loads((tmp_path / "fold/result.json").read_text())
    assert result["status"] == "computed_pending_review" and result["sampler_calls_started"] == 3
    _, fold = bridge_indices(lane, "q1", "training", None)
    prior = np.diag(np.array([0.5, 0.25, 0.5]) ** 2)

    def design(d):
        return np.c_[np.ones(len(d)), np.log(d / 1000), np.log((d + 500) / (1.5 * d))]

    for i, event in zip(fold.test, result["events"], strict=True):
        x = design(lane.distance_km[[1, i]])
        covariance = x @ prior @ x.T + np.eye(2) * (0.4**2 + 0.2**2)
        mean = covariance[1, 0] / covariance[0, 0] * lane.response[1]
        variance = covariance[1, 1] - covariance[1, 0] ** 2 / covariance[0, 0]
        expected = norm.logpdf(lane.response[i], mean, np.sqrt(variance)) - np.log(lane.y[i])
        assert event["joint_log_predictive"] == pytest.approx(expected, abs=1e-9)
    import csv

    rows = list(csv.DictReader((tmp_path / "fold/held-out-record-predictions.csv").open()))
    for row in rows:
        i = lane.record_ids.index(row["record_id"])
        d = lane.distance_km[i]
        expected = lane.reference_minutes[i] * np.exp(
            0.1 * np.log(d / 1000) + 0.2 * np.log((d + 500) / (1.5 * d))
        )
        assert float(row["q50"]) == pytest.approx(expected, rel=1e-9)
    assert [v for v in (tmp_path / "fold/sampling-starts").glob("*.json")].__len__() == 3


def test_failed_training_diagnostics_stops_before_any_augmented_fit(tmp_path, monkeypatch):
    _, job, calls = fixture(tmp_path, monkeypatch, diagnostic_failure=True)
    worker.run_fold(tmp_path, job, tmp_path / "fold", tmp_path / "raw")
    assert len(calls) == 1
    result = json.loads((tmp_path / "fold/result.json").read_text())
    assert result["status"] == "diagnostic_failure" and result["sampler_calls_started"] == 1
    assert not (tmp_path / "fold/held-out-record-predictions.csv").exists()


def test_existing_fold_is_not_overwritten_or_resampled(tmp_path, monkeypatch):
    _, job, calls = fixture(tmp_path, monkeypatch)
    (tmp_path / "fold").mkdir()
    with pytest.raises(ValueError, match="new bounded"):
        worker.run_fold(tmp_path, job, tmp_path / "fold", tmp_path / "raw")
    assert not calls


@pytest.mark.parametrize("bad_phase", ["training", "augmented"])
def test_each_ensemble_anchor_order_is_checked_before_scores(tmp_path, monkeypatch, bad_phase):
    _, job, calls = fixture(tmp_path, monkeypatch)
    original = worker.sample_ensemble

    def changed(*args):
        result, post = original(*args)
        if args[1]["phase"] == bad_phase:
            post = post.assign_coords(scale_anchor_km=[5000, 2000, 500])
        return result, post

    monkeypatch.setattr(worker, "sample_ensemble", changed)
    with pytest.raises(AssertionError):
        worker.run_fold(tmp_path, job, tmp_path / "fold", tmp_path / "raw")
    assert len(calls) == (1 if bad_phase == "training" else 2)
    assert not (tmp_path / "raw/bridge-arrays.npz").exists()


@pytest.mark.parametrize("missing", ["independent", "reserved", "confirmation"])
def test_cv_gate_requires_independent_and_protected_fit_acceptance(tmp_path, monkeypatch, missing):
    from analysis.arrival.evidence import write_json

    source = tmp_path / "stub.py"
    source.write_text("fixture")
    fit = {
        "status": "accepted_actual_curvature_fit_with_conditional_ppc_inadequacy",
        "independent_checker": True,
        "protected_data": {"reserved_outcomes": "sealed", "confirmation_outcomes_parsed": False},
        "files": {"stub.py": sha256(source)},
    }
    if missing == "independent":
        fit["independent_checker"] = False
    else:
        fit["protected_data"][
            "reserved_outcomes" if missing == "reserved" else "confirmation_outcomes_parsed"
        ] = "wrong"
    write_json(tmp_path / worker.FIT_GATE, fit)
    monkeypatch.setattr(worker, "CONSUMED", ["stub.py", worker.FIT_GATE])
    job = {"fixture": "gate"}
    write_json(
        tmp_path / worker.GATE,
        {
            "status": "accepted_curvature_sequence_rehearsal",
            "independent_checker": True,
            "max_sampler_call_slots": 248,
            "cases": [job],
            "files": {
                "stub.py": sha256(source),
                worker.FIT_GATE: sha256(tmp_path / worker.FIT_GATE),
            },
        },
    )
    with pytest.raises(ValueError, match="accepted actual fit"):
        worker.verify_gate(tmp_path, job)
