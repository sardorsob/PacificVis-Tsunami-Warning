"""Finite new-ensemble precision supplement for the unchanged LATA holdout."""

# pyright: basic
from __future__ import annotations

import json

import numpy as np
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge import bridge_score
from analysis.arrival.model_bridge_sampling import bridge_indices
from analysis.arrival.model_curvature_cv import curvature_kernel, native_event_logpdf
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_curvature_sequence import sample_ensemble
from analysis.arrival.model_curvature_sequence import verify_gate as original_gate
from analysis.arrival.model_data import CONTRACT, load_lanes
from analysis.arrival.model_validation_report import write_table

BASE = "artifacts/models/arrival-timing/mean-curvature-sequence-v1"
SOURCE = BASE + "/jobs/fold-008"
OUTPUT = BASE + "/resolutions/fold-008-precision-v1"
STORE = "data/processed/models/mean-curvature-sequence-v1/resolution-fold-008-precision-v1"
GATE = "artifacts/models/arrival-timing/mean-curvature-precision-design-v1/review-acceptance.json"
STOP_REVIEW = BASE + "/continuation-v1/numerical-stop-review.json"
WORKER = "scripts/fit_arrival_curvature_precision.py"
RUNTIME = [
    "scripts/run_arrival_curvature_continuation.py",
    "scripts/run_arrival_curvature_sequences.py",
    "scripts/run_arrival_model_batch.py",
    "scripts/run_arrival_model_validation.py",
    "analysis/arrival/evidence.py",
]
CODE = [
    "analysis/arrival/model_curvature_precision.py",
    WORKER,
    "scripts/run_arrival_curvature_precision.py",
]
EVENT = "usc000piqj"


def job():
    return {
        "id": "fold-008-lata-precision",
        "target": "NCEI-native-duration",
        "kind": "mean-curvature",
        "prior": "base",
        "sequence": "seq-usc000phx5",
        "draws": 8000,
        "tune": 2000,
        "cores": 2,
        "seed": 2866118800,
        "event": EVENT,
    }


def admit(root):
    gate = json.loads((root / GATE).read_text())
    if (
        gate.get("status") != "accepted_lata_precision_supplement"
        or gate.get("independent_checker") is not True
        or gate.get("job") != job()
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not set(
            [
                *CODE,
                *RUNTIME,
                STOP_REVIEW,
                CONTRACT,
                SOURCE + "/attempt-evidence.json",
                SOURCE + "/result.json",
                SOURCE + "/membership.json",
                SOURCE + "/held-out-record-predictions.csv",
            ]
        ).issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independently accepted two-ensemble precision design required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for name, digest in pins.items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("precision supplement source changed")
    review = json.loads((root / STOP_REVIEW).read_text())
    if (
        review.get("status") != "accepted_curvature_continuation_precision_stop"
        or review.get("independent_checker") is not True
        or review.get("confirmation_outcomes_parsed") is not False
        or review.get("reserved_outcomes") != "sealed"
        or not review.get("files")
        or any(pins.get(p) != h for p, h in review["files"].items())
    ):
        raise ValueError("complete independently reviewed original failure required")
    manifest = json.loads((root / SOURCE / "attempt-evidence.json").read_text())
    if not manifest.get("files") or any(pins.get(p) != h for p, h in manifest["files"].items()):
        raise ValueError("complete original failed science and raw closure required before parsing")
    raw = root / "data/processed/models/mean-curvature-sequence-v1/fold-008"
    inventory = {
        str(p.relative_to(root))
        for folder in [root / SOURCE, raw]
        for p in folder.rglob("*")
        if p.is_file()
    }
    mandatory = {
        SOURCE + "/" + name
        for name in [
            "job.json",
            "inputs.json",
            "membership.json",
            "result.json",
            "held-out-record-predictions.csv",
            "attempt-evidence.json",
        ]
    }
    mandatory.update(
        "data/processed/models/mean-curvature-sequence-v1/fold-008/" + name
        for name in ["00-training.nc", "01-augmented.nc", "02-augmented.nc", "bridge-arrays.npz"]
    )
    if not (inventory | mandatory).issubset(pins):
        raise ValueError("complete original failed science and raw closure required before parsing")
    old = json.loads((root / SOURCE / "result.json").read_text())
    if (
        old.get("status") != "precision_failure"
        or old.get("prediction_precision_passed") is not True
        or old["job"]["id"] != "fold-008"
        or old["job"]["sequence"] != job()["sequence"]
    ):
        raise ValueError("same failed original job and complete original predictions required")
    required = original_gate(root, old["job"])
    if any(pins.get(p) != h for p, h in required.items()):
        raise ValueError("original worker reference closure required")
    return gate, pins, old


def combine(original, replacement):
    """Fresh training makes the replacement MC error independent of the retained event."""
    if (
        original.get("status") != "precision_failure"
        or original.get("prediction_precision_passed") is not True
        or replacement.get("event_id") != EVENT
        or replacement.get("sequence") != job()["sequence"]
        or replacement.get("records") != 1
        or replacement.get("precision_passed") is not True
    ):
        raise ValueError("same original failed fold and precise LATA event required")
    events = original["events"]
    if len(events) != 2 or {e["event_id"] for e in events} != {EVENT, "usc000phx5"}:
        raise ValueError("both original held events required")
    old = next(e for e in events if e["event_id"] == EVENT)
    keep = next(e for e in events if e["event_id"] != EVENT)
    for e, n in [(old, 1), (keep, 3), (replacement, 1)]:
        values = [e["joint_log_predictive"], e["normalized_event_score"], e["normalized_mcse"]]
        if (
            e["records"] != n
            or not np.isfinite(values).all()
            or e["normalized_mcse"] < 0
            or not np.isclose(
                e["joint_log_predictive"] / n, e["normalized_event_score"], atol=1e-10, rtol=0
            )
        ):
            raise ValueError("finite exact native event score identities required")
    if (
        not keep["precision_passed"]
        or max(keep["normalized_mcse"], replacement["normalized_mcse"]) > 0.005
    ):
        raise ValueError("every event must pass original MCSE screen")
    error = float(np.hypot(old["normalized_mcse"], replacement["normalized_mcse"]))
    difference = float(replacement["normalized_event_score"] - old["normalized_event_score"])
    if abs(difference) > 3 * error + 1e-10:
        raise ValueError("new ensemble disagrees with retained approximation beyond3MCSE")
    return {
        **original,
        "status": "computed_pending_review",
        "score_precision_passed": True,
        "events": [replacement if e["event_id"] == EVENT else e for e in events],
        "fold_score": {
            "events": 2,
            "equal_event_score": float(
                (keep["normalized_event_score"] + replacement["normalized_event_score"]) / 2
            ),
            "event_precision_passed": True,
            "mcse_equal_event_score": float(
                np.hypot(keep["normalized_mcse"], replacement["normalized_mcse"]) / 2
            ),
            "mcse_scope": "independent_training_ensembles; same_sampling_sequence",
            "min_bridge_overlap": min(keep["overlap"], replacement["overlap"]),
        },
        "precision_resolution": {
            "old_lata_score_retained": old["normalized_event_score"],
            "old_lata_mcse_retained": old["normalized_mcse"],
            "difference": difference,
            "combined_mcse": error,
            "agreement_passed": True,
            "prediction_policy": "unchanged original training-only predictions",
        },
    }


def run(root):
    gate, pins, old = admit(root)
    output, store = root / OUTPUT, root / STORE
    if output.exists() or store.exists():
        raise ValueError("retain original supplement; new paths cannot overwrite")
    lanes, frozen = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    train, fold = bridge_indices(lane, job()["sequence"], "training", None)
    held = np.array([int(i) for i in fold.test if lane.event_ids[int(i)] == EVENT])
    if len(train) != 1060 or len(fold.test) != 4 or len(held) != 1:
        raise ValueError("unchanged1060train/4held/1LATA membership required")
    old_membership = json.loads((root / SOURCE / "membership.json").read_text())
    if old_membership["train"] != [lane.record_ids[int(i)] for i in train] or old_membership[
        "test"
    ] != [lane.record_ids[int(i)] for i in fold.test]:
        raise ValueError("original held sequence membership changed")
    output.mkdir(parents=True)
    store.mkdir(parents=True)
    write_json(output / "job.json", job())
    write_json(output / "inputs.json", {"files": pins, "source_files": frozen})
    ensembles = []
    for k, event in enumerate([None, EVENT]):
        phase = "training" if event is None else "augmented"
        ids, _ = bridge_indices(lane, job()["sequence"], phase, event)
        spec = {**job(), "event": event, "phase": phase, "seed": job()["seed"] + k}
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
            write_json(output / "result.json", {"status": "diagnostic_failure", "job": job()})
            return
        raw = checked_path(root, result["posterior"])
        if sha256(raw) != result["posterior_sha256"]:
            raise ValueError("saved precision ensemble changed")
        with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as obs:
            np.testing.assert_array_equal(obs.record.values, [lane.record_ids[int(i)] for i in ids])
            np.testing.assert_array_equal(obs.response.values, lane.response[ids])
            np.testing.assert_array_equal(obs.native_minutes.values, lane.y[ids])
        np.testing.assert_array_equal(post.scale_anchor_km.values, [500.0, 2000.0, 5000.0])
        variance = np.concatenate(
            [post.sigma_anchor.values, post.tau_event.values[..., None]], axis=-1
        )
        if (
            variance.shape != (4, 8000, 4)
            or not np.isfinite(variance).all()
            or (variance <= 0).any()
        ):
            raise ValueError("four aligned positive variance coordinates required")
        ensembles.append(variance)
    kernel = curvature_kernel(
        lane.response[train],
        lane.distance_km[train],
        np.array(lane.event_ids)[train],
        read_curvature_prior(root, "base"),
    )
    logs = [
        native_event_logpdf(
            kernel,
            v.reshape(-1, 4),
            lane.response[held],
            lane.distance_km[held],
            lane.y[held],
            np.array(lane.event_ids)[held],
        ).reshape(4, 8000)
        for v in ensembles
    ]
    score, a, b = bridge_score(*logs, records=1)
    arrays = store / "bridge-arrays.npz"
    with arrays.open("xb") as stream:
        np.savez_compressed(
            stream,
            training_native_log_ratio=logs[0],
            augmented_native_log_ratio=logs[1],
            training_influence=a,
            augmented_influence=b,
        )
    replacement = {"event_id": EVENT, "sequence": job()["sequence"], **score}
    write_json(output / "event-score.json", replacement)
    if not score["precision_passed"]:
        write_json(
            output / "result.json",
            {"status": "precision_failure", "job": job(), "event": replacement},
        )
        return
    resolved = combine(old, replacement)
    resolved.update(
        source_result=SOURCE + "/result.json",
        source_result_sha256=pins[SOURCE + "/result.json"],
        retained_direct_bridge_status="precision_failure",
        precision_job=job(),
        training_only_predictions=SOURCE + "/held-out-record-predictions.csv",
        training_only_predictions_sha256=pins[SOURCE + "/held-out-record-predictions.csv"],
        bridge_arrays=str(arrays.relative_to(root)),
        bridge_arrays_sha256=sha256(arrays),
    )
    write_table(output / "event-joint-scores.csv", resolved["events"])
    if any(sha256(checked_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("precision evidence changed during sampling")
    write_json(output / "result.json", resolved)
