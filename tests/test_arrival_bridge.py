"""Bridge roots, orientation, derivative and overlap against known Normal densities."""

# pyright: basic
import math

import numpy as np
import pytest
from scipy.special import expit
from scipy.stats import norm

from analysis.arrival.model_bridge import bridge_fold_score, bridge_score


def normal_case(shift=0.8, width=0.7, seed=27261108):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(4, 4000))
    y = rng.normal(shift, width, size=(4, 3000))
    c = -1200.0
    a = c + norm.logpdf(x, shift, width) - norm.logpdf(x)
    b = c + norm.logpdf(y, shift, width) - norm.logpdf(y)
    return a, b, c


def test_constant_ratio_has_exact_root_and_zero_influence():
    score, first, second = bridge_score(
        np.full((4, 1000), -1700.0), np.full((4, 1500), -1700.0), records=100
    )
    assert score["joint_log_predictive"] == pytest.approx(-1700, abs=1e-10)
    assert score["normalized_mcse"] == 0
    assert score["overlap"] == pytest.approx(1)
    assert score["precision_passed"]
    np.testing.assert_allclose(first, 0, atol=1e-12)
    np.testing.assert_allclose(second, 0, atol=1e-12)


def test_unequal_ensemble_gaussian_root_orientation_and_fixedpoint_derivative():
    a, b, truth = normal_case()
    score, first, second = bridge_score(a, b, records=10)
    reverse, rfirst, rsecond = bridge_score(-b, -a, records=10)
    assert abs(score["joint_log_predictive"] - truth) < 5 * score["joint_log_mcse_delta"]
    assert score["precision_passed"]
    assert reverse["joint_log_predictive"] == pytest.approx(-score["joint_log_predictive"])
    np.testing.assert_allclose(first, -rsecond, atol=1e-11)
    np.testing.assert_allclose(second, -rfirst, atol=1e-11)
    s0, s1 = a.size / (a.size + b.size), b.size / (a.size + b.size)

    def update(root):
        q0 = expit(math.log(s1 / s0) + a - root)
        p1 = expit(math.log(s0 / s1) - b + root)
        return root + math.log(q0.mean() / s1) - math.log(p1.mean() / s0)

    r = score["joint_log_predictive"]
    derivative = (update(r + 1e-4) - update(r - 1e-4)) / 2e-4
    assert derivative == pytest.approx(score["fixedpoint_derivative"], abs=1e-8)
    assert abs(first.mean()) < 1e-14 and abs(second.mean()) < 1e-14


def test_poor_overlap_cannot_pass_despite_a_finite_root():
    a, b, _ = normal_case(shift=9, width=1)
    score, _, _ = bridge_score(a, b, records=100)
    assert score["overlap"] < 0.1
    assert not score["precision_passed"]


def test_nonfinite_or_wrongly_shaped_ensembles_fail():
    with pytest.raises(ValueError):
        bridge_score(np.zeros((1, 4000)), np.zeros((4, 1000)), records=1)
    with pytest.raises(ValueError):
        bridge_score(np.full((4, 1000), np.nan), np.zeros((4, 1000)), records=1)


def test_fold_error_retains_shared_training_covariance():
    a, b, _ = normal_case()
    score, first, second = bridge_score(a, b, records=10)
    one = bridge_fold_score([score], [first], [second])
    two = bridge_fold_score([score, score], [first, first], [second, second])
    assert one["mcse_equal_event_score"] == pytest.approx(score["normalized_mcse"])
    # Training is shared; the two augmented ensembles are independent by contract.
    expected = (
        math.sqrt(
            score["training_influence_mcse"] ** 2 + score["augmented_influence_mcse"] ** 2 / 2
        )
        / 10
    )
    assert two["mcse_equal_event_score"] == pytest.approx(expected)
    assert two["mcse_equal_event_score"] > one["mcse_equal_event_score"] / math.sqrt(2)
