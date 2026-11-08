"""Cache-free bridge orchestration: sequence exclusion, signed units and immutable inputs."""

# pyright: basic
import json
import math
from dataclasses import replace

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_bridge_cv as cv
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_models import tiny_lane


@pytest.mark.parametrize("target", ["T-OBS", "T-CAL"])
def test_bridge_fold_uses_independent_ensembles_and_only_one_held_event(
    tmp_path, monkeypatch, target
):
    root = tmp_path
    for p in ["stub.py", "gate.json", "bridge-gate.json"]:
        (root / p).write_text("fixture")
    lane = tiny_lane()
    if target == "T-CAL":
        lane = replace(
            lane,
            target=target,
            y=np.array([-10.0, -2.0, 3.0]),
            response=np.array([-10.0, -2.0, 3.0]),
        )
    monkeypatch.setattr(cv, "CONSUMED", ["stub.py"])
    monkeypatch.setattr(cv, "SAMPLING_CONSUMED", ["stub.py"])
    monkeypatch.setattr(cv, "verify_bridge_gate", lambda *_: None)
    monkeypatch.setattr(cv, "verify_prediction_gate", lambda *_: None)
    frozen = {"fixture": True}
    monkeypatch.setattr(cv, "load_lanes", lambda *_: ({target: lane}, frozen))
    monkeypatch.setattr(cv, "read_prior", lambda *_: {"alpha_sd": 0.5, "beta_sd": 0.25})
    monkeypatch.setattr(cv.subprocess, "check_output", lambda *a, **kw: "fixture-sha")
    seen = []

    def sample(_root, job, output, store):
        seen.append(job.copy())
        ids, _ = cv.bridge_indices(lane, job["sequence"], job["phase"], job.get("event"))
        output.mkdir(parents=True)
        tree = xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    {
                        p: (("chain", "draw"), np.full((4, 1000), value))
                        for p, value in [
                            ("alpha", 0.0),
                            ("beta", 0.0),
                            ("sigma", 20.0 if target == "T-CAL" else 0.4),
                            ("tau_event", 10.0 if target == "T-CAL" else 0.2),
                        ]
                    }
                ),
                "observed_data": xr.Dataset(
                    {"response": (("record",), lane.response[ids])},
                    coords={"record": [lane.record_ids[int(i)] for i in ids]},
                ),
            }
        )
        tree.to_netcdf(store)
        write_json(
            output / "inputs.json",
            {
                "files": {
                    "stub.py": sha256(root / "stub.py"),
                    "gate.json": sha256(root / "gate.json"),
                },
                "source_files": frozen,
            },
        )
        write_json(
            output / "result.json",
            {
                "job": job,
                "records": len(ids),
                "posterior": str(store.relative_to(root)),
                "posterior_sha256": sha256(store),
                "diagnostics": {"screen_passed": True},
            },
        )

    monkeypatch.setattr(cv, "sample_ensemble", sample)
    job = {
        "target": target,
        "kind": "event",
        "prior": "base",
        "sequence": "q1",
        "gate": "gate.json",
        "bridge_gate": "bridge-gate.json",
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 800,
    }
    cv.run_bridge_fold(root, job, root / "out", root / "store")
    assert [(j["phase"], j.get("event"), j["seed"]) for j in seen] == [
        ("training", None, 800),
        ("augmented", "e1", 801),
        ("augmented", "e3", 802),
    ]
    result = json.loads((root / "out/result.json").read_text())
    assert result["score_precision_passed"] and result["prediction_precision_passed"]
    assert result["fold_score"]["events"] == 2
    assert result["training_records"] == 1 and result["heldout_records"] == 2
    with np.load(root / "store/bridge-arrays.npz") as raw:
        for k, i in enumerate([0, 2]):
            expected = raw[f"training_log_ratio_{k:03d}"][0, 0]
            if target != "T-CAL":
                expected -= math.log(lane.y[i])
            assert result["events"][k]["joint_log_predictive"] == pytest.approx(expected)
    with pytest.raises(ValueError):
        cv.run_bridge_fold(root, job, root / "out", root / "store")


def test_bridge_gate_failure_precedes_outcome_access(tmp_path, monkeypatch):
    def reject(*_):
        raise ValueError("numerical method not accepted")

    def forbidden(*_):
        raise AssertionError("protected data accessed before method gate")

    monkeypatch.setattr(cv, "verify_bridge_gate", reject)
    monkeypatch.setattr(cv, "load_lanes", forbidden)
    job = {
        "target": "T-CAL",
        "kind": "event",
        "prior": "base",
        "sequence": "q1",
        "gate": "unused",
        "bridge_gate": "unused",
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 801,
    }
    with pytest.raises(ValueError, match="not accepted"):
        cv.run_bridge_fold(tmp_path, job, tmp_path / "out", tmp_path / "store")
    assert not (tmp_path / "out").exists()


def test_method_receipt_requires_the_executed_checkpoint_helper(tmp_path):
    files = {}
    for name in cv.CONSUMED:
        if name == "scripts/run_arrival_model_batch.py":
            continue
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture only")
        files[name] = sha256(p)
    gate = tmp_path / "method.json"
    write_json(
        gate,
        {
            "schema_version": "arrival_bridge_cv_acceptance_v1",
            "status": "accepted",
            "numerical_checker": "fixture",
            "runtime_checker": "fixture",
            "reserved_outcomes": "sealed",
            "prior_variant": "base",
            "targets": ["T-CAL"],
            "kinds": ["event"],
            "files": files,
        },
    )
    with pytest.raises(ValueError, match="gate"):
        cv.verify_bridge_gate(tmp_path, gate, "T-CAL", "event")
