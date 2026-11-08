"""One whole-sequence curvature refit with independent integration ensembles."""

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
from analysis.arrival.model_bridge import bridge_fold_score, bridge_score
from analysis.arrival.model_bridge_predictions import predictions_with_precision
from analysis.arrival.model_bridge_sampling import bridge_indices
from analysis.arrival.model_curvature import build_curvature_model
from analysis.arrival.model_curvature_cv import (
    curvature_kernel,
    native_event_logpdf,
    posterior_components,
)
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_curvature_validation import CONSUMED as VALIDATION_CONSUMED
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_scale import ANCHORS_KM
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.model_validation_report import write_table

GATE = "artifacts/models/arrival-timing/mean-curvature-sequence-design-v1/review-acceptance.json"
FIT_GATE = "artifacts/models/arrival-timing/exploration-mean-curvature-v1/review-acceptance.json"
CONSUMED = sorted(
    set(
        [
            *VALIDATION_CONSUMED,
            FIT_GATE,
            "analysis/arrival/model_curvature_cv.py",
            "analysis/arrival/model_curvature_sequence.py",
            "analysis/arrival/model_collapsed.py",
            "analysis/arrival/model_bridge.py",
            "analysis/arrival/model_bridge_sampling.py",
            "analysis/arrival/model_bridge_predictions.py",
            "analysis/arrival/model_prediction.py",
            "analysis/arrival/model_scoring.py",
            "analysis/arrival/model_validation_report.py",
            "scripts/fit_arrival_curvature_sequence.py",
            "scripts/run_arrival_curvature_sequences.py",
            "scripts/run_arrival_model_batch.py",
        ]
    )
)


def verify_gate(root, job):
    gate = json.loads((root / GATE).read_text())
    if (
        gate.get("status") != "accepted_curvature_sequence_rehearsal"
        or gate.get("independent_checker") is not True
        or gate.get("max_sampler_call_slots") != 248
        or job not in gate.get("cases", [])
        or not set(CONSUMED).issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independently accepted curvature CV design required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for name, digest in pins.items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("curvature sequence design source changed")
    fit = json.loads((root / FIT_GATE).read_text())
    if (
        fit.get("status") != "accepted_actual_curvature_fit_with_conditional_ppc_inadequacy"
        or fit.get("independent_checker") is not True
        or fit.get("protected_data", {}).get("reserved_outcomes") != "sealed"
        or fit.get("protected_data", {}).get("confirmation_outcomes_parsed") is not False
    ):
        raise ValueError("accepted actual fit with explicit adequacy limitations required")
    if not fit.get("files") or any(pins.get(p) != h for p, h in fit["files"].items()):
        raise ValueError("complete accepted actual-fit reference closure required")
    return pins


def sample_ensemble(root, job, ids, lane, frozen, output, store, pins):
    if output.exists() or store.exists():
        raise ValueError("retain original ensemble; new paths required")
    model = build_curvature_model(lane, read_curvature_prior(root, "base"), indices=ids)
    output.mkdir(parents=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "files": {p: pins[p] for p in [*CONSUMED, GATE]},
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
            "role": "training_prediction_and_normalization"
            if job["phase"] == "training"
            else "augmented_normalization_only_not_prediction",
        },
    )
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
            {
                "response": (("record",), lane.response[ids]),
                "native_minutes": (("record",), lane.y[ids]),
            },
            coords={"record": [lane.record_ids[int(i)] for i in ids]},
        )
    )
    tree.to_netcdf(store)
    posterior = cast(Any, tree["posterior"])
    if "nutpie" not in str(posterior.attrs).lower():
        raise ValueError("unexplained sequence sampler backend")
    diagnostics, table = sampling_diagnostics(tree)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    result = {
        "job": job,
        "records": len(ids),
        "diagnostics": diagnostics,
        "posterior": str(store.relative_to(root)),
        "posterior_sha256": sha256(store),
        "scope": "training_prediction_and_normalization"
        if job["phase"] == "training"
        else "augmented_normalization_only_not_prediction",
    }
    write_json(output / "result.json", result)
    loaded = posterior.to_dataset().load() if hasattr(posterior, "to_dataset") else posterior.load()
    tree.close()
    return result, loaded


def run_fold(root: Path, job: dict[str, Any], output: Path, store: Path) -> None:
    if (
        output.exists()
        or store.exists()
        or not output.is_relative_to(root)
        or not store.is_relative_to(root)
        or job.get("kind") != "mean-curvature"
        or job.get("target") != "NCEI-native-duration"
        or job.get("prior") != "base"
        or job.get("draws") != 2000
        or job.get("tune") != 1000
        or job.get("cores") != 2
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 1000
    ):
        raise ValueError("new bounded base-prior curvature sequence job required")
    pins = verify_gate(root, job)
    lanes, frozen = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    train, fold = bridge_indices(lane, job["sequence"], "training", None)
    events = sorted({lane.event_ids[int(i)] for i in fold.test})
    output.mkdir(parents=True)
    store.mkdir(parents=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {"files": pins, "source_files": frozen, "prediction_ensemble": "00-training_only"},
    )
    write_json(
        output / "membership.json",
        {
            "train": [lane.record_ids[int(i)] for i in train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": fold.sequence_id,
        },
    )
    ensembles = []
    for k, event in enumerate([None, *events]):
        phase = "training" if event is None else "augmented"
        ids, _ = bridge_indices(lane, fold.sequence_id, phase, event)
        spec = {**job, "phase": phase, "event": event, "seed": job["seed"] + k}
        write_json(output / "sampling-starts" / f"{k:02d}.json", spec)
        result, post = sample_ensemble(
            root,
            spec,
            ids,
            lane,
            frozen,
            output / "ensembles" / f"{k:02d}-{phase}",
            store / f"{k:02d}-{phase}.nc",
            pins,
        )
        if not result["diagnostics"]["screen_passed"]:
            write_json(
                output / "result.json",
                {
                    "job": job,
                    "status": "diagnostic_failure",
                    "sampler_calls_started": k + 1,
                    "diagnostics": result["diagnostics"],
                },
            )
            return
        # Check native/log responses and membership against the retained file before scoring.
        raw = checked_path(root, result["posterior"])
        if sha256(raw) != result["posterior_sha256"] or result["job"] != spec:
            raise ValueError("ensemble identity changed")
        with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
            np.testing.assert_array_equal(
                observed.record.values, [lane.record_ids[int(i)] for i in ids]
            )
            np.testing.assert_array_equal(observed.response.values, lane.response[ids])
            np.testing.assert_array_equal(observed.native_minutes.values, lane.y[ids])
        np.testing.assert_array_equal(post.coords["scale_anchor_km"].values, ANCHORS_KM)
        variance = np.concatenate(
            [post.sigma_anchor.values, post.tau_event.values[..., None]], axis=-1
        )
        if (
            variance.shape != (4, 2000, 4)
            or not np.isfinite(variance).all()
            or (variance <= 0).any()
        ):
            raise ValueError("four aligned positive variance coordinates required")
        ensembles.append((post, variance))
    kernel = curvature_kernel(
        lane.response[train],
        lane.distance_km[train],
        np.array(lane.event_ids)[train],
        read_curvature_prior(root, "base"),
    )
    scores, firsts, seconds, arrays = [], [], [], {}
    for j, event in enumerate(events):
        held = np.array([int(i) for i in fold.test if lane.event_ids[int(i)] == event])
        logs = [
            native_event_logpdf(
                kernel,
                v.reshape(-1, 4),
                lane.response[held],
                lane.distance_km[held],
                lane.y[held],
                np.array(lane.event_ids)[held],
            ).reshape(4, 2000)
            for _, v in [ensembles[0], ensembles[j + 1]]
        ]
        # The adapter already supplies native-minute densities; no second Jacobian.
        score, a, b = bridge_score(*logs, records=len(held))
        scores.append({"event_id": event, "sequence": fold.sequence_id, **score})
        firsts.append(a)
        seconds.append(b)
        for name, value in [
            ("training_native_log_ratio", logs[0]),
            ("augmented_native_log_ratio", logs[1]),
            ("training_influence", a),
            ("augmented_influence", b),
        ]:
            arrays[f"{name}_{j:03d}"] = value
    path = store / "bridge-arrays.npz"
    np.savez_compressed(path, **arrays)
    mean, sigma, tau = posterior_components(ensembles[0][0], lane.distance_km[fold.test])
    predicted, precision = predictions_with_precision(
        lane.response[fold.test], mean, sigma, tau, lane.reference_minutes[fold.test], lane.target
    )
    predictions = [
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
        for j, i in enumerate(fold.test)
    ]
    write_table(output / "held-out-record-predictions.csv", predictions)
    write_table(
        output / "event-joint-scores.csv",
        [
            {k: v for k, v in row.items() if isinstance(v, (str, int, float, bool))}
            for row in scores
        ],
    )
    score_passed = all(row["precision_passed"] for row in scores)
    prediction_passed = all(row["prediction_precision_passed"] for row in precision)
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("CV source drift")
    write_json(
        output / "result.json",
        {
            "job": job,
            "status": "computed_pending_review"
            if score_passed and prediction_passed
            else "precision_failure",
            "score_precision_passed": score_passed,
            "prediction_precision_passed": prediction_passed,
            "fold_score": bridge_fold_score(scores, firsts, seconds),
            "events": scores,
            "sampler_calls_started": len(ensembles),
            "training_records": len(train),
            "heldout_records": len(fold.test),
            "bridge_arrays": str(path.relative_to(root)),
            "bridge_arrays_sha256": sha256(path),
            "observation_measure": "native_minutes_Jacobian_already_applied_once",
            "aggregation_note": "final program averages33event scores, not29fold means",
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
