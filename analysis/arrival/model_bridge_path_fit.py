"""Strict node jobs for the reviewed, fifteen-call Tohoku integration contingency."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge_path import build_path_model, path_held_loglikelihood
from analysis.arrival.model_cv import verify_prediction_gate
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.models import read_prior

SEQUENCE = "seq-official20110311054624120_30"
MODEL_GATE = (
    "artifacts/models/arrival-timing/distance-scale-validation-report-v1/review-acceptance.json"
)
PATH_GATE = (
    "artifacts/models/arrival-timing/bridge-path-validation-report-v1/review-acceptance.json"
)
CONSUMED = [
    "analysis/arrival/model_bridge_path_fit.py",
    "analysis/arrival/model_bridge_path.py",
    "analysis/arrival/model_bridge.py",
    "analysis/arrival/model_scoring.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/model_prediction.py",
    "analysis/arrival/model_evaluation.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_cv.py",
    "analysis/arrival/model_fit.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/model_validation_report.py",
    "analysis/arrival/models.py",
    "analysis/arrival/evidence.py",
    "scripts/sample_arrival_bridge_path.py",
    "scripts/run_arrival_bridge_path.py",
    "scripts/run_arrival_model_batch.py",
    "scripts/run_arrival_model_validation.py",
    "config/arrival-model-priors-v1.toml",
    "config/arrival-model-contract-v1.toml",
    "config/arrival-model-scoring-v1.toml",
    "pyproject.toml",
    "uv.lock",
    MODEL_GATE,
]


def path_jobs():
    return [
        {
            "path_role": role,
            "node": i,
            "temperature": i / 8,
            "target": "NCEI-native-duration",
            "kind": "distance-scale",
            "prior": "base",
            "sequence": SEQUENCE,
            "draws": 2000,
            "tune": 1000,
            "cores": 2,
            "seed": (2026110800 if role == "primary" else 2126110800) + i,
            "model_gate": MODEL_GATE,
            "path_gate": PATH_GATE,
        }
        for role, nodes in [("primary", range(1, 8)), ("repeat", range(8))]
        for i in nodes
    ]


def verify_path_gate(root, gate_path):
    gate = json.loads(gate_path.read_text())
    if (
        gate.get("schema_version") != "arrival_fixed_bridge_path_acceptance_v1"
        or gate.get("status") != "accepted_for_frozen_contingency"
        or gate.get("sequence") != SEQUENCE
        or gate.get("max_new_sampler_calls") != 15
        or gate.get("temperatures") != np.linspace(0, 1, 9).tolist()
        or not gate.get("numerical_checker")
        or not gate.get("runtime_checker")
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("prior_variant") != "base"
        or not set(CONSUMED) <= set(gate.get("files", {}))
    ):
        raise ValueError("accepted fixed fifteen-call numerical/runtime path gate required")
    for p, h in gate["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("path gate identity changed")


def validated_design(root):
    verify_prediction_gate(root, root / MODEL_GATE, "NCEI-native-duration", "distance-scale")
    lanes, frozen = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    fold = next(f for f in sequence_folds(lane) if f.sequence_id == SEQUENCE)
    if (
        len(fold.train) != 793
        or len(fold.test) != 271
        or len({lane.event_ids[int(i)] for i in fold.test}) != 1
    ):
        raise ValueError("frozen 793/271 single-event Tohoku design changed")
    return lane, fold.train, fold.test, frozen


def sample_path_job(root: Path, job, output: Path, store: Path):
    root, output, store = (p.resolve() for p in [root, output, store])
    if job not in path_jobs():
        raise ValueError("one exact fixed path job required; no ladder, seed or draw adaptation")
    if (
        output.exists()
        or store.exists()
        or not output.is_relative_to(root)
        or not store.is_relative_to(root)
    ):
        raise ValueError("new project-local node output/store required")
    verify_path_gate(root, root / PATH_GATE)
    lane, train, held, frozen = validated_design(root)
    pins = {p: sha256(root / p) for p in [*CONSUMED, PATH_GATE]}
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
            "sequence": SEQUENCE,
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
