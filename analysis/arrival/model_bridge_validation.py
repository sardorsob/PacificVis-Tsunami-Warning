"""Finite known-normalizer calibration and exploration-only bridge prototypes."""

# pyright: basic
from __future__ import annotations

import json
import math
import subprocess
import time
from pathlib import Path

import numpy as np
import xarray as xr
from scipy.signal import lfilter
from scipy.stats import norm

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_bridge import bridge_score
from analysis.arrival.model_collapsed import CollapsedGaussian
from analysis.arrival.model_cv import verify_prediction_gate
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_scale import ANCHORS_KM, scale_weights
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import read_prior

CONSUMED = [
    "analysis/arrival/model_bridge.py",
    "analysis/arrival/model_bridge_validation.py",
    "analysis/arrival/model_bridge_sampling.py",
    "analysis/arrival/model_scoring.py",
    "analysis/arrival/model_collapsed.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/models.py",
    "config/arrival-model-priors-v1.toml",
    "config/arrival-model-scoring-v1.toml",
    "scripts/validate_arrival_bridge.py",
    "pyproject.toml",
    "uv.lock",
]


def _inputs(root, output):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local prototype output required")
    output.mkdir(parents=True)
    pins = {p: sha256(root / p) for p in CONSUMED}
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "reserved_outcomes": "sealed",
        },
    )
    # Freeze uncommitted development source as well as recording its checksum.
    for p in CONSUMED:
        dest = output / "source-snapshot" / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((root / p).read_bytes())
    return pins


def _check(root, pins):
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("prototype source changed during execution")


def calibration(root: Path, output: Path):
    pins = _inputs(root, output)
    cases = [
        ("shifted-iid", [0.8], [0.7], 0.0, 40),
        ("wide-iid", [0.5], [1.8], 0.0, 40),
        ("autocorrelated", [1.0], [0.8], 0.8, 40),
        ("four-dimensional", [0.6, -0.4, 0.2, 0.3], [0.6, 1.3, 0.9, 1.1], 0.0, 40),
        ("poor-overlap", [9.0], [1.0], 0.0, 10),
    ]
    rows = []
    started = time.monotonic()
    for index, (label, mean, width, rho, count) in enumerate(cases):
        mean, width = np.asarray(mean), np.asarray(width)
        for rep in range(count):
            seed = 1026110800 + index * 1000 + rep
            rng = np.random.default_rng(seed)

            def samples(draws, rng=rng, mean=mean, rho=rho):
                eps = rng.normal(size=(4, draws, len(mean)))
                previous = rng.normal(size=(4, 1, len(mean)))
                return lfilter([math.sqrt(1 - rho**2)], [1, -rho], eps, axis=1, zi=rho * previous)[
                    0
                ]

            x, y = samples(4000), mean + width * samples(3000)
            truth = -1200.0
            a = truth + (norm.logpdf(x, mean, width) - norm.logpdf(x)).sum(axis=-1)
            b = truth + (norm.logpdf(y, mean, width) - norm.logpdf(y)).sum(axis=-1)
            score, _, _ = bridge_score(a, b, records=100)
            row = {
                "case": label,
                "replicate": rep,
                "seed": seed,
                "rho": rho,
                "dimensions": len(mean),
                "truth": truth,
                "estimate": score["joint_log_predictive"],
                "error": score["joint_log_predictive"] - truth,
                "mcse": score["joint_log_mcse_delta"],
                "overlap": score["overlap"],
                "fixedpoint_derivative": score["fixedpoint_derivative"],
                "numerical_screen_passed": score["precision_passed"],
                "covers_90": abs(score["joint_log_predictive"] - truth)
                <= norm.ppf(0.95) * score["joint_log_mcse_delta"],
            }
            rows.append(row)
            write_json(output / "cases" / f"{label}-{rep:02d}.json", score)
        write_table(output / "known-normalizer-calibration.csv", rows)
        print(label, "completed", count, flush=True)
    summary = []
    for label, *_ in cases:
        selected = [r for r in rows if r["case"] == label]
        err = np.array([r["error"] for r in selected])
        se = np.array([r["mcse"] for r in selected])
        summary.append(
            {
                "case": label,
                "replicates": len(selected),
                "accepted": sum(r["numerical_screen_passed"] for r in selected),
                "mean_error": float(err.mean()),
                "empirical_sd": float(err.std(ddof=1)),
                "rms_reported_mcse": float(np.sqrt(np.mean(se**2))),
                "covers_90": sum(r["covers_90"] for r in selected),
                "min_overlap": min(r["overlap"] for r in selected),
            }
        )
    write_table(output / "calibration-summary.csv", summary)
    write_json(
        output / "result.json",
        {
            "status": "development_calibration_pending_review",
            "replicates": len(rows),
            "elapsed_seconds": time.monotonic() - started,
            "scope": "known_stationary_Normal_ensembles_not_model_SBC_or_physical_validation",
            "reserved_outcomes": "sealed",
        },
    )
    _check(root, pins)


def actual_pilot(root: Path, training: Path, augmented: Path, output: Path, *, kind="event"):
    """Bounded exploration gate uses existing clean independent fits; no sampling."""
    first = json.loads((training / "result.json").read_text())
    second = json.loads((augmented / "result.json").read_text())
    if (
        any(
            r["job"]["kind"] != kind
            or r["job"]["target"] != "NCEI-native-duration"
            or not r["diagnostics"]["screen_passed"]
            or r["job"].get("prior", "base") != "base"
            for r in [first, second]
        )
        or first["job"]["seed"] == second["job"]["seed"]
        or kind not in {"event", "distance-scale"}
    ):
        raise ValueError("independent clean base-prior primary event fits required")
    verify_prediction_gate(root, root / first["job"]["gate"], "NCEI-native-duration", kind)
    lanes, frozen = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    fold = next(f for f in sequence_folds(lane) if f.sequence_id == first["job"]["sequence"])
    if len({lane.event_ids[int(i)] for i in fold.test}) != 1:
        raise ValueError("single-event prototype only")
    membership = json.loads((training / "membership.json").read_text())
    train_key, test_key = (
        ("training", "held_out_sequence") if "phase" in first["job"] else ("train", "test")
    )
    for key, ids in [(train_key, fold.train), (test_key, fold.test)]:
        if membership[key] != [lane.record_ids[int(i)] for i in ids]:
            raise ValueError("source fold membership changed")
    augmented_ids = np.sort(np.r_[fold.train, fold.test])
    if second["records"] != len(augmented_ids):
        raise ValueError("augmented fit includes other held-out sequence events")
    if "phase" in first["job"] and first["job"]["phase"] != "training":
        raise ValueError("training posterior phase mismatch")
    if "phase" in second["job"] and (
        second["job"]["phase"] != "augmented"
        or second["job"]["sequence"] != fold.sequence_id
        or second["job"]["event"] != lane.event_ids[int(fold.test[0])]
    ):
        raise ValueError("augmented posterior phase/event mismatch")
    arrays = []
    for folder, result in [(training, first), (augmented, second)]:
        inputs = json.loads((folder / "inputs.json").read_text())
        if inputs["source_files"] != frozen:
            raise ValueError("source data contract mismatch")
        identities = inputs.get("code_and_config", inputs.get("files", {}))
        for p in [
            "analysis/arrival/models.py",
            "analysis/arrival/model_data.py",
            "analysis/arrival/model_validation.py",
            "config/arrival-model-priors-v1.toml",
            "pyproject.toml",
            "uv.lock",
            *(["analysis/arrival/model_scale.py"] if kind == "distance-scale" else []),
        ]:
            if identities.get(p) != sha256(root / p):
                raise ValueError("source model/prior/environment identity mismatch")
        posterior = root / result["posterior"]
        if sha256(posterior) != result["posterior_sha256"]:
            raise ValueError("source posterior changed")
        with xr.open_dataset(posterior, group="posterior", engine="h5netcdf") as ds:
            if kind == "distance-scale":
                np.testing.assert_array_equal(ds.scale_anchor_km.values, ANCHORS_KM)
            scales = (
                ds.sigma_anchor.values if kind == "distance-scale" else ds.sigma.values[..., None]
            )
            arrays.append(np.concatenate([scales, ds.tau_event.values[..., None]], axis=-1))
    with xr.open_dataset(
        root / second["posterior"], group="observed_data", engine="h5netcdf"
    ) as ds:
        if ds.record.values.tolist() != [lane.record_ids[int(i)] for i in augmented_ids]:
            raise ValueError("augmented raw data membership mismatch")
        np.testing.assert_array_equal(ds.response.values, lane.response[augmented_ids])
    pins = _inputs(root, output)
    prior = read_prior(root, lane.target, "base")
    x = np.c_[np.ones(len(lane.rows)), lane.x]
    weights = scale_weights(lane.distance_km) if kind == "distance-scale" else np.ones((len(x), 1))
    model = CollapsedGaussian(
        lane.response[fold.train],
        x[fold.train],
        np.array(lane.event_ids)[fold.train],
        weights[fold.train],
        [prior["alpha_sd"], prior["beta_sd"]],
    )
    logs = [
        model.new_event_logpdf(
            a.reshape(-1, weights.shape[1] + 1),
            lane.response[fold.test],
            x[fold.test],
            weights[fold.test],
        ).reshape(a.shape[:2])
        for a in arrays
    ]
    score, i0, i1 = bridge_score(*logs, records=len(fold.test))
    jacobian = float(np.log(lane.y[fold.test]).sum())
    score["joint_log_predictive"] -= jacobian
    score["normalized_event_score"] = score["joint_log_predictive"] / len(fold.test)
    score["chain_joint_log_predictive"] = [
        v - jacobian for v in score["chain_joint_log_predictive"]
    ]
    np.savez_compressed(
        output / "bridge-arrays.npz",
        training_log_ratio=logs[0],
        augmented_log_ratio=logs[1],
        training_influence=i0,
        augmented_influence=i1,
    )
    write_json(
        output / "source-fits.json",
        {
            "training_result": str((training / "result.json").relative_to(root)),
            "training_result_sha256": sha256(training / "result.json"),
            "augmented_result": str((augmented / "result.json").relative_to(root)),
            "augmented_result_sha256": sha256(augmented / "result.json"),
            "source_files": frozen,
            "source_kind": kind,
            "sequence": fold.sequence_id,
            "duration_jacobian": jacobian,
            "augmented_posterior_scope": "integration_only_never_heldout_prediction",
        },
    )
    write_json(output / "result.json", score)
    _check(root, pins)
