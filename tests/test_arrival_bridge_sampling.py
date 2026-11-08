"""The integration ensemble must never add other events from a held-out sequence."""

# pyright: basic
import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_bridge_sampling as sampling
from analysis.arrival import model_bridge_validation as validation
from analysis.arrival.evidence import sha256
from tests.test_arrival_models import tiny_lane


def test_augmented_indices_add_one_event_and_reject_wrong_phase():
    lane = tiny_lane()
    ids, _ = sampling.bridge_indices(lane, "q1", "training", None)
    assert ids.tolist() == [1]
    for event, expected in [("e1", [0, 1]), ("e3", [1, 2])]:
        ids, _ = sampling.bridge_indices(lane, "q1", "augmented", event)
        assert ids.tolist() == expected
    with pytest.raises(ValueError):
        sampling.bridge_indices(lane, "q1", "augmented", "e2")
    with pytest.raises(ValueError):
        sampling.bridge_indices(lane, "q1", "training", "e1")


def test_sampling_saves_literal_subset_before_diagnostics_and_keeps_failure(tmp_path, monkeypatch):
    root = tmp_path
    (root / "stub.py").write_text("fixture only")
    (root / "gate.json").write_text("{}")
    lane = tiny_lane()
    monkeypatch.setattr(sampling, "CONSUMED", ["stub.py"])
    monkeypatch.setattr(sampling, "load_lanes", lambda *_: ({"T-OBS": lane}, {"fixture": True}))
    monkeypatch.setattr(sampling, "verify_prediction_gate", lambda *_: None)
    monkeypatch.setattr(sampling, "read_prior", lambda *_: {})
    monkeypatch.setattr(sampling.subprocess, "check_output", lambda *a, **kw: "fixture-sha")
    seen = []

    class Model:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def build(*a, **kw):
        seen.append(kw["indices"].tolist())
        return Model()

    monkeypatch.setattr(sampling, "build_model", build)
    monkeypatch.setattr(
        sampling.pm,
        "sample",
        lambda **kw: xr.DataTree.from_dict(
            {"posterior": xr.Dataset({"alpha": (("chain", "draw"), np.zeros((4, 1000)))})}
        ),
    )

    class Table:
        def to_csv(self, p, **kw):
            Path(p).write_text("mock")

    diagnostics = {"screen_passed": False}
    monkeypatch.setattr(sampling, "sampling_diagnostics", lambda tree: (diagnostics, Table()))
    job = {
        "target": "T-OBS",
        "kind": "event",
        "prior": "base",
        "sequence": "q1",
        "phase": "augmented",
        "event": "e1",
        "gate": "gate.json",
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 101,
    }
    sampling.sample_ensemble(root, job, root / "output", root / "posterior.nc")
    assert seen == [[0, 1]]
    result = json.loads((root / "output/result.json").read_text())
    assert not result["diagnostics"]["screen_passed"]
    assert sha256(root / "posterior.nc") == result["posterior_sha256"]
    with xr.open_dataset(root / "posterior.nc", group="observed_data", engine="h5netcdf") as ds:
        assert ds.record.values.tolist() == ["r0", "r1"]
        np.testing.assert_array_equal(ds.response.values, lane.response[[0, 1]])


def test_bridge_prototype_rejects_an_augmented_prior_variant_before_reading_data(
    tmp_path, monkeypatch
):
    for phase, prior in [("training", "base"), ("augmented", "wider")]:
        folder = tmp_path / phase
        folder.mkdir()
        (folder / "result.json").write_text(
            json.dumps(
                {
                    "job": {
                        "target": "NCEI-native-duration",
                        "kind": "event",
                        "prior": prior,
                        "seed": 1 if phase == "training" else 2,
                        "gate": "unused.json",
                    },
                    "diagnostics": {"screen_passed": True},
                }
            )
        )
    monkeypatch.setattr(validation, "verify_prediction_gate", lambda *_: None)

    def forbidden(*_):
        raise AssertionError("must reject unequal priors before outcome access")

    monkeypatch.setattr(validation, "load_lanes", forbidden)
    with pytest.raises(ValueError, match="base-prior"):
        validation.actual_pilot(
            tmp_path, tmp_path / "training", tmp_path / "augmented", tmp_path / "out"
        )
