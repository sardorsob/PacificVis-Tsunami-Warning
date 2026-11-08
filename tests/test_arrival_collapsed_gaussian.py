"""Dense Gaussian oracles for the common/variable-scale coefficient-and-event integral."""

# pyright: basic
import numpy as np
import pytest
from scipy.stats import multivariate_normal

from analysis.arrival.model_collapsed import CollapsedGaussian
from analysis.arrival.model_quadrature import RegressionQuadrature
from analysis.arrival.model_scale import scale_weights


def fixture(variable):
    y = np.array([0.2, -0.1, 0.4, 0.3, -0.2, 0.5, 0.1, -0.3])
    distance = np.array([200.0, 700, 1200, 2500, 4000, 7000, 10000, 15000])
    x = np.c_[np.ones(8), np.log(distance / 1000)]
    events = np.array(["e0", "e0", "e1", "e1", "e2", "e2", "e3", "e3"])
    weights = scale_weights(distance) if variable else np.ones((8, 1))
    prior = np.array([0.5, 0.25])
    return y, x, events, weights, prior


@pytest.mark.parametrize("variable", [False, True])
def test_collapsed_likelihood_and_coefficients_match_dense_covariance(variable):
    y, x, e, w, prior = fixture(variable)
    model = CollapsedGaussian(y, x, e, w, prior)
    values = (
        np.array([[0.6, 0.3, 0.1, 0.2], [0.03, 0.07, 0.12, 0.0], [0.8, 0.2, 0.3, 1.0]])
        if variable
        else np.array([[0.3, 0.2], [0.05, 0.0], [0.8, 1.0]])
    )
    z = np.array([[float(a == b) for b in sorted(set(e))] for a in e])
    design = x * prior
    ll, mean, precision = model.evaluate(values, coefficients=True)
    for j, v in enumerate(values):
        sigma = w @ v[:-1]
        base = np.diag(sigma**2) + v[-1] ** 2 * (z @ z.T)
        dense = multivariate_normal.logpdf(y, cov=base + design @ design.T)
        assert ll[j] == pytest.approx(dense, abs=1e-9)
        p = np.eye(2) + design.T @ np.linalg.solve(base, design)
        np.testing.assert_allclose(precision[j], p, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(
            mean[j], np.linalg.solve(p, design.T @ np.linalg.solve(base, y)), atol=1e-10
        )
    newy = np.array([0.5, -0.3, 0.2])
    newx = x[[1, 3, 6]]
    neww = w[[1, 3, 6]]
    got = model.new_event_logpdf(values, newy, newx, neww)
    for j, v in enumerate(values):
        mu = (newx * prior) @ mean[j]
        covariance = np.diag((neww @ v[:-1]) ** 2) + v[-1] ** 2 * np.ones((3, 3))
        covariance += (newx * prior) @ np.linalg.inv(precision[j]) @ (newx * prior).T
        assert got[j] == pytest.approx(
            multivariate_normal.logpdf(newy, mean=mu, cov=covariance), abs=1e-10
        )


def test_equal_anchor_and_zero_event_limits_and_row_permutations():
    y, x, e, w, prior = fixture(True)
    variable = CollapsedGaussian(y, x, e, w, prior)
    common = CollapsedGaussian(y, x, e, np.ones((8, 1)), prior)
    a = variable.evaluate(np.array([[0.3, 0.3, 0.3, 0.2], [0.3, 0.3, 0.3, 0.0]]))
    b = common.evaluate(np.array([[0.3, 0.2], [0.3, 0.0]]))
    np.testing.assert_allclose(a, b, atol=1e-10)
    regression = RegressionQuadrature(y, x, prior, 0.4)
    assert b[1] == pytest.approx(regression.log_likelihood(np.log(0.3)), abs=1e-10)
    order = np.array([5, 0, 7, 3, 2, 6, 1, 4])
    shuffled = CollapsedGaussian(y[order], x[order], e[order], w[order], prior)
    np.testing.assert_allclose(
        shuffled.evaluate(np.array([[0.3, 0.4, 0.1, 0.2]])),
        variable.evaluate(np.array([[0.3, 0.4, 0.1, 0.2]])),
        atol=1e-10,
    )
