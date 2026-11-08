"""Predictive integration and Monte Carlo precision for the declared event joint score."""

import math

import numpy as np
import pytest

from analysis.arrival.model_scoring import aggregate_score, event_score, fold_score


def test_score_integrates_density_before_logging_and_normalizes_records() -> None:
    log_density = np.array([[-2.0, -4.0] * 1000] * 4)
    result, influence = event_score(log_density, records=3)
    expected = math.log((math.exp(-2) + math.exp(-4)) / 2)
    assert result["joint_log_predictive"] == pytest.approx(expected)
    assert result["normalized_event_score"] == pytest.approx(expected / 3)
    assert abs(result["joint_log_predictive"] - log_density.mean()) > 0.3
    assert influence.shape == log_density.shape and abs(influence.mean()) < 1e-14


def test_constant_density_has_exact_zero_mcse_without_fake_ess() -> None:
    result, influence = event_score(np.full((4, 1000), -1700.0), records=100)
    assert result["normalized_event_score"] == -17
    assert result["normalized_mcse"] == 0
    np.testing.assert_array_equal(influence, np.zeros((4, 1000)))


def test_fold_score_carries_covariance_between_event_integrals() -> None:
    rng = np.random.default_rng(17)
    first = rng.normal(0, 0.2, (4, 5000))
    second = first.copy()
    result = fold_score(np.stack([first, second]), np.array([1, 1]))
    one, _ = event_score(first, records=1)
    assert result["equal_event_score"] == pytest.approx(one["normalized_event_score"])
    assert result["mcse_equal_event_score"] == pytest.approx(one["normalized_mcse"])
    assert result["mcse_equal_event_score"] > one["normalized_mcse"] / math.sqrt(2) * 1.2
    with pytest.raises(ValueError):
        event_score(first[:, :1], records=1)


def test_density_delta_mcse_matches_lognormal_iid_oracle() -> None:
    values = np.random.default_rng(17).normal(0, 0.2, (4, 5000))
    result, _ = event_score(values, records=1)
    expected = math.sqrt(math.expm1(0.2**2) / values.size)
    assert result["normalized_mcse"] == pytest.approx(expected, rel=0.15)
    assert abs(result["joint_log_predictive"] - 0.2**2 / 2) < 5 * expected


def test_extreme_weight_concentration_is_reported_not_hidden() -> None:
    values = np.full((4, 1000), -100000.0)
    values[0, 0] = 0
    result, _ = event_score(values, records=10)
    assert result["density_weight_concentration_ess"] == 1
    assert result["joint_log_predictive"] == pytest.approx(-math.log(values.size))


def test_primary_aggregation_weights_events_and_can_fail_after_event_screens_pass():
    folds = [
        {
            "events": 2,
            "equal_event_score": 1.0,
            "mcse_equal_event_score": 0.003,
            "event_precision_passed": True,
        },
        {
            "events": 1,
            "equal_event_score": 4.0,
            "mcse_equal_event_score": 0.002,
            "event_precision_passed": True,
        },
    ]
    result = aggregate_score(folds, max_mcse=0.002)
    assert result["equal_event_score"] == 2
    assert result["mcse_equal_event_score"] == pytest.approx(
        math.sqrt((2 * 0.003) ** 2 + 0.002**2) / 3
    )
    assert not result["precision_passed"]
