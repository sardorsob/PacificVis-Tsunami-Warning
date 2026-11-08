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


def test_unreviewed_attempt_is_rejected_before_any_science_parser(tmp_path, monkeypatch):
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT

    folder = tmp_path / OUTPUT
    source = tmp_path / "stub.py"
    source.write_text("source")
    write_json(
        folder / "plan.json",
        {
            "cases": [{"id": f"fold-{j:03d}"} for j in range(29)],
            "memberships": {f"fold-{j:03d}": {} for j in range(29)},
            "files": {"stub.py": sha256(source)},
        },
    )
    write_json(
        folder / "run-summary.json",
        {
            "status": "complete",
            "computed_folds": 29,
            "calls_charged": 62,
            "calls_started": 62,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_json(
        folder / "review-acceptance.json",
        {
            "status": "accepted_all_curvature_sequence_computations",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {
                "stub.py": sha256(source),
                **{
                    str((folder / p).relative_to(tmp_path)): sha256(folder / p)
                    for p in ["plan.json", "run-summary.json"]
                },
            },
        },
    )
    write_json(folder / "jobs/fold-000/result.json", {"unreviewed": True})

    def forbidden(*args, **kwargs):
        raise AssertionError("must not reach unreviewed science parser")

    monkeypatch.setattr("scripts.run_arrival_curvature_sequences.case_artifacts", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
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
