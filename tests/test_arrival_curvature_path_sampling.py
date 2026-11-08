"""Fixed seeds, pre-outcome gates and save-before-diagnostics numerical nodes."""

# pyright: basic

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis.arrival import model_curvature_path_sampling as worker
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_model_scale import grouped_lane


def test_exact32_seeds_are_disjoint_from_original_endpoint_and_other_folds():
    jobs = worker.path_jobs()
    assert len(jobs) == 32 and len({j["seed"] for j in jobs}) == 32
    assert [j["node"] for j in jobs[:15]] == list(range(1, 16))
    assert [j["node"] for j in jobs[15:]] == list(range(17))
    assert all(2856112801 < j["seed"] < 2856113800 for j in jobs)
    np.testing.assert_array_equal(worker.temperatures(), (np.arange(17) / 16) ** 2)


def test_incomplete_design_blocks_outcome_loader(tmp_path, monkeypatch):
    write_json(tmp_path / worker.GATE, {"status": "pending"})

    def forbidden(*args):
        raise AssertionError("outcomes remain unopened")

    monkeypatch.setattr(worker, "load_lanes", forbidden)
    with pytest.raises(ValueError, match="independent fixed32"):
        worker.load_design(tmp_path)


def fixture(root, monkeypatch, *, failure=False):
    lane = grouped_lane()
    train, held = np.array([0, 1]), np.array([2])
    stub = root / "stub.py"
    stub.write_text("source")
    design = {
        "lane": lane,
        "train": train,
        "held": held,
        "files": {"stub.py": sha256(stub)},
        "source_files": {"toy": True},
    }
    monkeypatch.setattr(worker, "load_design", lambda *a: design)
    monkeypatch.setattr(worker.subprocess, "check_output", lambda *a, **k: "fixture-git-sha\n")
    monkeypatch.setattr(
        worker,
        "read_curvature_prior",
        lambda *a: {
            "alpha_sd": 0.5,
            "beta_sd": 0.25,
            "gamma_sd": 0.5,
            "tau_sd": 0.4,
            "sigma_sd": 0.4,
        },
    )
    post = xr.Dataset(
        {
            k: (("chain", "draw"), np.full((4, 2000), v))
            for k, v in [("alpha", 0.1), ("beta", -0.05), ("gamma", 0.4), ("tau_event", 0.2)]
        },
        attrs={"sampler": "nutpie"},
    )
    post["sigma_anchor"] = xr.DataArray(
        np.tile([0.6, 0.3, 0.12], (4, 2000, 1)),
        dims=("chain", "draw", "scale_anchor_km"),
        coords={"scale_anchor_km": [500, 2000, 5000]},
    )
    tree = xr.DataTree.from_dict({"posterior": post})
    monkeypatch.setattr(worker.pm, "sample", lambda **k: tree)
    monkeypatch.setattr(
        worker,
        "sampling_diagnostics",
        lambda *a: ({"screen_passed": not failure}, pd.DataFrame({"r_hat": [1.0]})),
    )
    job = worker.path_jobs()[0]
    output = root / worker.OUTPUT / "jobs" / job["id"]
    raw = root / worker.STORE / (job["id"] + ".nc")
    return design, job, output, raw


def test_node_keeps_both_data_roles_and_replays_full_gamma_density(tmp_path, monkeypatch):
    design, job, output, raw = fixture(tmp_path, monkeypatch)
    worker.sample_node(tmp_path, job, output, raw)
    values = worker.read_node(tmp_path, job, design)
    assert values.shape == (4, 2000) and np.isfinite(values).all()
    assert (output / "sampling-start.json").is_file()
    with xr.open_dataset(raw, group="integration_held_data", engine="h5netcdf") as data:
        assert data.attrs["likelihood_power"] == 1 / 256
        np.testing.assert_array_equal(data.native_minutes.values, design["lane"].y[[2]])
    with pytest.raises(ValueError, match="exact new"):
        worker.sample_node(tmp_path, job, output, raw)


def test_failed_diagnostics_retains_posterior_and_start_without_logL(tmp_path, monkeypatch):
    _, job, output, raw = fixture(tmp_path, monkeypatch, failure=True)
    worker.sample_node(tmp_path, job, output, raw)
    assert raw.exists() and (output / "sampling-start.json").exists()
    assert not raw.with_suffix(".loglikelihood.npz").exists()
    import json

    assert json.loads((output / "result.json").read_text())["status"] == "diagnostic_failure"


def test_changed_cached_logL_is_refused_even_if_new_hash_is_supplied(tmp_path, monkeypatch):
    design, job, output, raw = fixture(tmp_path, monkeypatch)
    worker.sample_node(tmp_path, job, output, raw)
    import json

    array = raw.with_suffix(".loglikelihood.npz")
    np.savez_compressed(array, held_loglikelihood=np.zeros((4, 2000)))
    result = json.loads((output / "result.json").read_text())
    result["held_loglikelihood_sha256"] = sha256(array)
    write_json(output / "result.json", result)
    with pytest.raises(AssertionError):
        worker.read_node(tmp_path, job, design)


def test_existing_cache_is_preserved_before_any_sampler(tmp_path, monkeypatch):
    _, job, output, raw = fixture(tmp_path, monkeypatch)
    array = raw.with_suffix(".loglikelihood.npz")
    array.parent.mkdir(parents=True)
    array.write_bytes(b"original partial")
    with pytest.raises(ValueError, match="exact new"):
        worker.sample_node(tmp_path, job, output, raw)
    assert array.read_bytes() == b"original partial" and not output.exists()


def test_newly_appearing_cache_partial_is_preserved_exclusively(tmp_path, monkeypatch):
    _, job, output, raw = fixture(tmp_path, monkeypatch)
    sample = worker.pm.sample
    array = raw.with_suffix(".loglikelihood.npz")

    def injected(**kwargs):
        array.write_bytes(b"appeared during sampling")
        return sample(**kwargs)

    monkeypatch.setattr(worker.pm, "sample", injected)
    with pytest.raises(FileExistsError):
        worker.sample_node(tmp_path, job, output, raw)
    assert array.read_bytes() == b"appeared during sampling" and raw.exists()
