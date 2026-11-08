"""Equal-event paired contrasts with sequence-cluster uncertainty and cohort guards."""

# pyright: basic
import math
from hashlib import sha256

import numpy as np
import pytest

from analysis.arrival.model_comparison import paired_sequence_comparison


def rows(values, sequences):
    return [
        {
            "event_id": f"e{i}",
            "sequence": g,
            "records": i + 1,
            "joint_log_predictive": v * (i + 1),
            "normalized_event_score": v,
            "target": "T-OBS",
            "cohort_sha256": sha256(b"fixed-design").hexdigest(),
            "record_membership_sha256": sha256(f"members-{i}".encode()).hexdigest(),
            "precision_passed": True,
        }
        for i, (v, g) in enumerate(zip(values, sequences, strict=True))
    ]


def test_equal_event_mean_and_cluster_sandwich_match_independent_matrix_oracle():
    groups = ["a", "a", "b", "c"]
    first = rows([1, 3, -1, 4], groups)
    second = rows([0, 0, 0, 0], groups)
    summary, contributions = paired_sequence_comparison(first, second)
    assert summary["paired_mean_difference"] == 1.75
    delta = np.array([1, 3, -1, 4], float)
    incidence = np.array([[1, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    expected = math.sqrt(3 / 2 * np.sum((incidence @ (delta - delta.mean())) ** 2) / 16)
    assert summary["sequence_cluster_se"] == pytest.approx(expected)
    assert summary["sequence_clusters"] == 3 and summary["events"] == 4
    assert {
        r["sequence"]: r["mean_difference_without_cluster"] for r in contributions
    } == pytest.approx({"a": 1.5, "b": 8 / 3, "c": 1.0})
    reverse, _ = paired_sequence_comparison(second, first)
    assert reverse["paired_mean_difference"] == -1.75
    assert reverse["sequence_cluster_ci95_lower"] == pytest.approx(
        -summary["sequence_cluster_ci95_upper"]
    )


def test_singleton_clusters_reduce_to_standard_mean_error_and_mcse_stays_separate():
    a = rows([0, 1, 2, 4], ["a", "b", "c", "d"])
    b = rows([0, 0, 0, 0], ["a", "b", "c", "d"])
    summary, _ = paired_sequence_comparison(a, b, first_mcse=0.001, second_mcse=0.002)
    assert summary["sequence_cluster_se"] == pytest.approx(np.std([0, 1, 2, 4], ddof=1) / 2)
    assert summary["paired_numerical_mcse"] == pytest.approx(math.sqrt(0.001**2 + 0.002**2))


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", "T-CAL"),
        ("cohort_sha256", "other"),
        ("record_membership_sha256", "different"),
        ("sequence", "different"),
        ("precision_passed", False),
    ],
)
def test_different_targets_cohorts_memberships_or_unresolved_scores_are_not_comparable(
    field, value
):
    a = rows([0, 1], ["a", "b"])
    b = rows([0, 1], ["a", "b"])
    b[0][field] = value
    with pytest.raises(ValueError):
        paired_sequence_comparison(a, b)


@pytest.mark.parametrize("key", ["cohort_sha256", "record_membership_sha256"])
@pytest.mark.parametrize("value", ["unknown", "", None, "a" * 63, "z" * 64])
def test_identically_unresolved_or_malformed_hashes_cannot_establish_identity(key, value):
    a = rows([0, 1], ["a", "b"])
    b = rows([0, 1], ["a", "b"])
    a[0][key] = b[0][key] = value
    with pytest.raises(ValueError):
        paired_sequence_comparison(a, b)
