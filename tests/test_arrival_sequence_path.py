"""Squared-grid normalizer targets, one held event and fixed independent streams."""

# pyright: basic
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from scipy.stats import multivariate_normal

from analysis.arrival.model_bridge_path import build_path_model, path_score
from analysis.arrival.model_bridge_path_validation import known_geometry, normal_path
from analysis.arrival.model_scale import build_scale_model
from analysis.arrival.model_sequence_path_fit import (
    fixed_temperatures,
    path_jobs,
    sample_sequence_path_job,
)
from analysis.arrival.models import read_prior
from tests.test_arrival_model_scale import grouped_lane


def test_squared_grid_has_exactly_thirtytwo_new_disjoint_jobs():
    spec = {"seed_base": 2326220800, "sequence": "s", "event_id": "e"}
    jobs = path_jobs(spec)
    assert len(jobs) == 32 and len({j["seed"] for j in jobs}) == 32
    assert [(j["path_role"], j["node"]) for j in jobs] == [
        *(("primary", i) for i in range(1, 16)),
        *(("repeat", i) for i in range(17)),
    ]
    np.testing.assert_array_equal(fixed_temperatures(), (np.arange(17) / 16) ** 2)
    assert all(j["temperature"] == (j["node"] / 16) ** 2 for j in jobs)


def test_modified_temperature_is_rejected_before_outcome_access(tmp_path):
    spec = {"seed_base": 2326220800, "sequence": "s", "event_id": "e"}
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    job = {**path_jobs(spec)[0], "temperature": 0.1}
    with pytest.raises(ValueError, match="fixed"):
        sample_sequence_path_job(tmp_path, p, job, tmp_path / "out", tmp_path / "raw.nc")
    assert not (tmp_path / "out").exists()


def test_all_seventeen_targets_and_gradients_interpolate_train_and_one_event_only():
    base = grouped_lane()
    ids = ("e1", "e2", "e3")
    lane = replace(
        base,
        event_ids=ids,
        sequences=("s", "q", "s"),
        rows=tuple({**row, "event_id": e} for row, e in zip(base.rows, ids, strict=True)),
    )
    prior = read_prior(Path.cwd(), lane.target, "base")
    train = np.array([1])
    held = np.array([0])
    first = build_scale_model(lane, prior, indices=train)
    last = build_scale_model(lane, prior, indices=np.array([1, 0]))
    point = {
        "alpha": np.array(0.1),
        "beta": np.array(-0.05),
        "tau_event_log__": np.log(0.2),
        "sigma_anchor_log__": np.log([0.6, 0.3, 0.12]),
    }
    values = [m.compile_logp()(point) for m in [first, last]]
    gradients = [m.compile_dlogp()(point) for m in [first, last]]
    for t in fixed_temperatures():
        model = build_path_model(lane, prior, train, held, float(t))
        assert model.compile_logp()(point) == pytest.approx(
            (1 - t) * values[0] + t * values[1], abs=1e-10
        )
        if t in [0.0, 1 / 256, 0.25, 1.0]:
            np.testing.assert_allclose(
                model.compile_dlogp()(point), (1 - t) * gradients[0] + t * gradients[1], atol=1e-10
            )
    changed = replace(lane, response=lane.response + np.array([0, 0, 999.0]))
    assert build_path_model(changed, prior, train, held, 0.25).compile_logp()(point) == (
        build_path_model(lane, prior, train, held, 0.25).compile_logp()(point)
    )


def test_squared_grid_known_gaussian_normalizers_and_raw_constant_telescoping():
    m0, m1, c0, c1 = known_geometry()
    times = fixed_temperatures()
    constant = -1700.0
    states = normal_path(m0, m1, c0, c1, times, constant)
    points = np.random.default_rng(29).normal(size=(11, 6))
    for t, (m, c, z) in zip(times, states, strict=True):
        expected = (1 - t) * cast(Any, multivariate_normal).logpdf(points, m0, c0)
        expected += t * (constant + cast(Any, multivariate_normal).logpdf(points, m1, c1))
        np.testing.assert_allclose(
            multivariate_normal.logpdf(points, m, c) + z, expected, atol=1e-11
        )
    score, influences = path_score(
        [np.full((4, 1000), constant) for _ in times], times, records=1, jacobian=275.0
    )
    assert score["joint_log_predictive"] == pytest.approx(-1975, abs=1e-10)
    assert score["joint_log_mcse_delta"] == 0 and all(np.all(a == 0) for a in influences)


def test_failed_node_keeps_raw_draws_training_and_powered_held_groups(tmp_path, monkeypatch):
    import xarray as xr

    from analysis.arrival import model_sequence_path_fit as fitter
    from analysis.arrival.evidence import sha256

    (tmp_path / "stub.py").write_text("fixture")
    spec = {"seed_base": 2326220800, "sequence": "s", "event_id": "e2"}
    manifest = tmp_path / "design.json"
    manifest.write_text(json.dumps(spec))
    lane = grouped_lane()
    monkeypatch.setattr(fitter, "CONSUMED", ["stub.py"])
    monkeypatch.setattr(
        fitter,
        "validated_design",
        lambda *_: {
            "lane": lane,
            "train": np.array([0, 1]),
            "held": np.array([2]),
            "source_files": {"fixture": True},
            "files": {"stub.py": sha256(tmp_path / "stub.py")},
        },
    )
    monkeypatch.setattr(fitter, "read_prior", lambda *_: {})
    monkeypatch.setattr(fitter.subprocess, "check_output", lambda *a, **kw: "fixture-sha")

    class Model:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(fitter, "build_path_model", lambda *_: Model())

    def sample(**_):
        return xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    {"alpha": (("chain", "draw"), np.zeros((4, 2000)))},
                    attrs={"inference_library": "nutpie", "mock_only": "yes"},
                )
            }
        )

    monkeypatch.setattr(fitter.pm, "sample", sample)

    class Table:
        def to_csv(self, p, **kw):
            Path(p).write_text("mock")

    monkeypatch.setattr(
        fitter, "sampling_diagnostics", lambda *_: ({"screen_passed": False}, Table())
    )
    output, raw = tmp_path / "out", tmp_path / "node.nc"
    fitter.sample_sequence_path_job(tmp_path, manifest, fitter.path_jobs(spec)[0], output, raw)
    assert (
        raw.exists()
        and json.loads((output / "result.json").read_text())["status"] == "diagnostic_failure"
    )
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as d:
        assert d.record.values.tolist() == [lane.record_ids[i] for i in [0, 1]]
    with xr.open_dataset(raw, group="integration_held_data", engine="h5netcdf") as d:
        assert d.held_record.values.tolist() == [lane.record_ids[2]]
        assert d.attrs["likelihood_power"] == 1 / 256
