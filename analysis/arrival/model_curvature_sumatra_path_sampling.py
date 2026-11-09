"""Frozen numerical path nodes, with the original curvature endpoints preserved."""

# pyright: basic
from __future__ import annotations

import ast
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

GATE = (
    "artifacts/models/arrival-timing/mean-curvature-sumatra-path-design-v1/review-acceptance.json"
)
SOURCE = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/jobs/fold-019"
STOP_REVIEW = (
    "artifacts/models/arrival-timing/mean-curvature-sequence-v1/"
    "continuation-v2/numerical-stop-review.json"
)
OUTPUT = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/resolutions/fold-019-path-v1"
STORE = "data/processed/models/mean-curvature-sequence-v1/resolution-fold-019-path-v1"
ORIGINAL_PLAN = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/plan.json"
ORIGINAL_STORE = "data/processed/models/mean-curvature-sequence-v1/fold-019"
EVENT = "usp000exfn"
SEQUENCE = "seq-usp000exfn"
STOP_PIN_COUNT = 2980
CONSUMED = sorted(
    set(
        [
            *ORIGINAL_CONSUMED,
            ORIGINAL_GATE,
            "scripts/run_arrival_model_validation.py",
            STOP_REVIEW,
            "analysis/arrival/model_curvature_path.py",
            "analysis/arrival/model_curvature_sumatra_path_sampling.py",
            "analysis/arrival/model_bridge_path.py",
            "scripts/sample_arrival_curvature_sumatra_path.py",
            "scripts/run_arrival_curvature_sumatra_path.py",
            "scripts/check_arrival_curvature_sumatra_path.py",
            "artifacts/models/arrival-timing/mean-curvature-sumatra-path-design-v1/"
            "numerical-oracles.json",
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
            "sequence": "seq-usp000exfn",
            "event_id": "usp000exfn",
            "draws": 2000,
            "tune": 1000,
            "cores": 2,
            "seed": 2876129900 + (0 if role == "primary" else 50) + j,
        }
        for role, nodes in [("primary", range(1, 16)), ("repeat", range(17))]
        for j in nodes
    ]


def consumed_source_files(root):
    """Pin module-level runtime imports; inherited receipts own historical closure."""
    pending = [
        "analysis/arrival/model_curvature_sumatra_path_sampling.py",
        "scripts/sample_arrival_curvature_sumatra_path.py",
        "scripts/run_arrival_curvature_sumatra_path.py",
        "scripts/check_arrival_curvature_sumatra_path.py",
    ]
    found = set(CONSUMED)
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited or not (root / name).is_file():
            continue
        visited.add(name)
        for node in ast.parse((root / name).read_text(encoding="utf-8")).body:
            modules = (
                [node.module, *[node.module + "." + alias.name for alias in node.names]]
                if isinstance(node, ast.ImportFrom) and node.module
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for module in modules:
                path = module.replace(".", "/") + ".py"
                if path not in visited and (root / path).is_file():
                    found.add(path)
                    pending.append(path)
    return sorted(found)


def required_original_files():
    """Literal retained artifacts, including all four original ensembles."""
    files = [
        ORIGINAL_PLAN,
        ORIGINAL_GATE,
        *[
            f"{SOURCE}/{name}"
            for name in [
                "result.json",
                "job.json",
                "membership.json",
                "inputs.json",
                "held-out-record-predictions.csv",
                "event-joint-scores.csv",
                "attempt-evidence.json",
            ]
        ],
        f"{ORIGINAL_STORE}/bridge-arrays.npz",
    ]
    for index, phase in enumerate(["training", "augmented", "augmented", "augmented"]):
        name = f"{index:02d}-{phase}"
        files += [f"{ORIGINAL_STORE}/{name}.nc", f"{SOURCE}/sampling-starts/{index:02d}.json"]
        files += [
            f"{SOURCE}/ensembles/{name}/{leaf}"
            for leaf in [
                "result.json",
                "job.json",
                "membership.json",
                "inputs.json",
                "sampling-diagnostics.csv",
            ]
        ]
    return files


def load_design(root):
    gate = json.loads((root / GATE).read_text())
    if (
        gate.get("status") != "accepted_curvature_sumatra_path_resolution"
        or gate.get("independent_checker") is not True
        or gate.get("jobs") != path_jobs()
        or gate.get("temperatures") != temperatures().tolist()
        or gate.get("max_new_sampler_call_slots") != 32
        or gate.get("parent_calls_charged") != 77
        or gate.get("global_call_ceiling") != 248
        or gate.get("output") != OUTPUT
        or gate.get("store") != STORE
        or gate.get("source") != SOURCE
        or gate.get("per_node_seconds") != 600
        or gate.get("whole_active_allocation_seconds") != 1200
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not set(consumed_source_files(root)).issubset(gate.get("files", {}))
        or not set(required_original_files()).issubset(gate.get("files", {}))
    ):
        raise ValueError("independent fixed32call curvature path design required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for p, h in pins.items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("path design source changed")
    stop_review = json.loads((root / STOP_REVIEW).read_text())
    if (
        stop_review.get("status") != "accepted_curvature_completion_overlap_stop"
        or stop_review.get("independent_checker") is not True
        or len(stop_review.get("files", {})) != STOP_PIN_COUNT
        or stop_review.get("calls_charged") != 77
        or stop_review.get("calls_started") != 77
        or stop_review.get("failed_event") != EVENT
        or stop_review.get("quarantined_case") != "fold-019"
        or stop_review.get("confirmation_outcomes_parsed") is not False
        or stop_review.get("reserved_outcomes") != "sealed"
        or any(pins.get(p) != h for p, h in stop_review["files"].items())
    ):
        raise ValueError("complete independent numerical stop closure required")
    original_plan = ORIGINAL_PLAN
    if original_plan not in pins:
        raise ValueError("reviewed parent plan required before outcome loading")
    plan = json.loads((root / original_plan).read_text())
    if not plan.get("files") or any(pins.get(p) != h for p, h in plan["files"].items()):
        raise ValueError("complete original source closure before outcome loading required")
    original_gate = json.loads((root / ORIGINAL_GATE).read_text())
    if (
        original_gate.get("status") != "accepted_curvature_sequence_rehearsal"
        or original_gate.get("independent_checker") is not True
        or original_gate.get("max_sampler_call_slots") != 248
        or not set(ORIGINAL_CONSUMED).issubset(original_gate.get("files", {}))
        or any(pins.get(p) != h for p, h in original_gate.get("files", {}).items())
    ):
        raise ValueError("complete original worker gate/source closure required")
    for p in (root / SOURCE).rglob("*"):
        if p.is_file() and str(p.relative_to(root)) not in pins:
            raise ValueError("reviewed failed attempt required before parsing")
    result = json.loads((root / SOURCE / "result.json").read_text())
    job = result["job"]
    if (
        result.get("status") != "precision_failure"
        or result.get("prediction_precision_passed") is not True
        or job != plan["cases"][19]
        or job not in original_gate.get("cases", [])
        or job.get("id") != "fold-019"
        or job.get("sequence") != SEQUENCE
        or result.get("sampler_calls_started") != 4
        or result.get("training_records") != 984
        or result.get("heldout_records") != 80
        or result.get("confirmation_outcomes_parsed") is not False
        or result.get("reserved_outcomes") != "sealed"
        or [
            (e.get("event_id"), e.get("records"), e.get("precision_passed"))
            for e in result.get("events", [])
        ]
        != [(EVENT, 49, False), ("usp000f2ab", 22, True), ("usp000gsmz", 9, True)]
        or result.get("bridge_arrays") != f"{ORIGINAL_STORE}/bridge-arrays.npz"
        or pins.get(result["bridge_arrays"]) != result.get("bridge_arrays_sha256")
        or json.loads((root / SOURCE / "job.json").read_text()) != job
    ):
        raise ValueError("same-model retained failed endpoint bridge required")
    source_inputs = []
    for folder in [root / SOURCE, *sorted((root / SOURCE / "ensembles").iterdir())]:
        inputs = json.loads((folder / "inputs.json").read_text())
        if not set([*ORIGINAL_CONSUMED, ORIGINAL_GATE]).issubset(inputs.get("files", {})) or any(
            pins.get(p) != h for p, h in inputs.get("files", {}).items()
        ):
            raise ValueError("original attempt worker input closure required before outcomes")
        source_inputs.append(inputs)
    lanes, frozen = load_lanes(root)
    if any(inputs.get("source_files") != frozen for inputs in source_inputs):
        raise ValueError("original attempt source identities changed")
    lane = lanes["NCEI-native-duration"]
    train, fold = bridge_indices(lane, job["sequence"], "training", None)
    held = np.asarray([i for i in fold.test if lane.event_ids[int(i)] == EVENT], dtype=int)
    events = [lane.event_ids[int(i)] for i in fold.test]
    membership = json.loads((root / SOURCE / "membership.json").read_text())
    if (
        len(train) != 984
        or len(fold.test) != 80
        or len(held) != 49
        or {event: events.count(event) for event in set(events)}
        != {EVENT: 49, "usp000f2ab": 22, "usp000gsmz": 9}
        or set(train) & set(fold.test)
        or {lane.event_ids[int(i)] for i in train} & set(events)
        or membership
        != {
            "train": [lane.record_ids[int(i)] for i in train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": SEQUENCE,
        }
    ):
        raise ValueError("exact984train/all80purged/49target-only held membership required")
    return {
        "gate": gate,
        "files": pins,
        "lane": lane,
        "train": train,
        "held": held,
        "source_files": frozen,
    }


def read_endpoint(root, design, node):
    if node not in (0, 16) or type(node) is not int:
        raise ValueError("literal original endpoint node0 or16 required")
    name = "00-training" if node == 0 else "01-augmented"
    result = json.loads((root / SOURCE / "ensembles" / name / "result.json").read_text())
    literal = f"{ORIGINAL_STORE}/{name}.nc"
    raw = checked_path(root, literal)
    parent_job = json.loads((root / SOURCE / "job.json").read_text())
    expected_job = {
        **parent_job,
        "phase": "training" if node == 0 else "augmented",
        "event": None if node == 0 else EVENT,
        "seed": parent_job["seed"] + (0 if node == 0 else 1),
    }
    role = (
        "training_prediction_and_normalization"
        if node == 0
        else "augmented_normalization_only_not_prediction"
    )
    if (
        result.get("posterior") != literal
        or result.get("posterior_sha256") != sha256(raw)
        or result.get("job") != expected_job
        or result.get("scope") != role
        or result.get("records") != (984 if node == 0 else 1033)
        or json.loads((root / SOURCE / "ensembles" / name / "job.json").read_text()) != expected_job
        or design["files"].get(str(raw.relative_to(root))) != sha256(raw)
        or not result["diagnostics"]["screen_passed"]
    ):
        raise ValueError("reviewed clean original endpoint required")
    ids = design["train"] if node == 0 else np.sort(np.r_[design["train"], design["held"]])
    folder = root / SOURCE / "ensembles" / name
    if json.loads((folder / "membership.json").read_text()) != {
        "included": [design["lane"].record_ids[int(i)] for i in ids],
        "role": role,
    }:
        raise ValueError("literal endpoint training/target-only augmentation required")
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as data:
        if data.record.values.tolist() != [design["lane"].record_ids[int(i)] for i in ids]:
            raise ValueError("original endpoint IDs changed")
        np.testing.assert_array_equal(data.response.values, design["lane"].response[ids])
        np.testing.assert_array_equal(data.native_minutes.values, design["lane"].y[ids])
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as data:
        posterior = data.load()
    validate_posterior(posterior)
    return curvature_held_loglikelihood(design["lane"], design["held"], posterior), result[
        "posterior_sha256"
    ]


def validate_posterior(posterior):
    """Require the reviewed backend and all seven finite sampled coordinates."""
    if "nutpie" not in str(posterior.attrs).lower():
        raise ValueError("nutpie posterior backend required")
    for name in ["alpha", "beta", "gamma", "tau_event", "sigma_anchor"]:
        data = posterior[name]
        shape = (4, 2000, 3) if name == "sigma_anchor" else (4, 2000)
        dims = ("chain", "draw", "scale_anchor_km") if name == "sigma_anchor" else ("chain", "draw")
        if data.shape != shape or data.dims != dims or not np.isfinite(data.values).all():
            raise ValueError("four chains/two thousand draws/all seven coordinates required")
    if not np.array_equal(posterior.scale_anchor_km.values, [500, 2000, 5000]):
        raise ValueError("frozen residual anchor order required")


def sample_node(root, job, output, store):
    if (
        job not in path_jobs()
        or output.exists()
        or store.exists()
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
    if status == "node_computed_pending_review":
        try:
            validate_posterior(posterior)
        except ValueError:
            status = "posterior_shape_failure"
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
    if job not in path_jobs():
        raise ValueError("exact frozen path job required")
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
        or result.get("confirmation_outcomes_parsed") is not False
        or result.get("reserved_outcomes") != "sealed"
        or result.get("likelihood_measure")
        != "log_ratio_response_explicit_alpha_beta_gamma_new_u_integrated"
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
    validate_posterior(post)
    expected_log = curvature_held_loglikelihood(design["lane"], design["held"], post)
    with np.load(array) as saved:
        values = saved["held_loglikelihood"]
    if values.shape != (4, 2000) or not np.isfinite(values).all():
        raise ValueError("finite four-chain held likelihood cache required")
    np.testing.assert_allclose(values, expected_log, rtol=0, atol=1e-10)
    return values
