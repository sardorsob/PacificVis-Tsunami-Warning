"""A resolved score replaces only the failed integral and keeps its native measure."""

# pyright: basic

import numpy as np
import pytest

from analysis.arrival.model_bridge_path import path_score
from analysis.arrival.model_curvature_resolution import resolved_path_result


def case():
    native = np.full(100, np.exp(3.0))
    logs = [np.full((4, 1000), -1700.0) for _ in range(17)]
    primary, influences = path_score(logs, (np.arange(17) / 16) ** 2, records=100, jacobian=300.0)
    primary.update(
        event_id="event",
        sequence="sequence",
        records=100,
        target="NCEI-native-duration",
        kind="mean-curvature",
        source_training_posterior_sha="a" * 64,
    )
    original = {
        "job": {"kind": "mean-curvature", "target": "NCEI-native-duration", "prior": "base"},
        "status": "precision_failure",
        "prediction_precision_passed": True,
        "events": [
            {
                "event_id": "event",
                "sequence": "sequence",
                "records": 100,
                "precision_passed": False,
                "normalized_event_score": -999.0,
            }
        ],
        "observation_measure": "native_minutes_Jacobian_already_applied_once",
    }
    repeat = {
        "agreement_passed": True,
        "primary_designated_before_fitting": True,
        "score_to_use": "primary_never_select_favorable_repeat",
    }
    return original, primary, repeat, influences, native


def test_same_model_resolution_uses_primary_once_and_keeps_direct_failure_visible():
    original, primary, repeat, influences, native = case()
    result = resolved_path_result(
        original, primary, repeat, influences, {}, native, training_sha="a" * 64
    )
    assert result["status"] == "computed_pending_review"
    assert result["events"][0]["normalized_event_score"] == pytest.approx(-20.0)
    assert result["fold_score"]["equal_event_score"] == pytest.approx(-20.0)
    assert result["fold_score"]["mcse_equal_event_score"] == 0
    assert result["prediction_precision_passed"] is True
    assert result["retained_direct_bridge_status"] == "precision_failure"
    assert original["events"][0]["normalized_event_score"] == -999.0


@pytest.mark.parametrize("change", ["jacobian", "repeat", "training", "model", "measure"])
def test_wrong_measure_endpoint_or_failed_repeat_cannot_promote(change):
    original, primary, repeat, influences, native = case()
    if change == "jacobian":
        primary["native_jacobian_subtracted_once"] = 600.0
    elif change == "repeat":
        repeat["agreement_passed"] = False
    elif change == "training":
        primary["source_training_posterior_sha"] = "b" * 64
    elif change == "model":
        primary["kind"] = "distance-scale"
    else:
        original["observation_measure"] = "log_response"
    with pytest.raises(ValueError):
        resolved_path_result(
            original, primary, repeat, influences, {}, native, training_sha="a" * 64
        )
