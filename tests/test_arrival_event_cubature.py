"""Single-event normalizer integration must not add other held sequence members."""

# pyright: basic
import numpy as np
import pytest
from scipy.stats import multivariate_normal

from analysis.arrival.model_data import sequence_folds
from analysis.arrival.model_event_cubature import event_models, normalized_target
from tests.test_arrival_models import tiny_lane


def test_augmented_normalizer_adds_only_one_event_with_dense_density_oracle():
    lane = tiny_lane()
    fold = next(f for f in sequence_folds(lane) if f.sequence_id == "q1")
    sd = np.array([0.5, 0.25])
    train, augmented, held = event_models(lane, fold, "e1", sd)
    assert held.tolist() == [0] and train.n == 1 and augmented.n == 2
    ids = np.array([1, 0])
    x = np.c_[np.ones(2), lane.x[ids]] * sd
    covariance = 0.4**2 * np.eye(2) + 0.2**2 * np.eye(2) + x @ x.T
    expected = multivariate_normal.logpdf(lane.response[ids], np.zeros(2), covariance)
    assert augmented.evaluate(np.array([[0.4, 0.2]]))[0] == pytest.approx(expected, abs=1e-12)
    with pytest.raises(ValueError):
        event_models(lane, fold, "e2", sd)  # Training member is not a held event.


def test_rescaled_positive_prior_density_includes_both_halfnormal_constants():
    lane = tiny_lane()
    fold = sequence_folds(lane)[0]
    train, _, _ = event_models(lane, fold, "e1", np.array([0.5, 0.25]))
    z = np.array([[1.2, 0.7], [0.4, 1.8]])
    scales = np.array([0.4, 0.4])
    target = normalized_target(train, scales)
    expected = train.evaluate(z * scales) + np.log(2 / np.pi) - 0.5 * np.sum(z * z, axis=1)
    np.testing.assert_allclose(target(z), expected, atol=1e-12)
