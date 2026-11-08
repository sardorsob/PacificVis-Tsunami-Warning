"""One whole-sequence bridge refit, with independent augmented integration ensembles."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge import bridge_fold_score, bridge_score
from analysis.arrival.model_bridge_predictions import predictions_with_precision
from analysis.arrival.model_bridge_sampling import CONSUMED as SAMPLING_CONSUMED
from analysis.arrival.model_bridge_sampling import bridge_indices, sample_ensemble
from analysis.arrival.model_collapsed import CollapsedGaussian
from analysis.arrival.model_cv import verify_prediction_gate
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_prediction import posterior_components
from analysis.arrival.model_scale import ANCHORS_KM, scale_weights
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import read_prior

CONSUMED = sorted(
    set(
        [
            *SAMPLING_CONSUMED,
            "analysis/arrival/model_bridge.py",
            "analysis/arrival/model_bridge_cv.py",
            "analysis/arrival/model_bridge_predictions.py",
            "analysis/arrival/model_collapsed.py",
            "analysis/arrival/model_prediction.py",
            "analysis/arrival/model_scoring.py",
            "analysis/arrival/model_validation_report.py",
            "config/arrival-model-scoring-v1.toml",
            "scripts/fit_arrival_bridge_fold.py",
            "scripts/run_arrival_bridge_batch.py",
            "scripts/run_arrival_model_batch.py",
        ]
    )
)


def verify_bridge_gate(root, path, target, kind):
    gate = json.loads(path.read_text())
    if (
        gate.get("schema_version") != "arrival_bridge_cv_acceptance_v1"
        or gate.get("status") != "accepted"
        or not gate.get("numerical_checker")
        or not gate.get("runtime_checker")
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("prior_variant") != "base"
        or target not in gate.get("targets", [])
        or kind not in gate.get("kinds", [])
        or not set(CONSUMED) <= set(gate.get("files", {}))
    ):
        raise ValueError("accepted numerical and runtime bridge gate required")
    for p, h in gate["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("bridge acceptance identity changed")


def _read_ensemble(root, output, job, lane, ids, frozen):
    result = json.loads((output / "result.json").read_text())
    inputs = json.loads((output / "inputs.json").read_text())
    expected = {p: sha256(root / p) for p in [*SAMPLING_CONSUMED, job["gate"]]}
    if result["job"] != job or inputs["files"] != expected or inputs["source_files"] != frozen:
        raise ValueError("ensemble job/model/data identities mismatch")
    raw = checked_path(root, result["posterior"])
    if sha256(raw) != result["posterior_sha256"] or result["records"] != len(ids):
        raise ValueError("ensemble posterior/count changed")
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
        if observed.record.values.tolist() != [lane.record_ids[int(i)] for i in ids]:
            raise ValueError("ensemble observed membership mismatch")
        np.testing.assert_array_equal(observed.response.values, lane.response[ids])
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as posterior:
        ds = posterior.load()
    if job["kind"] == "distance-scale":
        np.testing.assert_array_equal(ds.scale_anchor_km.values, ANCHORS_KM)
        sd = ds.sigma_anchor.values
    else:
        sd = ds.sigma.values[..., None]
    values = np.concatenate([sd, ds.tau_event.values[..., None]], axis=-1)
    if (
        values.shape[:2] != (4, job["draws"])
        or not np.isfinite(values).all()
        or (values <= 0).any()
    ):
        raise ValueError("unaligned/nonpositive hyperparameter draws")
    return result, ds, values


def run_bridge_fold(root: Path, job, output: Path, store: Path):
    if (
        output.exists()
        or store.exists()
        or not output.is_relative_to(root)
        or not store.is_relative_to(root)
        or job.get("target") not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or job.get("kind") not in {"event", "distance-scale"}
        or job.get("prior") != "base"
        or any(type(job.get(k)) is not int or not 1000 <= job[k] <= 4000 for k in ["draws", "tune"])
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 100
        or job.get("cores") != 2
    ):
        raise ValueError("new bounded project-local bridge fold required")
    verify_bridge_gate(root, checked_path(root, job["bridge_gate"]), job["target"], job["kind"])
    verify_prediction_gate(root, checked_path(root, job["gate"]), job["target"], job["kind"])
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    train_ids, fold = bridge_indices(lane, job["sequence"], "training", None)
    held_events = sorted({lane.event_ids[int(i)] for i in fold.test})
    pins = {p: sha256(root / p) for p in [*CONSUMED, job["gate"], job["bridge_gate"]]}
    output.mkdir(parents=True)
    store.mkdir(parents=True)
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
    write_json(output / "job.json", job)
    write_json(
        output / "membership.json",
        {
            "train": [lane.record_ids[int(i)] for i in fold.train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": fold.sequence_id,
        },
    )
    ensembles = []
    for k, event in enumerate([None, *held_events]):
        phase = "training" if event is None else "augmented"
        ensemble_job = {**job, "phase": phase, "event": event, "seed": job["seed"] + k}
        ids, _ = bridge_indices(lane, fold.sequence_id, phase, event)
        folder = output / "ensembles" / f"{k:02d}-{phase}"
        write_json(output / "sampling-starts" / f"{k:02d}.json", ensemble_job)
        sample_ensemble(root, ensemble_job, folder, store / f"{k:02d}-{phase}.nc")
        result, posterior, values = _read_ensemble(root, folder, ensemble_job, lane, ids, frozen)
        ensembles.append((result, posterior, values))
        d = result["diagnostics"]
        if not d["screen_passed"]:
            repairable = bool(
                d["finite_diagnostics"]
                and d["divergences"] == 0
                and d["maxdepth_reached"] == 0
                and d["min_bfmi"] >= 0.3
                and d["max_rhat"] <= 1.03
            )
            write_json(
                output / "result.json",
                {
                    "job": job,
                    "status": "diagnostic_failure",
                    "repairable": repairable,
                    "diagnostics": d,
                    "sampler_calls": len(ensembles),
                    "reserved_outcomes": "sealed",
                },
            )
            return
    prior = read_prior(root, lane.target, "base")
    design = np.c_[np.ones(len(lane.rows)), lane.x]
    weights = (
        scale_weights(lane.distance_km)
        if job["kind"] == "distance-scale"
        else np.ones((len(lane.rows), 1))
    )
    model = CollapsedGaussian(
        lane.response[train_ids],
        design[train_ids],
        np.array(lane.event_ids)[train_ids],
        weights[train_ids],
        [prior["alpha_sd"], prior["beta_sd"]],
    )
    scores, first_influences, second_influences = [], [], []
    arrays = {}
    for k, event in enumerate(held_events):
        ids = np.array([int(i) for i in fold.test if lane.event_ids[int(i)] == event])
        logs = [
            model.new_event_logpdf(
                v.reshape(-1, weights.shape[1] + 1), lane.response[ids], design[ids], weights[ids]
            ).reshape(v.shape[:2])
            for v in [ensembles[0][2], ensembles[k + 1][2]]
        ]
        score, first, second = bridge_score(*logs, records=len(ids))
        jacobian = 0.0 if lane.target == "T-CAL" else float(np.log(lane.y[ids]).sum())
        score["joint_log_predictive"] -= jacobian
        score["normalized_event_score"] = score["joint_log_predictive"] / len(ids)
        score["chain_joint_log_predictive"] = [
            v - jacobian for v in score["chain_joint_log_predictive"]
        ]
        scores.append({"event_id": event, "sequence": fold.sequence_id, **score})
        first_influences.append(first)
        second_influences.append(second)
        for label, value in [
            ("training_log_ratio", logs[0]),
            ("augmented_log_ratio", logs[1]),
            ("training_influence", first),
            ("augmented_influence", second),
        ]:
            arrays[f"{label}_{k:03d}"] = value
    raw_arrays = store / "bridge-arrays.npz"
    np.savez_compressed(raw_arrays, **arrays)
    fold_score = bridge_fold_score(scores, first_influences, second_influences)
    mean, sigma, tau = posterior_components(
        ensembles[0][1], job["kind"], lane.distance_km[fold.test]
    )
    predicted, precision = predictions_with_precision(
        lane.response[fold.test], mean, sigma, tau, lane.reference_minutes[fold.test], lane.target
    )
    predictions = []
    for j, i in enumerate(fold.test):
        predictions.append(
            {
                "record_id": lane.record_ids[int(i)],
                "event_id": lane.event_ids[int(i)],
                "target": lane.target,
                "sequence": fold.sequence_id,
                "distance_km": float(lane.distance_km[i]),
                "observed_native_minutes": float(lane.y[i]),
                "seen_site": bool(fold.seen_site[j]),
                **{p: float(v[j]) for p, v in predicted.items()},
                **precision[j],
            }
        )
    write_table(output / "held-out-record-predictions.csv", predictions)
    write_table(
        output / "event-joint-scores.csv",
        [{k: v for k, v in s.items() if isinstance(v, (int, float, str, bool))} for s in scores],
    )
    score_passed = all(s["precision_passed"] for s in scores)
    prediction_passed = all(p["prediction_precision_passed"] for p in precision)
    repairable = all(
        s["overlap"] >= 0.1
        and abs(s["fixedpoint_derivative"]) <= 0.25
        and min(s["training_weight_concentration"], s["augmented_weight_concentration"]) >= 100
        and all(
            m.get("constant") or m.get("rhat") is not None and m["rhat"] <= 1.03
            for m in [s["training_functional_mixing"], s["augmented_functional_mixing"]]
        )
        for s in scores
    )
    write_json(
        output / "result.json",
        {
            "job": job,
            "status": "computed_pending_review"
            if score_passed and prediction_passed
            else "precision_failure",
            "score_precision_passed": score_passed,
            "prediction_precision_passed": prediction_passed,
            "repairable": repairable,
            "fold_score": fold_score,
            "events": scores,
            "training_records": len(train_ids),
            "heldout_records": len(fold.test),
            "sampler_calls": len(ensembles),
            "bridge_arrays": str(raw_arrays.relative_to(root)),
            "bridge_arrays_sha256": sha256(raw_arrays),
            "reserved_outcomes": "sealed",
        },
    )
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("bridge fold inputs changed during execution")
