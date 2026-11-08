"""Save bounded training/augmented posterior ensembles for bridge integration."""

# pyright: basic
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_cv import verify_prediction_gate
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_scale import build_scale_model
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.models import build_model, read_prior

CONSUMED = [
    "analysis/arrival/model_bridge_sampling.py",
    "analysis/arrival/model_cv.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/models.py",
    "analysis/arrival/evidence.py",
    "config/arrival-model-contract-v1.toml",
    "config/arrival-model-priors-v1.toml",
    "scripts/sample_arrival_bridge.py",
    "scripts/run_arrival_model_validation.py",
    "pyproject.toml",
    "uv.lock",
]


def bridge_indices(lane, sequence, phase, event):
    folds = [f for f in sequence_folds(lane) if f.sequence_id == sequence]
    if len(folds) != 1 or phase not in {"training", "augmented"}:
        raise ValueError("one frozen exploration sequence and ensemble phase required")
    fold = folds[0]
    if phase == "training":
        if event is not None:
            raise ValueError("training ensemble has no held event")
        return fold.train, fold
    selected = [int(i) for i in fold.test if lane.event_ids[int(i)] == event]
    if not selected:
        raise ValueError("augmented ensemble requires exactly one held-out event")
    return np.sort(np.r_[fold.train, selected]), fold


def sample_ensemble(root: Path, job: dict[str, Any], output: Path, store: Path):
    if (
        job.get("target") not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or job.get("kind") not in {"event", "distance-scale"}
        or job.get("prior") != "base"
        or any(type(job.get(k)) is not int or not 1000 <= job[k] <= 4000 for k in ["draws", "tune"])
        or job.get("cores") != 2
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 20
        or output.exists()
        or store.exists()
        or not output.is_relative_to(root)
        or not store.is_relative_to(root)
    ):
        raise ValueError("new paths and bounded source-specific base-prior ensemble job required")
    gate = checked_path(root, job["gate"])
    verify_prediction_gate(root, gate, job["target"], job["kind"])
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    ids, fold = bridge_indices(lane, job["sequence"], job["phase"], job.get("event"))
    pins = {p: sha256(root / p) for p in [*CONSUMED, job["gate"]]}
    model = (
        build_scale_model(lane, read_prior(root, lane.target, "base"), indices=ids)
        if job["kind"] == "distance-scale"
        else build_model(
            lane,
            read_prior(root, lane.target, "base"),
            kind="event",
            indices=ids,
            parameterization="marginal",
        )
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
            "included": [lane.record_ids[int(i)] for i in ids],
            "training": [lane.record_ids[int(i)] for i in fold.train],
            "held_out_sequence": [lane.record_ids[int(i)] for i in fold.test],
            "phase": job["phase"],
            "event": job.get("event"),
            "sequence": fold.sequence_id,
        },
    )
    # Development runs retain the exact source, including uncommitted prototypes.
    for p in CONSUMED:
        target = output / "source-snapshot" / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / p).read_bytes())
    with model:
        tree = pm.sample(
            draws=job["draws"],
            tune=job["tune"],
            chains=4,
            cores=2,
            target_accept=0.95,
            random_seed=job["seed"],
            progressbar=False,
        )
    tree["observed_data"] = xr.DataTree(
        xr.Dataset(
            {"response": (("record",), lane.response[ids])},
            coords={"record": [lane.record_ids[int(i)] for i in ids]},
        )
    )
    tree.to_netcdf(store)
    diagnostics, table = sampling_diagnostics(tree)
    cast(Any, table).to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    write_json(output / "diagnostics.json", diagnostics)
    write_json(
        output / "result.json",
        {
            "job": job,
            "status": "posterior_saved_score_not_evaluated",
            "diagnostics": diagnostics,
            "posterior": str(store.relative_to(root)),
            "posterior_sha256": sha256(store),
            "records": len(ids),
            "reserved_outcomes": "sealed",
            "scope": "integration_ensemble_only",
        },
    )
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("ensemble source changed during sampling")
