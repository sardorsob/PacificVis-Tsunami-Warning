"""Deterministic event integrals retain covariance among other shared-training scores."""

# pyright: basic
import math

import numpy as np
import pytest

from analysis.arrival.model_score_resolution import hybrid_fold_score
from analysis.arrival.model_scoring import mean_mcse


def fixture():
    events = [
        {
            "event_id": f"e{i}",
            "sequence": "s",
            "records": n,
            "normalized_event_score": -float(i + 1),
            "precision_passed": i != 0,
            "overlap": 0.8,
        }
        for i, n in enumerate([49, 22, 9])
    ]
    original = {
        "events": events,
        "job": {"target": "T-OBS", "kind": "event", "sequence": "s", "prior": "base"},
    }
    rng = np.random.default_rng(2026)
    shared = rng.normal(size=(4, 2000))
    arrays = {f"training_influence_{i:03d}": shared * (i + 1) for i in range(3)}
    arrays.update({f"augmented_influence_{i:03d}": rng.normal(size=(4, 2000)) for i in range(3)})
    fixed = {
        "e0": {
            "event_id": "e0",
            "sequence": "s",
            "target": "T-OBS",
            "kind": "event",
            "records": 49,
            "normalized_event_score": -1.1,
            "joint_log_predictive": -1.1 * 49,
            "precision_passed": True,
            "monte_carlo_used": False,
            "numerical_error_estimate_per_record": 1e-8,
            "max_refinement_agreement_nats_per_record": 1e-10,
        }
    }
    return original, arrays, fixed


def test_hybrid_score_keeps_shared_training_covariance_and_separates_numeric_error():
    original, arrays, fixed = fixture()
    result = hybrid_fold_score(original, fixed, arrays)
    assert result["equal_event_score"] == pytest.approx((-1.1 - 2 - 3) / 3)
    shared = (arrays["training_influence_001"] / 22 + arrays["training_influence_002"] / 9) / 3
    variance = mean_mcse(shared) ** 2
    variance += sum(
        (mean_mcse(arrays[f"augmented_influence_{i:03d}"]) / n / 3) ** 2
        for i, n in [(1, 22), (2, 9)]
    )
    assert result["mcse_equal_event_score"] == pytest.approx(math.sqrt(variance))
    assert result["mean_deterministic_error_estimate"] == pytest.approx(1e-8 / 3)
    assert result["events"] == 3 and result["deterministic_event_scores"] == 1
    assert original["events"][0]["precision_passed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", "T-CAL"),
        ("records", 50),
        ("sequence", "other"),
        ("precision_passed", False),
        ("monte_carlo_used", True),
    ],
)
def test_resolution_cannot_change_target_membership_or_precision(field, value):
    original, arrays, fixed = fixture()
    fixed["e0"][field] = value
    with pytest.raises(ValueError):
        hybrid_fold_score(original, fixed, arrays)
