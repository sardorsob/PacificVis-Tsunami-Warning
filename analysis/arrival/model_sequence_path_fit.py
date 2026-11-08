"""Reviewed sixteen-edge squared paths for one held NCEI event; no statistical change."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge_cv import CONSUMED as BRIDGE_CONSUMED
from analysis.arrival.model_bridge_cv import _read_ensemble, verify_bridge_gate
from analysis.arrival.model_bridge_path import build_path_model, path_held_loglikelihood
from analysis.arrival.model_bridge_path_fit import CONSUMED as LEGACY_CONSUMED
from analysis.arrival.model_bridge_path_fit import PATH_GATE as LEGACY_GATE
from analysis.arrival.model_bridge_path_fit import verify_path_gate
from analysis.arrival.model_bridge_sampling import bridge_indices
from analysis.arrival.model_cv import verify_prediction_gate
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.models import read_prior

CONSUMED = sorted(
    set(
        [
            *BRIDGE_CONSUMED,
            *LEGACY_CONSUMED,
            LEGACY_GATE,
            "analysis/arrival/model_sequence_path_fit.py",
            "analysis/arrival/model_path_fold_resolution.py",
            "scripts/run_arrival_sequence_path.py",
            "scripts/sample_arrival_sequence_path.py",
        ]
    )
)


def fixed_temperatures():
    return (np.arange(17, dtype=float) / 16) ** 2


def path_jobs(spec):
    return [
        {
            "path_role": role,
            "node": i,
            "temperature": float(fixed_temperatures()[i]),
            "target": "NCEI-native-duration",
            "kind": "distance-scale",
            "prior": "base",
            "sequence": spec["sequence"],
            "event": spec["event_id"],
            "draws": 2000,
            "tune": 1000,
            "cores": 2,
            "seed": spec["seed_base"] + (0 if role == "primary" else 50) + i,
        }
        for role, nodes in [("primary", range(1, 16)), ("repeat", range(17))]
        for i in nodes
    ]


def validated_design(root, manifest):
    manifest = checked_path(root, str(manifest))
    spec = json.loads(manifest.read_text())
    if (
        spec.get("schema_version") != "arrival_squared_sequence_path_v1"
        or spec.get("status") != "accepted_for_frozen_path"
        or not spec.get("numerical_checker")
        or not spec.get("runtime_checker")
        or spec.get("reserved_outcomes") != "sealed"
        or spec.get("temperatures") != fixed_temperatures().tolist()
        or spec.get("max_new_sampler_calls") != 32
        or type(spec.get("seed_base")) is not int
        or not 0 <= spec["seed_base"] <= 2**32 - 100
        or not set(CONSUMED) <= set(spec.get("files", {}))
    ):
        raise ValueError("reviewed fixed thirty-two-call squared-path manifest required")
    for p, h in spec["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("path design identity changed")
    verify_path_gate(root, root / LEGACY_GATE)
    source = checked_path(root, spec["source_fold"])
    original = json.loads((source / "result.json").read_text())
    job = original["job"]
    required = [
        source / name
        for name in [
            "result.json",
            "inputs.json",
            "membership.json",
            "held-out-record-predictions.csv",
        ]
    ]
    required.append(checked_path(root, original["bridge_arrays"]))
    if any(spec["files"].get(str(p.relative_to(root))) != sha256(p) for p in required):
        raise ValueError("immutable failed-fold evidence must remain pinned")
    if (
        job["target"] != "NCEI-native-duration"
        or job["kind"] != "distance-scale"
        or job["prior"] != "base"
        or job["sequence"] != spec["sequence"]
        or original["status"] != "precision_failure"
        or not original["prediction_precision_passed"]
    ):
        raise ValueError("same-model unresolved score and clean predictions required")
    verify_bridge_gate(root, root / job["bridge_gate"], job["target"], job["kind"])
    verify_prediction_gate(root, root / job["gate"], job["target"], job["kind"])
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    train, fold = bridge_indices(lane, job["sequence"], "training", None)
    events = sorted({lane.event_ids[int(i)] for i in fold.test})
    if spec["event_id"] not in events:
        raise ValueError("one held event required")
    held = np.array([int(i) for i in fold.test if lane.event_ids[int(i)] == spec["event_id"]])
    old = next(e for e in original["events"] if e["event_id"] == spec["event_id"])
    if old["precision_passed"]:
        raise ValueError("an unresolved held integral required")
    endpoints = {}
    metadata = []
    for k, phase, event, ids in [
        (0, "training", None, train),
        (
            events.index(spec["event_id"]) + 1,
            "augmented",
            spec["event_id"],
            np.sort(np.r_[train, held]),
        ),
    ]:
        folder = source / "ensembles" / f"{k:02d}-{phase}"
        source_job = {**job, "phase": phase, "event": event, "seed": job["seed"] + k}
        saved, posterior, _ = _read_ensemble(root, folder, source_job, lane, ids, frozen)
        if not saved["diagnostics"]["screen_passed"]:
            raise ValueError("clean source endpoint required")
        for p in [folder / "result.json", folder / "inputs.json", root / saved["posterior"]]:
            name = str(p.relative_to(root))
            if spec["files"].get(name) != sha256(p):
                raise ValueError("source endpoint must remain pinned")
        node = 0 if phase == "training" else 16
        endpoints[("primary", node)] = path_held_loglikelihood(lane, held, posterior)
        metadata.append(
            {
                "node": node,
                "posterior": saved["posterior"],
                "posterior_sha256": saved["posterior_sha256"],
                "seed": source_job["seed"],
            }
        )
    parent = checked_path(root, spec["parent_output"])
    parent_plan = json.loads((parent / "plan.json").read_text())
    snapshot_path = checked_path(root, spec["budget_snapshot"])
    if (
        str(snapshot_path.relative_to(root)) not in spec["files"]
        or str((parent / "plan.json").relative_to(root)) not in spec["files"]
    ):
        raise ValueError("immutable parent plan and copied budget evidence required")
    budget = json.loads(snapshot_path.read_text())
    if (
        budget["status"] != "needs_review"
        or budget["global_calls_reserved"] != spec["parent_call_slots"]
        or parent_plan["global_call_ceiling"] != 352
        or spec["global_call_ceiling"] != 352
        or spec["parent_call_slots"] + 32 > 352
        or spec["prior_raw_stores"] != [*parent_plan["prior_raw_stores"], parent_plan["raw_store"]]
        or spec["external_endpoint"] != parent_plan["external_endpoint"]
        or spec["max_raw_bytes"] != parent_plan["max_posterior_bytes"]
    ):
        raise ValueError("original global call and storage budgets required")
    if set(j["seed"] for j in path_jobs(spec)) & set(parent_plan["original_seed_channels"]):
        raise ValueError("path sampling streams overlap source validation streams")
    return {
        "spec": spec,
        "lane": lane,
        "train": train,
        "held": held,
        "source_files": frozen,
        "endpoint_logs": endpoints,
        "endpoint_metadata": metadata,
        "record_count": len(held),
        "jacobian": float(np.log(lane.y[held]).sum()),
        "source_result": original,
        "files": {**spec["files"], str(manifest.relative_to(root)): sha256(manifest)},
    }


def sample_sequence_path_job(root, manifest, job, output, store):
    root, manifest, output, store = [p.resolve() for p in [root, manifest, output, store]]
    if not all(p.is_relative_to(root) for p in [manifest, output, store]):
        raise ValueError("project-local manifest, output and raw paths required")
    if job not in path_jobs(json.loads(manifest.read_text())):
        raise ValueError("one exact fixed squared-path job required")
    if output.exists() or store.exists():
        raise ValueError("new node paths required")
    design = validated_design(root, manifest)
    lane, train, held, frozen = [design[k] for k in ["lane", "train", "held", "source_files"]]
    pins = design["files"]
    model = build_path_model(
        lane, read_prior(root, lane.target, "base"), train, held, job["temperature"]
    )
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "source_files": frozen,
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
            "sequence": job["sequence"],
            "held_power": job["temperature"],
            "scope": "integration_device_never_training_forecast",
        },
    )
    for p in CONSUMED:
        target = output / "source-snapshot" / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / p).read_bytes())
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
    tree["observed_data"] = xr.DataTree(
        xr.Dataset(
            {"response": (("record",), lane.response[train])},
            coords={"record": [lane.record_ids[int(i)] for i in train]},
            attrs={"scope": "training_records"},
        )
    )
    tree["integration_held_data"] = xr.DataTree(
        xr.Dataset(
            {"response": (("held_record",), lane.response[held])},
            coords={"held_record": [lane.record_ids[int(i)] for i in held]},
            attrs={"likelihood_power": job["temperature"], "scope": "integration_device_only"},
        )
    )
    tree.to_netcdf(store)
    diagnostics, table = sampling_diagnostics(tree)
    cast(Any, table).to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    write_json(output / "diagnostics.json", diagnostics)
    result = {
        "job": job,
        "diagnostics": diagnostics,
        "posterior": str(store.relative_to(root)),
        "posterior_sha256": sha256(store),
        "training_records": len(train),
        "held_records": len(held),
        "scope": "integration_device_not_statistical_candidate_or_heldout_prediction",
        "coordinates": "explicit_alpha_beta_tau_and_three_raw_SD_anchors",
        "reserved_outcomes": "sealed",
    }
    posterior = cast(Any, tree["posterior"])
    if "nutpie" not in str(posterior.attrs).lower():
        result["status"] = "backend_failure"
    elif not diagnostics["screen_passed"]:
        result["status"] = "diagnostic_failure"
    else:
        values = path_held_loglikelihood(lane, held, posterior)
        log_store = store.with_suffix(".loglikelihood.npz")
        np.savez_compressed(log_store, held_loglikelihood=values)
        result.update(
            status="node_computed_pending_review",
            held_loglikelihood=str(log_store.relative_to(root)),
            held_loglikelihood_sha256=sha256(log_store),
            likelihood_measure="model_response_given_coefficients_new_event_effect_integrated",
        )
    write_json(output / "result.json", result)
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("node sources changed during sampling")


def read_sequence_node(root, folder, job, design):
    result = json.loads((folder / "result.json").read_text())
    inputs = json.loads((folder / "inputs.json").read_text())
    if (
        result["job"] != job
        or result["status"] != "node_computed_pending_review"
        or not result["diagnostics"]["screen_passed"]
        or inputs["files"] != design["files"]
        or inputs["source_files"] != design["source_files"]
    ):
        raise ValueError("node identities or diagnostics failed")
    raw = checked_path(root, result["posterior"])
    if sha256(raw) != result["posterior_sha256"]:
        raise ValueError("node posterior changed")
    lane = design["lane"]
    for group, dim, ids in [
        ("observed_data", "record", design["train"]),
        ("integration_held_data", "held_record", design["held"]),
    ]:
        with xr.open_dataset(raw, group=group, engine="h5netcdf") as ds:
            if ds[dim].values.tolist() != [lane.record_ids[int(i)] for i in ids]:
                raise ValueError("node membership changed")
            np.testing.assert_array_equal(ds.response.values, lane.response[ids])
            if (
                group == "integration_held_data"
                and ds.attrs["likelihood_power"] != job["temperature"]
            ):
                raise ValueError("node temperature changed")
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as ds:
        post = ds.load()
    np.testing.assert_array_equal(post.scale_anchor_km.values, [500.0, 2000.0, 5000.0])
    if post.alpha.shape != (4, 2000) or any(
        not np.isfinite(post[k].values).all()
        for k in ["alpha", "beta", "tau_event", "sigma_anchor"]
    ):
        raise ValueError("finite fixed four-chain posterior required")
    if (post.tau_event.values < 0).any() or (post.sigma_anchor.values <= 0).any():
        raise ValueError("node scales outside support")
    array = checked_path(root, result["held_loglikelihood"])
    if sha256(array) != result["held_loglikelihood_sha256"]:
        raise ValueError("node logL changed")
    with np.load(array) as z:
        values = z["held_loglikelihood"]
    np.testing.assert_allclose(
        values, path_held_loglikelihood(lane, design["held"], post), rtol=0, atol=1e-10
    )
    return values
