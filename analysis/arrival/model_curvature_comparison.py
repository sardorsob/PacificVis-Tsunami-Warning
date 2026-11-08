"""Complete-cohort gate and native-minute collection for the curvature candidate."""

# pyright: basic
from __future__ import annotations

import hashlib
import json
import tomllib

import numpy as np

from analysis.arrival.evidence import checked_path, read_rows, sha256
from analysis.arrival.model_scoring import aggregate_score
from analysis.arrival.model_sequence_comparison import normalize_predictions
from analysis.arrival.model_sequence_report import validate_predictions

OUTPUT = "artifacts/models/arrival-timing/mean-curvature-sequence-v1"


def verify_complete_curvature(root):
    """Require independent full collection acceptance before loading any outcomes."""
    folder = root / OUTPUT
    gate_path = folder / "review-acceptance.json"
    gate = json.loads(gate_path.read_text())
    if (
        gate.get("status") != "accepted_all_curvature_sequence_computations"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not gate.get("files")
    ):
        raise ValueError("complete independently reviewed curvature CV required")
    pins = {**gate["files"], str(gate_path.relative_to(root)): sha256(gate_path)}
    for name, digest in pins.items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("accepted curvature evidence changed")

    def read(name):
        path = folder / name
        if str(path.relative_to(root)) not in pins:
            raise ValueError("complete reviewed science closure required")
        return json.loads(path.read_text())

    summary, plan = read("run-summary.json"), read("plan.json")
    if (
        summary.get("status") != "complete"
        or summary.get("computed_folds") != 29
        or summary.get("confirmation_outcomes_parsed") is not False
        or summary.get("reserved_outcomes") != "sealed"
        or len(plan.get("cases", [])) != 29
        or len(plan.get("memberships", {})) != 29
        or not 62 <= summary.get("calls_charged", -1) <= 248
        or summary.get("calls_charged", 249) > 248
        or summary.get("calls_charged") != summary.get("calls_started")
    ):
        raise ValueError("all29folds and inclusive sampler accounting required")
    if not plan.get("files") or any(pins.get(p) != h for p, h in plan["files"].items()):
        raise ValueError("complete reviewed source closure required")
    from scripts.run_arrival_curvature_sequences import case_artifacts

    for case in plan["cases"]:
        attempt = folder / "jobs" / case["id"]
        raw = root / "data/processed/models/mean-curvature-sequence-v1" / case["id"]
        inventory = {p for base in [attempt, raw] for p in base.rglob("*") if p.is_file()}
        inventory.update(
            [
                attempt.with_name(case["id"] + "-spec.json"),
                attempt.with_suffix(".log"),
                attempt.with_suffix(".supervisor.json"),
            ]
        )
        # case_artifacts reads science values. Admit every file before that call.
        if any(str(p.relative_to(root)) not in pins for p in inventory):
            raise ValueError("complete reviewed science closure required before parsing")
        files, manifest = case_artifacts(root, case, plan["memberships"][case["id"]], plan["files"])
        files[str(manifest.relative_to(root))] = sha256(manifest)
        if any(pins.get(p) != h for p, h in files.items()):
            raise ValueError("complete reviewed attempt and raw evidence required")
        if json.loads(manifest.read_text()) != {
            "case_id": case["id"],
            "files": {p: h for p, h in files.items() if p != str(manifest.relative_to(root))},
        }:
            raise ValueError("complete immutable attempt manifest required")
    return plan, pins


def assemble_candidate(lane, results, predictions, cohort_sha256):
    """Validate native events and event-weighted MC variance, never average fold means."""
    from analysis.arrival.model_data import sequence_folds

    folds = list(sequence_folds(lane))
    if len(results) != len(folds):
        raise ValueError("complete distinct sequence results required")
    by_sequence = {r["job"]["sequence"]: r for r in results}
    if len(by_sequence) != len(folds) or set(by_sequence) != {f.sequence_id for f in folds}:
        raise ValueError("complete distinct sequence results required")
    validate_predictions(lane, predictions)
    events, scores = [], []
    for fold in folds:
        result = by_sequence[fold.sequence_id]
        if (
            result.get("status") != "computed_pending_review"
            or result.get("score_precision_passed") is not True
            or result.get("prediction_precision_passed") is not True
            or result.get("observation_measure") != "native_minutes_Jacobian_already_applied_once"
            or result["job"].get("kind") != "mean-curvature"
            or result["job"].get("target") != lane.target
            or result["job"].get("prior") != "base"
        ):
            raise ValueError("resolved native-measure curvature result required")
        expected = sorted({lane.event_ids[int(i)] for i in fold.test})
        rows = result["events"]
        if len(rows) != len(expected) or {r["event_id"] for r in rows} != set(expected):
            raise ValueError("complete distinct held events required")
        for row in rows:
            ids = sorted(
                lane.record_ids[int(i)]
                for i in fold.test
                if lane.event_ids[int(i)] == row["event_id"]
            )
            n = len(ids)
            value, error = row["normalized_event_score"], row["normalized_mcse"]
            if (
                row["records"] != n
                or row["sequence"] != fold.sequence_id
                or row.get("precision_passed") is not True
                or not np.isfinite([value, error, row["joint_log_predictive"]]).all()
                or not 0 <= error <= 0.005
                or not np.isclose(row["joint_log_predictive"] / n, value, atol=1e-10, rtol=0)
            ):
                raise ValueError("native event score membership or precision changed")
            events.append(
                {
                    **{
                        k: row[k]
                        for k in [
                            "event_id",
                            "sequence",
                            "records",
                            "joint_log_predictive",
                            "normalized_event_score",
                            "normalized_mcse",
                        ]
                    },
                    "target": lane.target,
                    "cohort_sha256": cohort_sha256,
                    "record_membership_sha256": hashlib.sha256(
                        json.dumps(ids, separators=(",", ":")).encode()
                    ).hexdigest(),
                    "precision_passed": True,
                    "normalized_deterministic_error": 0.0,
                }
            )
        score = result["fold_score"]
        if (
            score.get("event_precision_passed") is not True
            or score.get("events") != len(expected)
            or not np.isclose(
                score["equal_event_score"],
                np.mean([r["normalized_event_score"] for r in rows]),
                atol=1e-10,
                rtol=0,
            )
        ):
            raise ValueError("equal-event fold score changed")
        scores.append(score)
    summary = aggregate_score(scores, max_mcse=0.002)
    if not summary["precision_passed"]:
        raise ValueError("global Monte Carlo precision failed")
    summary.update(
        target=lane.target,
        kind="mean-curvature",
        records=int(lane.included.sum()),
        cohort_sha256=cohort_sha256,
        row_weighted_joint_score=sum(e["joint_log_predictive"] for e in events)
        / int(lane.included.sum()),
        monte_carlo_standard_error=summary["mcse_equal_event_score"],
        mean_numerical_error_estimate=0.0,
        monte_carlo_used=True,
    )
    return {"events": events, "predictions": predictions, "folds": scores, "summary": summary}


def collect_curvature(root):
    plan, pins = verify_complete_curvature(root)
    from analysis.arrival.model_data import CONTRACT, load_lanes

    if CONTRACT not in pins:
        raise ValueError("reviewed contract required before outcome loading")
    preflight = tomllib.loads((root / CONTRACT).read_text())
    if not preflight.get("inputs") or any(pins.get(p) != h for p, h in preflight["inputs"].items()):
        raise ValueError("all frozen native inputs must be reviewed before parsing")
    lanes, contract = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    cohort_sha256 = hashlib.sha256(
        json.dumps(
            {
                "target": lane.target,
                "contract": contract,
                "primary_record_ids": sorted(np.array(lane.record_ids)[lane.included].tolist()),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    results, predictions = [], []
    for case in plan["cases"]:
        folder = root / OUTPUT / "jobs" / case["id"]
        for name in ["result.json", "held-out-record-predictions.csv"]:
            if str((folder / name).relative_to(root)) not in pins:
                raise ValueError("complete reviewed science closure required")
        result = json.loads((folder / "result.json").read_text())
        if result["job"] != case:
            raise ValueError("frozen curvature job changed")
        results.append(result)
        predictions += normalize_predictions(
            read_rows(folder / "held-out-record-predictions.csv"), lane.target
        )
    return assemble_candidate(lane, results, predictions, cohort_sha256), pins
