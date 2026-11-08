"""Complete-cohort gates and source-specific prediction units must survive report assembly."""

# pyright: basic
import pytest

from analysis.arrival.evidence import write_json
from analysis.arrival.model_sequence_comparison import normalize_predictions, verify_complete_cv


def row():
    return {
        "record_id": "r",
        "event_id": "e",
        "sequence": "s",
        "distance_km": "3000",
        "seen_site_in_training": "False",
        "observed_minutes": "2",
        "pit": ".4",
        "q05": ".1",
        "q25": ".5",
        "q50": "1",
        "q75": "2",
        "q95": "3",
    }


def test_incomplete_computations_are_rejected_before_reading_outcomes(tmp_path):
    source = tmp_path / "artifacts/models/arrival-timing/bridge-sequence-continuation-v2"
    write_json(source / "run-summary.json", {"status": "needs_review", "completed_folds": 0})
    with pytest.raises(ValueError, match="complete"):
        verify_complete_cv(tmp_path)


def test_analytic_prediction_aliases_preserve_units_false_and_unassessed_precision():
    out = normalize_predictions([row()], "T-OBS")[0]
    assert out["observed_native_minutes"] == 2 and out["seen_site"] is False
    assert out["coverage90_numerically_ambiguous"] is None
    assert out["prediction_precision_passed"] is None
    signed = {
        **row(),
        "target": "T-CAL",
        "observed_minutes": "0",
        "q05": "-4",
        "q25": "-2",
        "q50": "0",
    }
    assert normalize_predictions([signed], "T-CAL")[0]["observed_native_minutes"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"target": "T-CAL"},
        {"seen_site_in_training": "unknown"},
        {"prediction_precision_passed": "False"},
        {"pit": "nan"},
    ],
)
def test_source_target_boolean_and_numeric_precision_mismatches_are_not_repaired(change):
    with pytest.raises(ValueError):
        normalize_predictions([{**row(), **change}], "T-OBS")


def complete_receipt(root):
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_sequence_comparison import CONTINUATION

    folder = root / CONTINUATION
    write_json(
        folder / "run-summary.json",
        {
            "status": "computations_complete",
            "completed_folds": 72,
            "planned_folds": 72,
            "logical_completed_folds": 83,
        },
    )
    write_json(folder / "plan.json", {"cases": []})
    write_json(folder / "reviewed-resolutions.json", {})
    receipt = {
        "status": "accepted_all_logical_sequence_computations",
        "independent_checker": "toy-checker",
        "reserved_outcomes": "sealed",
        "plan_sha256": sha256(folder / "plan.json"),
        "files": {
            str((folder / n).relative_to(root)): sha256(folder / n)
            for n in [
                "plan.json",
                "run-summary.json",
                "reviewed-resolutions.json",
            ]
        },
    }
    write_json(folder / "review-acceptance.json", receipt)
    return folder, receipt


def test_empty_final_review_cannot_admit_self_pinned_unreviewed_science(tmp_path):
    folder, receipt = complete_receipt(tmp_path)
    receipt["files"] = {}
    write_json(folder / "review-acceptance.json", receipt)
    with pytest.raises(ValueError, match="complete reviewed"):
        verify_complete_cv(tmp_path)


def test_changed_completion_evidence_invalidates_review(tmp_path):
    folder, _ = complete_receipt(tmp_path)
    write_json(folder / "reviewed-resolutions.json", {"changed": True})
    with pytest.raises(ValueError, match="changed"):
        verify_complete_cv(tmp_path)


def test_unreviewed_science_is_rejected_before_being_read(tmp_path, monkeypatch):
    from analysis.arrival.model_sequence_comparison import collect_models

    complete_receipt(tmp_path)
    monkeypatch.setattr("analysis.arrival.model_data.load_lanes", lambda _: ({}, {"inputs": {}}))
    # The absent original plan must be refused as unreviewed before an open is attempted.
    with pytest.raises(ValueError, match="every consumed science artifact"):
        collect_models(tmp_path)


def test_missing_native_input_review_is_rejected_before_outcome_loader(tmp_path, monkeypatch):
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_data import CONTRACT
    from analysis.arrival.model_sequence_comparison import collect_models

    folder, receipt = complete_receipt(tmp_path)
    contract = tmp_path / CONTRACT
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text('[inputs]\n"outcomes.csv" = "' + "a" * 64 + '"\n')
    receipt["files"][CONTRACT] = sha256(contract)
    write_json(folder / "review-acceptance.json", receipt)

    def forbidden(_):
        raise AssertionError("outcome loader must remain unopened")

    monkeypatch.setattr("analysis.arrival.model_data.load_lanes", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
        collect_models(tmp_path)
