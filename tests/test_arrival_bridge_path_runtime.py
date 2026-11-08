"""Fixed path jobs, guarded data access and retained failed node draws."""

# pyright: basic
import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_bridge_path_fit as fitting
from tests.test_arrival_model_scale import grouped_lane


def test_fixed_path_jobs_conserve_fifteen_calls_and_disjoint_streams():
    jobs = fitting.path_jobs()
    assert len(jobs) == 15
    assert [(j["path_role"], j["node"]) for j in jobs] == [
        *(("primary", i) for i in range(1, 8)),
        *(("repeat", i) for i in range(8)),
    ]
    seeds = [j["seed"] for j in jobs]
    assert len(set(seeds)) == 15
    assert not set(seeds) & {1426110900, 1426110901, 89261107}
    assert all(j["temperature"] == j["node"] / 8 and j["draws"] == 2000 for j in jobs)


def test_modified_temperature_is_rejected_before_data_access(tmp_path, monkeypatch):
    def forbidden(*_):
        raise AssertionError("protected data accessed by invalid path job")

    monkeypatch.setattr(fitting, "validated_design", forbidden)
    job = {**fitting.path_jobs()[0], "temperature": 0.1}
    with pytest.raises(ValueError, match="fixed"):
        fitting.sample_path_job(tmp_path, job, tmp_path / "out", tmp_path / "raw.nc")
    assert not (tmp_path / "out").exists()


def test_node_preserves_training_and_weighted_held_groups_before_failed_diagnostics(
    tmp_path, monkeypatch
):
    root = tmp_path
    (root / "stub.py").write_text("fixture")
    lane = grouped_lane()
    monkeypatch.setattr(fitting, "CONSUMED", ["stub.py"])
    monkeypatch.setattr(fitting, "PATH_GATE", "stub.py")
    monkeypatch.setattr(fitting, "verify_path_gate", lambda *_: None)
    monkeypatch.setattr(
        fitting,
        "validated_design",
        lambda *_: (lane, np.array([0, 1]), np.array([2]), {"fixture": True}),
    )
    monkeypatch.setattr(fitting, "read_prior", lambda *_: {})
    monkeypatch.setattr(fitting.subprocess, "check_output", lambda *a, **kw: "fixture-sha")

    class Model:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(fitting, "build_path_model", lambda *_: Model())

    def sample(**_):
        return xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    {"alpha": (("chain", "draw"), np.zeros((4, 2000)))},
                    attrs={"inference_library": "nutpie", "mock_only": "yes"},
                )
            }
        )

    monkeypatch.setattr(fitting.pm, "sample", sample)

    class Table:
        def to_csv(self, p, **kw):
            Path(p).write_text("mock")

    monkeypatch.setattr(
        fitting, "sampling_diagnostics", lambda *_: ({"screen_passed": False}, Table())
    )
    output, raw = root / "out", root / "node.nc"
    fitting.sample_path_job(root, fitting.path_jobs()[0], output, raw)
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "diagnostic_failure" and raw.exists()
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as d:
        assert d.record.values.tolist() == [lane.record_ids[i] for i in [0, 1]]
    with xr.open_dataset(raw, group="integration_held_data", engine="h5netcdf") as d:
        assert d.held_record.values.tolist() == [lane.record_ids[2]]
        assert d.attrs["likelihood_power"] == 0.125
