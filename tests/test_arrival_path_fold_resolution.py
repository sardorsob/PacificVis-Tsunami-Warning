"""Path and direct-bridge estimates share a training ensemble within one held sequence."""

# pyright: basic
import math

import numpy as np
import pytest

from analysis.arrival.model_path_fold_resolution import path_fold_score
from analysis.arrival.model_scoring import mean_mcse


def fixture():
    rng = np.random.default_rng(20261128)
    base = rng.normal(size=(4, 2000))
    path = [2 * base, *[rng.normal(size=(4, 2000)) for _ in range(16)]]
    arrays = {f"training_influence_{i:03d}": (i + 1) * base for i in range(3)}
    arrays.update({f"augmented_influence_{i:03d}": rng.normal(size=(4, 2000)) for i in range(3)})
    original = {
        "events": [
            {
                "event_id": f"e{i}",
                "sequence": "s",
                "records": n,
                "normalized_event_score": -float(i + 1),
                "joint_log_predictive": -float(i + 1) * n,
                "precision_passed": i != 0,
            }
            for i, n in enumerate([49, 22, 9])
        ]
    }
    score = {
        "event_id": "e0",
        "sequence": "s",
        "records": 49,
        "normalized_event_score": -1.1,
        "joint_log_predictive": -1.1 * 49,
        "precision_passed": True,
        "joint_log_mcse_delta": math.sqrt(sum(mean_mcse(a) ** 2 for a in path)),
        "source_training_posterior_sha": "a" * 64,
    }
    return original, score, path, arrays


def test_full_fold_covariance_matches_direct_common_training_vector_oracle():
    original, score, path, arrays = fixture()
    result = path_fold_score(original, score, path, arrays, training_sha="a" * 64)
    shared = (
        path[0] / 49 + arrays["training_influence_001"] / 22 + arrays["training_influence_002"] / 9
    ) / 3
    variance = mean_mcse(shared) ** 2
    variance += sum((mean_mcse(a) / 49 / 3) ** 2 for a in path[1:])
    variance += sum(
        (mean_mcse(arrays[f"augmented_influence_{i:03d}"]) / n / 3) ** 2
        for i, n in [(1, 22), (2, 9)]
    )
    assert result["mcse_equal_event_score"] == pytest.approx(math.sqrt(variance))
    assert result["equal_event_score"] == pytest.approx((-1.1 - 2 - 3) / 3)
    assert original["events"][0]["precision_passed"] is False
    naive = sum((mean_mcse(a) / 49 / 3) ** 2 for a in path)
    naive += sum(
        (mean_mcse(arrays[f"{phase}_influence_{i:03d}"]) / n / 3) ** 2
        for phase in ["training", "augmented"]
        for i, n in [(1, 22), (2, 9)]
    )
    assert result["mcse_equal_event_score"] > math.sqrt(naive)


def test_foreign_training_draws_and_different_chain_alignment_are_rejected():
    original, score, path, arrays = fixture()
    with pytest.raises(ValueError):
        path_fold_score(original, score, path, arrays, training_sha="b" * 64)
    invalid = {**score, "source_training_posterior_sha": "unknown"}
    with pytest.raises(ValueError):
        path_fold_score(original, invalid, path, arrays, training_sha="unknown")
    arrays["training_influence_001"] = arrays["training_influence_001"][:, :1000]
    with pytest.raises(ValueError):
        path_fold_score(original, score, path, arrays, training_sha="a" * 64)
