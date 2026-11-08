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

    def read(relative):
        path = root / relative
        if relative not in pins:
            raise ValueError("complete reviewed science closure required")
        return json.loads(path.read_text())

    continuation = OUTPUT + "/continuation-v2"
    summary = read(continuation + "/run-summary.json")
    plan = read(OUTPUT + "/plan.json")
    resumed = read(continuation + "/plan.json")
    if (
        summary.get("status") != "cv_computations_complete"
        or summary.get("logical_completed_folds") != 29
        or summary.get("planned_folds") != 29
        or summary.get("direct_accepted_folds") != 27
        or summary.get("reviewed_resolutions") != 2
        or summary.get("confirmation_outcomes_parsed") is not False
        or summary.get("reserved_outcomes") != "sealed"
        or len(plan.get("cases", [])) != 29
        or len(plan.get("memberships", {})) != 29
        or summary.get("calls_charged") != 96
        or summary.get("calls_started") != 96
        or summary.get("inherited_slots") != 53
        or summary.get("remaining_nominal_calls_at_start") != 43
        or resumed.get("cases") != plan["cases"]
        or resumed.get("original_plan_sha256") != pins[OUTPUT + "/plan.json"]
        or resumed.get("original_worker_files") != plan.get("files")
    ):
        raise ValueError("all29logicalfolds and inclusive96sampler accounting required")
    for sources in [plan.get("files"), resumed.get("files")]:
        if not sources or any(pins.get(p) != h for p, h in sources.items()):
            raise ValueError("complete reviewed source closure required")
    from scripts.run_arrival_curvature_completion import (
        GATE,
        PRECISION_OUTPUT,
        PRECISION_REVIEW,
        REHEARSAL,
    )
    from scripts.run_arrival_curvature_continuation import DERIVED, DERIVED_REVIEW
    from scripts.run_arrival_curvature_sequences import case_artifacts

    for receipt in [GATE, REHEARSAL, DERIVED_REVIEW, PRECISION_REVIEW]:
        review = read(receipt)
        if (
            review.get("independent_checker") is not True
            or not review.get("files")
            or any(pins.get(p) != h for p, h in review["files"].items())
        ):
            raise ValueError("complete reviewed continuation and resolution closure required")
    resolutions = {}
    for case_id, derived, receipt, status in [
        ("fold-002", DERIVED, DERIVED_REVIEW, "accepted_same_model_curvature_fold_resolution"),
        (
            "fold-008",
            PRECISION_OUTPUT,
            PRECISION_REVIEW,
            "accepted_same_model_curvature_precision_resolution",
        ),
    ]:
        prediction = OUTPUT + "/jobs/" + case_id + "/held-out-record-predictions.csv"
        resolutions[case_id] = {
            "receipt": receipt,
            "receipt_sha256": pins[receipt],
            "result": derived + "/result.json",
            "result_sha256": pins.get(derived + "/result.json"),
            "prediction": prediction,
            "prediction_sha256": pins.get(prediction),
        }
        proof = read(receipt)
        if (
            proof.get("status") != status
            or proof.get("derived_result") != derived + "/result.json"
            or proof.get("derived_result_sha256") != resolutions[case_id]["result_sha256"]
        ):
            raise ValueError("literal accepted same-model numerical resolution required")
    if (
        resumed.get("resolutions") != resolutions
        or gate.get("resolutions") != resolutions
        or read(GATE).get("status") != "accepted_curvature_completion_rehearsal"
        or read(REHEARSAL).get("status") != "accepted_first_curvature_completion_fold"
    ):
        raise ValueError("literal accepted same-model resolution registry required")
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
        if any(str(p.relative_to(root)) not in pins for p in inventory):
            raise ValueError("complete reviewed science closure required before parsing")
        if case["id"] in resolutions:
            resolution = resolutions[case["id"]]
            failed_path = OUTPUT + "/jobs/" + case["id"] + "/result.json"
            failed = read(failed_path)
            result = read(resolution["result"])
            if (
                failed.get("status") != "precision_failure"
                or failed.get("job") != case
                or result.get("job") != case
                or result.get("source_result") != failed_path
                or result.get("source_result_sha256") != pins[failed_path]
                or result.get("training_only_predictions") != resolution["prediction"]
                or result.get("training_only_predictions_sha256") != resolution["prediction_sha256"]
            ):
                raise ValueError(
                    "unchanged original failed result and training predictions required"
                )
            continue
        files, manifest = case_artifacts(root, case, plan["memberships"][case["id"]], plan["files"])
        files[str(manifest.relative_to(root))] = sha256(manifest)
        if any(pins.get(p) != h for p, h in files.items()):
            raise ValueError("complete reviewed attempt and raw evidence required")
        if json.loads(manifest.read_text()) != {
            "case_id": case["id"],
            "files": {p: h for p, h in files.items() if p != str(manifest.relative_to(root))},
        }:
            raise ValueError("complete immutable attempt manifest required")
    return {**plan, "resolutions": resolutions}, pins


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
        resolution = plan["resolutions"].get(case["id"])
        result_path = (
            resolution["result"] if resolution else str((folder / "result.json").relative_to(root))
        )
        prediction_path = (
            resolution["prediction"]
            if resolution
            else str((folder / "held-out-record-predictions.csv").relative_to(root))
        )
        if result_path not in pins or prediction_path not in pins:
            raise ValueError("complete reviewed science closure required")
        result = json.loads((root / result_path).read_text())
        if result["job"] != case:
            raise ValueError("frozen curvature job changed")
        results.append(result)
        predictions += normalize_predictions(read_rows(root / prediction_path), lane.target)
    candidate = assemble_candidate(lane, results, predictions, cohort_sha256)
    if any(sha256(checked_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("curvature comparison input drift")
    return candidate, pins
