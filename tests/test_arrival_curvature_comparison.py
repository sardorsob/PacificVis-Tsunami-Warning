"""Event weighting, frozen units and pre-outcome gates for new curvature CV."""

# pyright: basic
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from analysis.arrival.evidence import write_json
from analysis.arrival.model_curvature_comparison import (
    assemble_candidate,
    verify_complete_curvature,
)
from analysis.arrival.model_data import sequence_folds
from tests.test_arrival_models import tiny_lane


def toy():
    lane = replace(tiny_lane(), target="NCEI-native-duration")
    results, predictions = [], []
    for j, fold in enumerate(sequence_folds(lane)):
        events = []
        for i in fold.test:
            value = -2.0 if j == 0 else -8.0
            events.append(
                {
                    "event_id": lane.event_ids[i],
                    "sequence": fold.sequence_id,
                    "records": 1,
                    "joint_log_predictive": value,
                    "normalized_event_score": value,
                    "normalized_mcse": 0.001,
                    "precision_passed": True,
                }
            )
        results.append(
            {
                "job": {
                    "sequence": fold.sequence_id,
                    "target": lane.target,
                    "kind": "mean-curvature",
                    "prior": "base",
                },
                "status": "computed_pending_review",
                "score_precision_passed": True,
                "prediction_precision_passed": True,
                "observation_measure": "native_minutes_Jacobian_already_applied_once",
                "events": events,
                "fold_score": {
                    "events": len(events),
                    "equal_event_score": events[0]["normalized_event_score"],
                    "event_precision_passed": True,
                    "mcse_equal_event_score": 0.001,
                },
            }
        )
        for i, seen in zip(fold.test, fold.seen_site, strict=True):
            predictions.append(
                {
                    "record_id": lane.record_ids[i],
                    "event_id": lane.event_ids[i],
                    "sequence": fold.sequence_id,
                    "distance_km": lane.distance_km[i],
                    "seen_site": bool(seen),
                    "observed_native_minutes": lane.y[i],
                    "pit": 0.5,
                    **{f"q{q:02d}": float(q) for q in [5, 25, 50, 75, 95]},
                }
            )
    return lane, results, predictions


def test_two_event_sequence_and_single_event_have_equal_event_not_fold_weights():
    lane, results, predictions = toy()
    out = assemble_candidate(lane, results, predictions, "cohort")
    assert out["summary"]["events"] == 3 and out["summary"]["sequence_refits"] == 2
    assert out["summary"]["equal_event_score"] == pytest.approx(-4.0)
    assert out["summary"]["monte_carlo_standard_error"] == pytest.approx(np.sqrt(5) * 0.001 / 3)
    assert len({e["record_membership_sha256"] for e in out["events"]}) == 3


@pytest.mark.parametrize(
    "change",
    ["duplicate_event", "wrong_measure", "failed_precision", "bad_fold_mean", "missing_fold"],
)
def test_invalid_candidate_cannot_enter_comparison(change):
    lane, original, predictions = toy()
    results = deepcopy(original)
    if change == "duplicate_event":
        results[0]["events"][1] = dict(results[0]["events"][0])
    elif change == "wrong_measure":
        results[0]["observation_measure"] = "log_ratio"
    elif change == "failed_precision":
        results[0]["events"][0]["normalized_mcse"] = 0.006
    elif change == "bad_fold_mean":
        results[0]["fold_score"]["equal_event_score"] = -3.0
    else:
        results.pop()
    with pytest.raises(ValueError):
        assemble_candidate(lane, results, predictions, "cohort")


def test_incomplete_review_rejected_before_science_or_outcome_read(tmp_path):
    write_json(
        tmp_path
        / "artifacts/models/arrival-timing/mean-curvature-sequence-v1/review-acceptance.json",
        {"status": "checkpoint", "files": {}},
    )
    with pytest.raises(ValueError, match="complete independently"):
        verify_complete_curvature(tmp_path)


def complete_bundle(root, monkeypatch):
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts.run_arrival_curvature_completion import (
        GATE,
        PRECISION_OUTPUT,
        PRECISION_REVIEW,
        REHEARSAL,
    )
    from scripts.run_arrival_curvature_continuation import DERIVED, DERIVED_REVIEW

    source = root / "stub.py"
    source.write_text("source")
    worker = {"stub.py": sha256(source)}
    cases = [{"id": f"fold-{j:03d}", "sequence": f"seq-{j}"} for j in range(29)]
    plan = {"cases": cases, "memberships": {c["id"]: {} for c in cases}, "files": worker}
    write_json(root / OUTPUT / "plan.json", plan)
    write_json(root / OUTPUT / "run-summary.json", {"status": "cv_needs_review"})
    for case in cases:
        folder = root / OUTPUT / "jobs" / case["id"]
        raw = root / "data/processed/models/mean-curvature-sequence-v1" / case["id"]
        raw.mkdir(parents=True)
        (raw / "raw.nc").write_bytes(b"raw")
        write_json(
            folder / "result.json",
            {
                "job": case,
                "status": "precision_failure"
                if case["id"] in {"fold-002", "fold-008"}
                else "computed_pending_review",
            },
        )
        (folder / "held-out-record-predictions.csv").write_text("prediction")
        for path in [
            folder.with_name(case["id"] + "-spec.json"),
            folder.with_suffix(".supervisor.json"),
        ]:
            write_json(path, {})
        folder.with_suffix(".log").write_text("log")
        files = {
            str(p.relative_to(root)): sha256(p)
            for base in [folder, raw]
            for p in base.rglob("*")
            if p.is_file()
        }
        files.update(
            {
                str(p.relative_to(root)): sha256(p)
                for p in [
                    folder.with_name(case["id"] + "-spec.json"),
                    folder.with_suffix(".supervisor.json"),
                    folder.with_suffix(".log"),
                ]
            }
        )
        write_json(folder / "attempt-evidence.json", {"case_id": case["id"], "files": files})
    failed = OUTPUT + "/jobs/fold-002/result.json"
    prediction = OUTPUT + "/jobs/fold-002/held-out-record-predictions.csv"
    result = DERIVED + "/result.json"
    write_json(
        root / result,
        {
            "job": cases[2],
            "source_result": failed,
            "source_result_sha256": sha256(root / failed),
            "training_only_predictions": prediction,
            "training_only_predictions_sha256": sha256(root / prediction),
        },
    )
    proof = {"independent_checker": True, "files": worker}
    write_json(
        root / DERIVED_REVIEW,
        {
            **proof,
            "status": "accepted_same_model_curvature_fold_resolution",
            "derived_result": result,
            "derived_result_sha256": sha256(root / result),
        },
    )
    write_json(root / GATE, {**proof, "status": "accepted_curvature_completion_rehearsal"})
    write_json(root / REHEARSAL, {**proof, "status": "accepted_first_curvature_completion_fold"})
    resolution = {
        "fold-002": {
            "receipt": DERIVED_REVIEW,
            "receipt_sha256": sha256(root / DERIVED_REVIEW),
            "result": result,
            "result_sha256": sha256(root / result),
            "prediction": prediction,
            "prediction_sha256": sha256(root / prediction),
        }
    }
    failed8 = OUTPUT + "/jobs/fold-008/result.json"
    prediction8 = OUTPUT + "/jobs/fold-008/held-out-record-predictions.csv"
    result8 = PRECISION_OUTPUT + "/result.json"
    write_json(
        root / result8,
        {
            "job": cases[8],
            "source_result": failed8,
            "source_result_sha256": sha256(root / failed8),
            "training_only_predictions": prediction8,
            "training_only_predictions_sha256": sha256(root / prediction8),
        },
    )
    write_json(
        root / PRECISION_REVIEW,
        {
            **proof,
            "status": "accepted_same_model_curvature_precision_resolution",
            "derived_result": result8,
            "derived_result_sha256": sha256(root / result8),
        },
    )
    resolution["fold-008"] = {
        "receipt": PRECISION_REVIEW,
        "receipt_sha256": sha256(root / PRECISION_REVIEW),
        "result": result8,
        "result_sha256": sha256(root / result8),
        "prediction": prediction8,
        "prediction_sha256": sha256(root / prediction8),
    }
    write_json(
        root / OUTPUT / "continuation-v2/plan.json",
        {
            "cases": cases,
            "original_plan_sha256": sha256(root / OUTPUT / "plan.json"),
            "original_worker_files": worker,
            "resolutions": resolution,
            "files": worker,
        },
    )
    write_json(
        root / OUTPUT / "continuation-v2/run-summary.json",
        {
            "status": "cv_computations_complete",
            "logical_completed_folds": 29,
            "planned_folds": 29,
            "direct_accepted_folds": 27,
            "reviewed_resolutions": 2,
            "calls_charged": 96,
            "calls_started": 96,
            "inherited_slots": 53,
            "remaining_nominal_calls_at_start": 43,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    gate = {
        "status": "accepted_all_curvature_sequence_computations",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "resolutions": resolution,
        "files": {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()},
    }
    write_json(root / OUTPUT / "review-acceptance.json", gate)

    def checked_attempt(root, case, member, worker):
        path = root / OUTPUT / "jobs" / case["id"] / "attempt-evidence.json"
        import json

        return json.loads(path.read_text())["files"], path

    monkeypatch.setattr("scripts.run_arrival_curvature_sequences.case_artifacts", checked_attempt)
    return gate


def test_complete_continuation_maps_only_resolved_score_and_keeps_original_failure(
    tmp_path, monkeypatch
):
    import json

    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts.run_arrival_curvature_continuation import DERIVED

    complete_bundle(tmp_path, monkeypatch)
    plan, pins = verify_complete_curvature(tmp_path)
    assert len(plan["cases"]) == 29
    assert plan["resolutions"]["fold-002"]["result"] == DERIVED + "/result.json"
    assert OUTPUT + "/run-summary.json" in pins
    assert (
        json.loads((tmp_path / OUTPUT / "jobs/fold-002/result.json").read_text())["status"]
        == "precision_failure"
    )


@pytest.mark.parametrize(
    "change",
    [
        "unreviewed_attempt",
        "refunded_slots",
        "missing_resolution",
        "drop_lata_resolution",
        "wrong_prediction",
        "unreviewed_source",
        "old_summary_only",
    ],
)
def test_incomplete_continuation_cannot_enter_science(tmp_path, monkeypatch, change):
    import json

    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts.run_arrival_curvature_continuation import DERIVED

    gate = complete_bundle(tmp_path, monkeypatch)
    if change == "unreviewed_attempt":
        path = tmp_path / OUTPUT / "jobs/fold-000/extra.json"
        write_json(path, {})
    elif change == "refunded_slots":
        path = tmp_path / OUTPUT / "continuation-v2/run-summary.json"
        value = json.loads(path.read_text())
        value["calls_charged"] = value["calls_started"] = 94
        write_json(path, value)
        gate["files"][str(path.relative_to(tmp_path))] = sha256(path)
    elif change == "missing_resolution":
        gate["resolutions"] = {}
    elif change == "drop_lata_resolution":
        del gate["resolutions"]["fold-008"]
    elif change == "wrong_prediction":
        path = tmp_path / DERIVED / "result.json"
        value = json.loads(path.read_text())
        value["training_only_predictions"] = "alternate.csv"
        write_json(path, value)
        gate["files"][str(path.relative_to(tmp_path))] = sha256(path)
    elif change == "unreviewed_source":
        del gate["files"]["stub.py"]
    else:
        del gate["files"][OUTPUT + "/continuation-v2/run-summary.json"]
    write_json(tmp_path / OUTPUT / "review-acceptance.json", gate)
    with pytest.raises(ValueError):
        verify_complete_curvature(tmp_path)


def test_contract_input_gap_blocks_outcome_loader(tmp_path, monkeypatch):
    from analysis.arrival import model_curvature_comparison as module
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_data import CONTRACT

    p = tmp_path / CONTRACT
    p.parent.mkdir(parents=True)
    p.write_text('[inputs]\n"unreviewed.csv" = "' + "a" * 64 + '"\n')
    monkeypatch.setattr(module, "verify_complete_curvature", lambda _: ({}, {CONTRACT: sha256(p)}))

    def forbidden(*args):
        raise AssertionError("native outcome loader must remain unopened")

    monkeypatch.setattr("analysis.arrival.model_data.load_lanes", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
        module.collect_curvature(tmp_path)


def test_collector_uses_resolved_result_with_original_prediction_file(tmp_path, monkeypatch):
    import json

    from analysis.arrival import model_curvature_comparison as module
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_data import CONTRACT

    lane, results, predictions = toy()
    contract_file = tmp_path / CONTRACT
    contract_file.parent.mkdir(parents=True)
    contract_file.write_text('[inputs]\n"native.csv" = "reviewed"\n')
    cases, resolutions, tables = [], {}, {}
    for j, result in enumerate(results):
        case = {**result["job"], "id": f"fold-{j:03d}"}
        result["job"] = case
        cases.append(case)
        folder = tmp_path / module.OUTPUT / "jobs" / case["id"]
        target = folder / "result.json" if j == 0 else tmp_path / "resolved/result.json"
        write_json(target, result)
        prediction_path = folder / "held-out-record-predictions.csv"
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text("original prediction")
        tables[str(prediction_path)] = [p for p in predictions if p["sequence"] == case["sequence"]]
        if j:
            write_json(
                folder / "result.json", {"status": "precision_failure", "unusable_score": 999}
            )
            resolutions[case["id"]] = {
                "result": str(target.relative_to(tmp_path)),
                "prediction": str(prediction_path.relative_to(tmp_path)),
            }
    pins = {str(p.relative_to(tmp_path)): sha256(p) for p in tmp_path.rglob("*") if p.is_file()}
    # Input closure is exercised independently; this isolates score/prediction routing.
    pins["native.csv"] = "reviewed"
    monkeypatch.setattr(
        module,
        "verify_complete_curvature",
        lambda _: ({"cases": cases, "resolutions": resolutions}, pins),
    )
    monkeypatch.setattr(
        "analysis.arrival.model_data.load_lanes",
        lambda _: ({lane.target: lane}, {"contract": "toy"}),
    )
    monkeypatch.setattr(module, "read_rows", lambda p: tables[str(p)])
    monkeypatch.setattr(module, "normalize_predictions", lambda p, _: p)
    real_hash = module.sha256
    monkeypatch.setattr(
        module, "sha256", lambda p: "reviewed" if p.name == "native.csv" else real_hash(p)
    )
    (tmp_path / "native.csv").write_text("native")
    candidate, _ = module.collect_curvature(tmp_path)
    assert candidate["summary"]["equal_event_score"] == pytest.approx(-4)
    assert candidate["predictions"] == predictions
    failed = tmp_path / module.OUTPUT / "jobs/fold-001/result.json"
    assert json.loads(failed.read_text())["status"] == "precision_failure"


def test_report_requires_curvature_acceptance_before_baseline_outcomes(tmp_path, monkeypatch):
    from scripts import summarize_arrival_curvature_comparison as report_module

    for path in report_module.CODE:
        source = tmp_path / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("source")

    def missing_gate(root):
        raise ValueError("complete independently reviewed curvature CV required")

    def forbidden(root):
        raise AssertionError("baseline outcomes must remain unopened")

    monkeypatch.setattr(report_module, "collect_curvature", missing_gate)
    monkeypatch.setattr(report_module, "collect_models", forbidden)
    with pytest.raises(ValueError, match="independently reviewed"):
        report_module.report(tmp_path, tmp_path / "report")
    assert not (tmp_path / "report").exists()
