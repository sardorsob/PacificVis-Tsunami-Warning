"""Fixed seeds, pre-outcome gates and save-before-diagnostics numerical nodes."""

# pyright: basic

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis.arrival import model_curvature_sumatra_path_sampling as worker
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_model_scale import grouped_lane


def test_exact32_seeds_are_disjoint_from_original_endpoint_and_other_folds():
    jobs = worker.path_jobs()
    assert len(jobs) == 32 and len({j["seed"] for j in jobs}) == 32
    assert [j["node"] for j in jobs[:15]] == list(range(1, 16))
    assert [j["node"] for j in jobs[15:]] == list(range(17))
    assert all(2876129900 < j["seed"] < 2876130000 for j in jobs)
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


@pytest.mark.parametrize("change", ["backend", "gamma_shape", "sigma_shape"])
def test_new_invalid_posterior_is_retained_without_cache(tmp_path, monkeypatch, change):
    _, job, output, raw = fixture(tmp_path, monkeypatch)
    sample = worker.pm.sample

    def invalid(**kwargs):
        tree = sample(**kwargs)
        if change == "backend":
            tree["posterior"].attrs["sampler"] = "other"
        else:
            name = "gamma" if change == "gamma_shape" else "sigma_anchor"
            tree["posterior"][name] = xr.DataArray(np.ones(2000), dims=("draw",))
        return tree

    monkeypatch.setattr(worker.pm, "sample", invalid)
    worker.sample_node(tmp_path, job, output, raw)
    assert raw.is_file() and not raw.with_suffix(".loglikelihood.npz").exists()
    assert json.loads((output / "result.json").read_text())["status"] in {
        "backend_failure",
        "posterior_shape_failure",
    }


@pytest.mark.parametrize("kind", ["native", "backend", "gamma_shape", "diagnostics", "flags"])
def test_replay_rejects_rehashed_invalid_node(tmp_path, monkeypatch, kind):
    design, job, output, raw = fixture(tmp_path, monkeypatch)
    worker.sample_node(tmp_path, job, output, raw)
    result = json.loads((output / "result.json").read_text())
    if kind in {"diagnostics", "flags"}:
        if kind == "diagnostics":
            result["diagnostics"]["screen_passed"] = False
        else:
            result["confirmation_outcomes_parsed"] = True
    else:
        with xr.open_datatree(raw, engine="h5netcdf") as saved:
            tree = saved.load()
        if kind == "native":
            tree["observed_data"]["native_minutes"] *= 2
        elif kind == "backend":
            tree["posterior"].attrs["sampler"] = "other"
        else:
            tree["posterior"]["gamma"] = xr.DataArray(np.ones(2000), dims="draw")
        tree.to_netcdf(raw)
        tree.close()
        result["posterior_sha256"] = sha256(raw)
    write_json(output / "result.json", result)
    with pytest.raises((ValueError, AssertionError)):
        worker.read_node(tmp_path, job, design)


def admitted_fixture(root, monkeypatch):
    """Entire fake original closure; no actual outcome or accepted receipt is read."""
    monkeypatch.setattr(worker, "ORIGINAL_CONSUMED", ["contract.toml"])
    monkeypatch.setattr(worker, "consumed_source_files", lambda root: ["worker.py"])
    paths = set(worker.required_original_files()) | {"contract.toml", "worker.py"}
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("retained fixture")
    train, whole = np.arange(984), np.arange(984, 1064)
    lane = replace(
        grouped_lane(),
        record_ids=tuple(f"r{i}" for i in range(1064)),
        event_ids=tuple(
            ["train"] * 984 + [worker.EVENT] * 49 + ["usp000f2ab"] * 22 + ["usp000gsmz"] * 9
        ),
    )
    membership = {
        "train": list(lane.record_ids[:984]),
        "test": list(lane.record_ids[984:]),
        "sequence": worker.SEQUENCE,
    }
    job = {"id": "fold-019", "sequence": worker.SEQUENCE, "seed": 2856129800}
    files = {"contract.toml": sha256(root / "contract.toml")}
    write_json(root / worker.ORIGINAL_PLAN, {"files": files, "cases": [None] * 19 + [job]})
    write_json(
        root / worker.ORIGINAL_GATE,
        {
            "files": files,
            "cases": [job],
            "status": "accepted_curvature_sequence_rehearsal",
            "independent_checker": True,
            "max_sampler_call_slots": 248,
        },
    )
    write_json(root / worker.SOURCE / "job.json", job)
    write_json(root / worker.SOURCE / "membership.json", membership)
    write_json(
        root / worker.SOURCE / "result.json",
        {
            "job": job,
            "status": "precision_failure",
            "prediction_precision_passed": True,
            "sampler_calls_started": 4,
            "training_records": 984,
            "heldout_records": 80,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "events": [
                {"event_id": event, "records": n, "precision_passed": passed}
                for event, n, passed in [
                    (worker.EVENT, 49, False),
                    ("usp000f2ab", 22, True),
                    ("usp000gsmz", 9, True),
                ]
            ],
            "bridge_arrays": f"{worker.ORIGINAL_STORE}/bridge-arrays.npz",
            "bridge_arrays_sha256": sha256(root / worker.ORIGINAL_STORE / "bridge-arrays.npz"),
        },
    )
    inputs = {
        "files": {**files, worker.ORIGINAL_GATE: sha256(root / worker.ORIGINAL_GATE)},
        "source_files": {"frozen": "fixture"},
    }
    for folder in [root / worker.SOURCE, *sorted((root / worker.SOURCE / "ensembles").iterdir())]:
        write_json(folder / "inputs.json", inputs)
    pins = {name: sha256(root / name) for name in paths}
    monkeypatch.setattr(worker, "STOP_PIN_COUNT", len(pins))
    write_json(
        root / worker.STOP_REVIEW,
        {
            "status": "accepted_curvature_completion_overlap_stop",
            "independent_checker": True,
            "files": pins,
            "calls_charged": 77,
            "calls_started": 77,
            "failed_event": worker.EVENT,
            "quarantined_case": "fold-019",
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    pins = {**pins, worker.STOP_REVIEW: sha256(root / worker.STOP_REVIEW)}
    gate = {
        "status": "accepted_curvature_sumatra_path_resolution",
        "independent_checker": True,
        "files": pins,
        "jobs": worker.path_jobs(),
        "temperatures": worker.temperatures().tolist(),
        "max_new_sampler_call_slots": 32,
        "parent_calls_charged": 77,
        "global_call_ceiling": 248,
        "source": worker.SOURCE,
        "output": worker.OUTPUT,
        "store": worker.STORE,
        "per_node_seconds": 600,
        "whole_active_allocation_seconds": 1200,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
    }
    write_json(root / worker.GATE, gate)
    monkeypatch.setattr(
        worker, "load_lanes", lambda root: ({"NCEI-native-duration": lane}, {"frozen": "fixture"})
    )
    monkeypatch.setattr(
        worker, "bridge_indices", lambda *args: (train, SimpleNamespace(test=whole))
    )
    return gate, lane, train, whole


def test_admitted_design_purges_all80_and_powers_only49(tmp_path, monkeypatch):
    _, lane, train, whole = admitted_fixture(tmp_path, monkeypatch)
    design = worker.load_design(tmp_path)
    np.testing.assert_array_equal(design["train"], train)
    np.testing.assert_array_equal(design["held"], whole[:49])
    assert not set(design["train"]) & set(whole)
    assert {lane.event_ids[int(i)] for i in design["held"]} == {worker.EVENT}


@pytest.mark.parametrize("missing", ["stop_closure", "raw02", "predictions", "worker"])
def test_admission_requires_source_before_outcome_loader(tmp_path, monkeypatch, missing):
    gate, _, _, _ = admitted_fixture(tmp_path, monkeypatch)
    if missing == "stop_closure":
        # The file remains hash-pinned in the gate, but is omitted from inherited closure.
        stop = json.loads((tmp_path / worker.STOP_REVIEW).read_text())
        stop["files"].pop("contract.toml")
        write_json(tmp_path / worker.STOP_REVIEW, stop)
        gate["files"][worker.STOP_REVIEW] = sha256(tmp_path / worker.STOP_REVIEW)
    else:
        key = {
            "raw02": f"{worker.ORIGINAL_STORE}/02-augmented.nc",
            "predictions": f"{worker.SOURCE}/held-out-record-predictions.csv",
            "worker": "worker.py",
        }[missing]
        gate["files"].pop(key)
    write_json(tmp_path / worker.GATE, gate)

    def forbidden(*args):
        raise AssertionError("outcomes remain unopened")

    monkeypatch.setattr(worker, "load_lanes", forbidden)
    with pytest.raises(ValueError):
        worker.load_design(tmp_path)


def test_related_event_in_training_is_rejected(tmp_path, monkeypatch):
    _, _, train, whole = admitted_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker,
        "bridge_indices",
        lambda *args: (np.r_[train[:-1], whole[50]], SimpleNamespace(test=whole)),
    )
    with pytest.raises(ValueError, match="all80purged"):
        worker.load_design(tmp_path)


def test_endpoint_index_and_literal_target_role_are_bound(tmp_path):
    with pytest.raises(ValueError, match="node0 or16"):
        worker.read_endpoint(tmp_path, {}, 1)
    folder = tmp_path / worker.SOURCE / "ensembles" / "01-augmented"
    raw = tmp_path / worker.ORIGINAL_STORE / "01-augmented.nc"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"literal endpoint")
    write_json(tmp_path / worker.SOURCE / "job.json", {"seed": 2856129800})
    wrong = {"seed": 2856129802, "event": "usp000f2ab", "phase": "augmented"}
    write_json(folder / "job.json", wrong)
    write_json(
        folder / "result.json",
        {
            "posterior": str(raw.relative_to(tmp_path)),
            "posterior_sha256": sha256(raw),
            "job": wrong,
            "scope": "augmented_normalization_only_not_prediction",
            "records": 1006,
            "diagnostics": {"screen_passed": True},
        },
    )
    with pytest.raises(ValueError, match="clean original endpoint"):
        worker.read_endpoint(tmp_path, {"files": {str(raw.relative_to(tmp_path)): sha256(raw)}}, 16)


@pytest.mark.parametrize("node", [0, 16])
def test_literal_original_endpoint_positive_replay(tmp_path, monkeypatch, node):
    design, _, _, sample_raw = fixture(tmp_path, monkeypatch)
    tree = worker.pm.sample()
    lane = grouped_lane()
    count = 1064
    distance = np.full(count, 1000.0)
    response = np.full(count, 0.2)
    reference = np.full(count, lane.reference_minutes[0])
    lane = replace(
        lane,
        rows=tuple({} for _ in range(count)),
        record_ids=tuple(f"r{i}" for i in range(count)),
        event_ids=tuple(
            ["train"] * 984 + [worker.EVENT] * 49 + ["usp000f2ab"] * 22 + ["usp000gsmz"] * 9
        ),
        distance_km=distance,
        response=response,
        reference_minutes=reference,
        y=np.exp(response) * reference,
        x=np.zeros(count),
        included=np.ones(count, dtype=bool),
    )
    design.update(lane=lane, train=np.arange(984), held=np.arange(984, 1033))
    ids = design["train"] if node == 0 else np.arange(1033)
    name = "00-training" if node == 0 else "01-augmented"
    raw = tmp_path / worker.ORIGINAL_STORE / f"{name}.nc"
    raw.parent.mkdir(parents=True)
    tree["observed_data"] = xr.DataTree(
        xr.Dataset(
            {
                "response": (("record",), lane.response[ids]),
                "native_minutes": (("record",), lane.y[ids]),
            },
            coords={"record": [lane.record_ids[int(i)] for i in ids]},
        )
    )
    tree.to_netcdf(raw)
    tree.close()
    parent = {"seed": 2856129800}
    spec = {
        **parent,
        "seed": 2856129800 + (0 if node == 0 else 1),
        "phase": "training" if node == 0 else "augmented",
        "event": None if node == 0 else worker.EVENT,
    }
    role = (
        "training_prediction_and_normalization"
        if node == 0
        else "augmented_normalization_only_not_prediction"
    )
    folder = tmp_path / worker.SOURCE / "ensembles" / name
    write_json(tmp_path / worker.SOURCE / "job.json", parent)
    write_json(folder / "job.json", spec)
    write_json(
        folder / "membership.json",
        {"included": [lane.record_ids[int(i)] for i in ids], "role": role},
    )
    write_json(
        folder / "result.json",
        {
            "posterior": str(raw.relative_to(tmp_path)),
            "posterior_sha256": sha256(raw),
            "job": spec,
            "scope": role,
            "records": len(ids),
            "diagnostics": {"screen_passed": True},
        },
    )
    design["files"][str(raw.relative_to(tmp_path))] = sha256(raw)
    values, digest = worker.read_endpoint(tmp_path, design, node)
    assert values.shape == (4, 2000) and np.isfinite(values).all() and digest == sha256(raw)
    assert not sample_raw.exists()


def test_positive_sampler_receives_frozen_kwargs(tmp_path, monkeypatch):
    _, job, output, raw = fixture(tmp_path, monkeypatch)
    sample = worker.pm.sample
    seen = {}

    def exact(**kwargs):
        seen.update(kwargs)
        return sample(**kwargs)

    monkeypatch.setattr(worker.pm, "sample", exact)
    worker.sample_node(tmp_path, job, output, raw)
    assert seen == {
        "draws": 2000,
        "tune": 1000,
        "chains": 4,
        "cores": 2,
        "target_accept": 0.95,
        "random_seed": job["seed"],
        "progressbar": False,
    }


def test_source_closure_follows_package_imports_without_unrelated_lazy_lanes(tmp_path):
    worker_path = tmp_path / "analysis/arrival/model_curvature_sumatra_path_sampling.py"
    worker_path.parent.mkdir(parents=True)
    worker_path.write_text("from scripts import needed\ndef unused():\n import scripts.future\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "needed.py").write_text("from analysis.arrival.narrow import helper\n")
    (scripts / "future.py").write_text("raise RuntimeError('must stay unconsumed')\n")
    (worker_path.parent / "narrow.py").write_text("helper = 1\n")
    files = worker.consumed_source_files(tmp_path)
    assert "scripts/needed.py" in files and "analysis/arrival/narrow.py" in files
    assert "scripts/future.py" not in files
