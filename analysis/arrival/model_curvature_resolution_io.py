"""File-gated resolution of the retained Tohoku curvature score, with no new fits."""

# pyright: basic
from __future__ import annotations

import json
import math
import subprocess
import tomllib

import numpy as np

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge_sampling import bridge_indices
from analysis.arrival.model_curvature_path_sampling import (
    GATE as SOURCE_GATE,
)
from analysis.arrival.model_curvature_path_sampling import (
    OUTPUT,
    SOURCE,
    STOP_REVIEW,
    STORE,
    path_jobs,
)
from analysis.arrival.model_curvature_resolution import resolved_path_result
from analysis.arrival.model_data import CONTRACT, load_lanes

REVIEW = OUTPUT + "/review-acceptance.json"
ORIGINAL_RAW = "data/processed/models/mean-curvature-sequence-v1/fold-002/"
CODE = [
    "analysis/arrival/model_curvature_resolution_io.py",
    "analysis/arrival/model_curvature_resolution.py",
    "analysis/arrival/model_path_fold_resolution.py",
    "analysis/arrival/model_scoring.py",
    "scripts/resolve_arrival_curvature_fold.py",
]


def verified_path(root):
    gate = json.loads((root / REVIEW).read_text())
    if (
        gate.get("status") != "accepted_curvature_primary_path_and_independent_repeat"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not gate.get("files")
    ):
        raise ValueError("complete independently accepted path evidence required")
    pins = {**gate["files"], REVIEW: sha256(root / REVIEW)}
    for p, h in pins.items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("accepted path evidence changed")
    required = {
        OUTPUT + "/" + p
        for p in [
            "plan.json",
            "run-summary.json",
            "primary-path-result.json",
            "repeat-path-result.json",
            "independent-repeat-check.json",
        ]
    }
    required.update(
        STORE + "/" + p
        for p in ["primary-combined-influences.npz", "repeat-combined-influences.npz"]
    )
    required.update({SOURCE_GATE, STOP_REVIEW, CONTRACT})
    required.update(
        SOURCE + "/" + p
        for p in [
            "result.json",
            "inputs.json",
            "membership.json",
            "held-out-record-predictions.csv",
            "ensembles/00-training/result.json",
            "ensembles/01-augmented/result.json",
        ]
    )
    required.update(
        ORIGINAL_RAW + p
        for p in [
            "00-training.nc",
            "01-augmented.nc",
            "bridge-arrays.npz",
        ]
    )
    for job in path_jobs():
        base = OUTPUT + "/jobs/" + job["id"]
        required.update(
            base + "/" + p
            for p in [
                "job.json",
                "inputs.json",
                "membership.json",
                "sampling-start.json",
                "sampling-diagnostics.csv",
                "result.json",
                "attempt-evidence.json",
            ]
        )
        required.update(base + suffix for suffix in ["-spec.json", ".log", ".supervisor.json"])
        required.update(
            STORE + "/" + job["id"] + suffix for suffix in [".nc", ".loglikelihood.npz"]
        )
    timings = sorted((root / OUTPUT / "invocations").glob("*.json"))
    required.update(str(p.relative_to(root)) for p in timings)
    if not required.issubset(pins):
        raise ValueError("complete reviewed raw/node/path closure required before parsing")
    for name, status in [
        (SOURCE_GATE, "accepted_curvature_path_resolution"),
        (STOP_REVIEW, "accepted_fold001_retained_fold002_numerical_stop"),
    ]:
        review = json.loads((root / name).read_text())
        if (
            review.get("status") != status
            or review.get("independent_checker") is not True
            or not review.get("files")
            or any(pins.get(p) != h for p, h in review["files"].items())
        ):
            raise ValueError("complete prospective and stop-review reference closure required")
    plan = json.loads((root / OUTPUT / "plan.json").read_text())
    summary = json.loads((root / OUTPUT / "run-summary.json").read_text())
    if (
        plan.get("jobs") != path_jobs()
        or not plan.get("files")
        or any(pins.get(p) != h for p, h in plan["files"].items())
        or summary.get("status") != "path_computations_complete"
        or summary.get("accepted_nodes") != 32
        or summary.get("total_curvature_calls_charged") != 38
        or summary.get("total_curvature_calls_started") != 38
        or summary.get("new_slots_charged") != 32
        or summary.get("max_curvature_slots") != 248
    ):
        raise ValueError("complete original32node same-ledger path required")
    if CONTRACT not in pins:
        raise ValueError("reviewed native contract required before outcome loading")
    contract = tomllib.loads((root / CONTRACT).read_text())
    if not contract.get("inputs") or any(pins.get(p) != h for p, h in contract["inputs"].items()):
        raise ValueError("reviewed native input identities required before outcome loading")
    for job in path_jobs():
        inputs = json.loads((root / OUTPUT / "jobs" / job["id"] / "inputs.json").read_text())
        if inputs.get("files") != plan["files"] or inputs.get("source_files") != contract:
            raise ValueError("identical reviewed node source/contract identities required")
    cursor = 0
    active = 0.0
    for j, p in enumerate(timings):
        t = json.loads(p.read_text())
        if (
            p.name != f"{j:03d}.json"
            or t.get("plan_sha256") != sha256(root / OUTPUT / "plan.json")
            or t.get("start_node") != cursor
            or not cursor < t.get("end_node", -1) <= cursor + 3
            or type(t.get("seconds")) not in {int, float}
            or not math.isfinite(t["seconds"])
            or t["seconds"] < 0
        ):
            raise ValueError("complete immutable path timing required")
        cursor = t["end_node"]
        active += t["seconds"]
        if any(
            pins.get(p) != h
            for p, h in {**t.get("attempt_receipts", {}), **t.get("aggregate_files", {})}.items()
        ):
            raise ValueError("complete invocation evidence closure required")
    if (
        cursor != 32
        or not 0 <= active <= 1200
        or not math.isclose(active, summary.get("active_seconds", -1), abs_tol=1e-9, rel_tol=0)
    ):
        raise ValueError("same finite cumulative-active allocation required")
    return pins


def write_resolution(root, output):
    root, output = root.resolve(), output.resolve()
    if output.exists() or not output.is_relative_to(root / OUTPUT):
        raise ValueError("new resolution output inside counted path working store required")
    pins = verified_path(root)
    executed_code = {p: sha256(root / p) for p in CODE}
    if any(p in pins and pins[p] != h for p, h in executed_code.items()):
        raise ValueError("reviewed scientific helper source changed")
    pins.update(executed_code)
    lanes, _ = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    original = json.loads((root / SOURCE / "result.json").read_text())
    if len(original.get("events", [])) != 1:
        raise ValueError("one retained Tohoku event score required")
    canonical_bridge = ORIGINAL_RAW + "bridge-arrays.npz"
    if (
        original.get("bridge_arrays") != canonical_bridge
        or original.get("bridge_arrays_sha256") != pins[canonical_bridge]
    ):
        raise ValueError("canonical reviewed original bridge array reference required")
    training = json.loads((root / SOURCE / "ensembles/00-training/result.json").read_text())
    training_raw = ORIGINAL_RAW + "00-training.nc"
    if (
        training.get("posterior") != training_raw
        or training.get("posterior_sha256") != pins[training_raw]
    ):
        raise ValueError("canonical reviewed original training raw identity required")
    train, fold = bridge_indices(lane, original["job"]["sequence"], "training", None)
    membership = json.loads((root / SOURCE / "membership.json").read_text())
    if membership != {
        "train": [lane.record_ids[int(i)] for i in train],
        "test": [lane.record_ids[int(i)] for i in fold.test],
        "sequence": fold.sequence_id,
    }:
        raise ValueError("original exact cohort membership required")
    primary, repeat, check = [
        json.loads((root / OUTPUT / p).read_text())
        for p in [
            "primary-path-result.json",
            "repeat-path-result.json",
            "independent-repeat-check.json",
        ]
    ]
    original_event = original["events"][0]
    identity = {
        "target": original["job"]["target"],
        "kind": original["job"]["kind"],
        **{k: original_event[k] for k in ["event_id", "sequence", "records"]},
    }
    native_jacobian = float(np.log(lane.y[fold.test]).sum())
    repeat_training = json.loads((root / OUTPUT / "jobs/repeat-node-00/result.json").read_text())
    for role, value in [("primary", primary), ("repeat", repeat)]:
        if (
            any(value.get(k) != v for k, v in identity.items())
            or any(
                type(value.get(k)) not in {int, float}
                or not math.isfinite(value[k])
                or value[k] < 0
                for k in ["joint_log_mcse_delta", "normalized_mcse"]
            )
            or not math.isfinite(value.get("joint_log_predictive", float("nan")))
            or not math.isclose(
                value.get("normalized_event_score", float("nan")),
                value["joint_log_predictive"] / len(fold.test),
                abs_tol=1e-10,
                rel_tol=0,
            )
            or not math.isclose(
                value["normalized_mcse"],
                value["joint_log_mcse_delta"] / len(fold.test),
                abs_tol=1e-10,
                rel_tol=0,
            )
            or value.get("method") != "fixed_geometric_full_coefficient_coordinate_path"
            or not math.isclose(
                value.get("native_jacobian_subtracted_once", float("nan")),
                native_jacobian,
                abs_tol=1e-10,
                rel_tol=0,
            )
        ):
            raise ValueError("same-model finite primary/repeat native score certificate required")
        if role == "repeat" and value.get("source_training_posterior_sha") != repeat_training.get(
            "posterior_sha256"
        ):
            raise ValueError("fresh repeat training identity changed")
    repeat_raw = STORE + "/repeat-node-00.nc"
    if (
        repeat_training.get("posterior") != repeat_raw
        or repeat_training.get("posterior_sha256") != pins[repeat_raw]
    ):
        raise ValueError("reviewed fresh repeat raw identity required")
    difference = abs(primary["joint_log_predictive"] - repeat["joint_log_predictive"])
    error = math.hypot(primary["joint_log_mcse_delta"], repeat["joint_log_mcse_delta"])
    if (
        repeat.get("precision_passed") is not True
        or not math.isclose(difference, check["raw_difference"], abs_tol=1e-10, rel_tol=0)
        or not math.isclose(error, check["combined_mcse"], abs_tol=1e-10, rel_tol=0)
        or difference > 3 * error + 1e-6
    ):
        raise ValueError("independent repeat calculation changed")
    with np.load(root / STORE / "primary-combined-influences.npz") as raw:
        if set(raw.files) != {f"node_{j}" for j in range(17)}:
            raise ValueError("all17primarystage influences required")
        influences = [raw[f"node_{j}"] for j in range(17)]
    with np.load(checked_path(root, original["bridge_arrays"])) as raw:
        bridge = {p: raw[p] for p in raw.files}
    result = resolved_path_result(
        original,
        primary,
        check,
        influences,
        bridge,
        lane.y[fold.test],
        training_sha=training["posterior_sha256"],
    )
    prediction = SOURCE + "/held-out-record-predictions.csv"
    if prediction not in pins:
        raise ValueError("original training-only predictions must be reviewed")
    result.update(
        source_result=SOURCE + "/result.json",
        source_result_sha256=sha256(root / SOURCE / "result.json"),
        training_only_predictions=prediction,
        training_only_predictions_sha256=pins[prediction],
        primary_path=OUTPUT + "/primary-path-result.json",
        primary_path_sha256=pins[OUTPUT + "/primary-path-result.json"],
    )
    if any(not (root / p).is_file() or sha256(root / p) != h for p, h in executed_code.items()):
        raise ValueError("executed scientific helper source changed during resolution")
    if any(not (root / p).is_file() or sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("accepted evidence changed during resolution")
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "new_sampler_calls": 0,
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
        },
    )
    write_json(output / "result.json", result)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in [output / "inputs.json", output / "result.json"]},
    )
