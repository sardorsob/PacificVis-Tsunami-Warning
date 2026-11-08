"""Frozen numerical path nodes, with the original curvature endpoints preserved."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge_sampling import bridge_indices
from analysis.arrival.model_curvature_path import build_curvature_path, curvature_held_loglikelihood
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_curvature_sequence import CONSUMED as ORIGINAL_CONSUMED
from analysis.arrival.model_curvature_sequence import GATE as ORIGINAL_GATE
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_validation import sampling_diagnostics

GATE = "artifacts/models/arrival-timing/mean-curvature-path-design-v1/review-acceptance.json"
SOURCE = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/jobs/fold-002"
STOP_REVIEW = (
    "artifacts/models/arrival-timing/mean-curvature-sequence-v1/numerical-stop-review.json"
)
OUTPUT = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/resolutions/fold-002-path-v1"
STORE = "data/processed/models/mean-curvature-sequence-v1/resolution-fold-002-path-v1"
CONSUMED = sorted(
    set(
        [
            *ORIGINAL_CONSUMED,
            ORIGINAL_GATE,
            STOP_REVIEW,
            "analysis/arrival/model_curvature_path.py",
            "analysis/arrival/model_curvature_path_sampling.py",
            "analysis/arrival/model_bridge_path.py",
            "scripts/sample_arrival_curvature_path.py",
            "scripts/run_arrival_curvature_path.py",
        ]
    )
)


def temperatures():
    return (np.arange(17, dtype=float) / 16) ** 2


def path_jobs():
    return [
        {
            "id": f"{role}-node-{j:02d}",
            "path_role": role,
            "node": j,
            "temperature": float(temperatures()[j]),
            "target": "NCEI-native-duration",
            "kind": "mean-curvature",
            "prior": "base",
            "sequence": "seq-official20110311054624120_30",
            "event_id": "official20110311054624120_30",
            "draws": 2000,
            "tune": 1000,
            "cores": 2,
            "seed": 2856112900 + (0 if role == "primary" else 50) + j,
        }
        for role, nodes in [("primary", range(1, 16)), ("repeat", range(17))]
        for j in nodes
    ]


def load_design(root):
    gate = json.loads((root / GATE).read_text())
    if (
        gate.get("status") != "accepted_curvature_path_resolution"
        or gate.get("independent_checker") is not True
        or gate.get("jobs") != path_jobs()
        or gate.get("temperatures") != temperatures().tolist()
        or gate.get("max_new_sampler_call_slots") != 32
        or gate.get("parent_calls_charged") != 6
        or gate.get("global_call_ceiling") != 248
        or gate.get("output") != OUTPUT
        or gate.get("store") != STORE
        or gate.get("source") != SOURCE
        or gate.get("per_node_seconds") != 600
        or gate.get("whole_active_allocation_seconds") != 1200
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not set(CONSUMED).issubset(gate.get("files", {}))
    ):
        raise ValueError("independent fixed32call curvature path design required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for p, h in pins.items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("path design source changed")
    stop_review = json.loads((root / STOP_REVIEW).read_text())
    if (
        stop_review.get("status") != "accepted_fold001_retained_fold002_numerical_stop"
        or stop_review.get("independent_checker") is not True
        or not stop_review.get("files")
        or any(pins.get(p) != h for p, h in stop_review["files"].items())
    ):
        raise ValueError("complete independent numerical stop closure required")
    original_plan = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/plan.json"
    if original_plan not in pins:
        raise ValueError("reviewed parent plan required before outcome loading")
    plan = json.loads((root / original_plan).read_text())
    if not plan.get("files") or any(pins.get(p) != h for p, h in plan["files"].items()):
        raise ValueError("complete original source closure before outcome loading required")
    for p in (root / SOURCE).rglob("*"):
        if p.is_file() and str(p.relative_to(root)) not in pins:
            raise ValueError("reviewed failed attempt required before parsing")
    result = json.loads((root / SOURCE / "result.json").read_text())
    job = result["job"]
    if (
        result.get("status") != "precision_failure"
        or result.get("prediction_precision_passed") is not True
        or job != plan["cases"][2]
        or result.get("sampler_calls_started") != 2
        or len(result.get("events", [])) != 1
        or result["events"][0]["precision_passed"] is not False
    ):
        raise ValueError("same-model retained failed endpoint bridge required")
    lanes, frozen = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    train, fold = bridge_indices(lane, job["sequence"], "training", None)
    held = fold.test
    if len(held) != 271 or len({lane.event_ids[int(i)] for i in held}) != 1:
        raise ValueError("exact retained271record held event required")
    return {
        "gate": gate,
        "files": pins,
        "lane": lane,
        "train": train,
        "held": held,
        "source_files": frozen,
    }


def read_endpoint(root, design, node):
    name = "00-training" if node == 0 else "01-augmented"
    result = json.loads((root / SOURCE / "ensembles" / name / "result.json").read_text())
    raw = checked_path(root, result["posterior"])
    if (
        design["files"].get(str(raw.relative_to(root))) != sha256(raw)
        or not result["diagnostics"]["screen_passed"]
    ):
        raise ValueError("reviewed clean original endpoint required")
    ids = design["train"] if node == 0 else np.sort(np.r_[design["train"], design["held"]])
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as data:
        if data.record.values.tolist() != [design["lane"].record_ids[int(i)] for i in ids]:
            raise ValueError("original endpoint IDs changed")
        np.testing.assert_array_equal(data.response.values, design["lane"].response[ids])
        np.testing.assert_array_equal(data.native_minutes.values, design["lane"].y[ids])
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as data:
        posterior = data.load()
    return curvature_held_loglikelihood(design["lane"], design["held"], posterior), result[
        "posterior_sha256"
    ]


def sample_node(root, job, output, store):
    if (
        job not in path_jobs() or output.exists() or store.exists()
        or store.with_suffix(".loglikelihood.npz").exists()
    ):
        raise ValueError("exact new frozen curvature path job required")
    design = load_design(root)
    if output != root / OUTPUT / "jobs" / job["id"] or store != root / STORE / (job["id"] + ".nc"):
        raise ValueError("canonical bound node output and raw paths required")
    lane, train, held = [design[k] for k in ["lane", "train", "held"]]
    model = build_curvature_path(
        lane, read_curvature_prior(root, "base"), train, held, job["temperature"]
    )
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "files": design["files"],
            "source_files": design["source_files"],
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    )
    write_json(
        output / "membership.json",
        {
            "training": [lane.record_ids[int(i)] for i in train],
            "integration_held": [lane.record_ids[int(i)] for i in held],
            "temperature": job["temperature"],
            "scope": "numerical_integration_only_never_training_forecast",
        },
    )
    write_json(output / "sampling-start.json", job)
    with model:
        tree = pm.sample(
            draws=2000,
            tune=1000,
            chains=4,
            cores=2,
            target_accept=0.95,
            random_seed=job["seed"],
            progressbar=False,
        )
    for group, dim, ids in [
        ("observed_data", "record", train),
        ("integration_held_data", "held_record", held),
    ]:
        tree[group] = xr.DataTree(
            xr.Dataset(
                {"response": ((dim,), lane.response[ids]), "native_minutes": ((dim,), lane.y[ids])},
                coords={dim: [lane.record_ids[int(i)] for i in ids]},
                attrs={
                    "scope": "numerical_integration_device",
                    "likelihood_power": job["temperature"]
                    if group == "integration_held_data"
                    else 1.0,
                },
            )
        )
    tree.to_netcdf(store)
    diagnostics, table = sampling_diagnostics(tree)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    posterior = cast(Any, tree["posterior"])
    status = (
        "node_computed_pending_review" if diagnostics["screen_passed"] else "diagnostic_failure"
    )
    if "nutpie" not in str(posterior.attrs).lower():
        status = "backend_failure"
    result = {
        "job": job,
        "status": status,
        "diagnostics": diagnostics,
        "posterior": str(store.relative_to(root)),
        "posterior_sha256": sha256(store),
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
    }
    if status == "node_computed_pending_review":
        values = curvature_held_loglikelihood(lane, held, posterior)
        raw = store.with_suffix(".loglikelihood.npz")
        with raw.open("xb") as stream:
            np.savez_compressed(stream, held_loglikelihood=values)
        result.update(
            held_loglikelihood=str(raw.relative_to(root)),
            held_loglikelihood_sha256=sha256(raw),
            likelihood_measure="log_ratio_response_explicit_alpha_beta_gamma_new_u_integrated",
        )
    write_json(output / "result.json", result)
    tree.close()
    if any(sha256(root / p) != h for p, h in design["files"].items()):
        raise ValueError("path node source drift")


def read_node(root, job, design):
    folder = root / OUTPUT / "jobs" / job["id"]
    result = json.loads((folder / "result.json").read_text())
    inputs = json.loads((folder / "inputs.json").read_text())
    expected = {
        "training": [design["lane"].record_ids[int(i)] for i in design["train"]],
        "integration_held": [design["lane"].record_ids[int(i)] for i in design["held"]],
        "temperature": job["temperature"],
        "scope": "numerical_integration_only_never_training_forecast",
    }
    if (
        result.get("status") != "node_computed_pending_review"
        or result.get("job") != job
        or not result["diagnostics"]["screen_passed"]
        or inputs.get("files") != design["files"]
        or inputs.get("source_files") != design["source_files"]
        or json.loads((folder / "job.json").read_text()) != job
        or json.loads((folder / "sampling-start.json").read_text()) != job
        or json.loads((folder / "membership.json").read_text()) != expected
    ):
        raise ValueError("complete path node identity/diagnostics required")
    raw = root / STORE / (job["id"] + ".nc")
    array = raw.with_suffix(".loglikelihood.npz")
    if (
        result.get("posterior") != str(raw.relative_to(root))
        or sha256(raw) != result["posterior_sha256"]
        or result.get("held_loglikelihood") != str(array.relative_to(root))
        or sha256(array) != result["held_loglikelihood_sha256"]
    ):
        raise ValueError("node raw evidence changed")
    for group, dim, ids in [
        ("observed_data", "record", design["train"]),
        ("integration_held_data", "held_record", design["held"]),
    ]:
        with xr.open_dataset(raw, group=group, engine="h5netcdf") as data:
            if data[dim].values.tolist() != [design["lane"].record_ids[int(i)] for i in ids]:
                raise ValueError("node record IDs changed")
            np.testing.assert_array_equal(data.response.values, design["lane"].response[ids])
            np.testing.assert_array_equal(data.native_minutes.values, design["lane"].y[ids])
            if data.attrs["likelihood_power"] != (
                job["temperature"] if group == "integration_held_data" else 1.0
            ):
                raise ValueError("node temperature changed")
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as data:
        post = data.load()
    if post.alpha.shape != (4, 2000):
        raise ValueError("four chains/two thousand draws required")
    expected_log = curvature_held_loglikelihood(design["lane"], design["held"], post)
    with np.load(array) as saved:
        values = saved["held_loglikelihood"]
    np.testing.assert_allclose(values, expected_log, rtol=0, atol=1e-10)
    return values
