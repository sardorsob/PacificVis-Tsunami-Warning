"""Independent dense Gaussian and direct-scale integration oracles."""

# pyright: basic
import math

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.stats import multivariate_normal, norm

from analysis.arrival.model_quadrature import RegressionQuadrature


@pytest.mark.parametrize("design", [np.ones((5, 1)), np.c_[np.ones(5), [-2, -1, 0, 1, 2]]])
def test_collapsed_gaussian_density_and_logscale_derivative_match_dense(design):
    y = np.array([0.3, -0.2, 0.4, 0.1, -0.15])
    prior = np.array([0.5, 0.25])[: design.shape[1]]
    model = RegressionQuadrature(y, design, prior, 0.4)

    def dense(t):
        sigma = np.exp(t)
        w = design * prior
        return multivariate_normal.logpdf(y, cov=np.eye(len(y)) * sigma**2 + w @ w.T)

    for t in [-5.0, -1.0, 2.0]:
        assert model.log_likelihood(t) == pytest.approx(dense(t), rel=1e-10, abs=1e-9)
        h = 1e-5
        assert (model.log_likelihood(t + h) - model.log_likelihood(t - h)) / (
            2 * h
        ) == pytest.approx((dense(t + h) - dense(t - h)) / (2 * h), rel=1e-7, abs=1e-5)


def test_evidence_ratio_and_coefficient_posterior_match_independent_oracles():
    y = np.array([0.2, -0.1, 0.3])
    x = np.c_[np.ones(3), [-1, 0, 1]]
    prior = np.array([0.5, 0.25])
    scale = 0.4
    model = RegressionQuadrature(y, x, prior, scale)

    def evidence(yy, xx):
        w = xx * prior
        value, error = quad(
            lambda s: (
                multivariate_normal.pdf(yy, cov=np.eye(len(yy)) * s * s + w @ w.T)
                * math.sqrt(2 / math.pi)
                / scale
                * np.exp(-0.5 * (s / scale) ** 2)
            ),
            0,
            np.inf,
            epsabs=1e-11,
            epsrel=1e-10,
        )
        assert error / value < 1e-7
        return math.log(value)

    assert model.log_evidence == pytest.approx(evidence(y, x), abs=1e-8)
    testy = np.array([0.5, -0.2])
    testx = np.array([[1, 2], [1, -0.5]])
    scored = model.joint_logpdf(testy, testx)
    assert scored["log_predictive"] == pytest.approx(
        evidence(np.r_[y, testy], np.vstack([x, testx])) - evidence(y, x), abs=1e-8
    )
    sigma = np.array([0.01, 0.3, 3.0])
    means, covs = model.conditional_coefficients(sigma)
    for j, s in enumerate(sigma):
        covariance = np.linalg.inv(np.diag(1 / prior**2) + x.T @ x / s**2)
        np.testing.assert_allclose(means[j], covariance @ x.T @ y / s**2, atol=1e-11)
        np.testing.assert_allclose(covs[j], covariance, atol=1e-11)
    out = model.marginal_predictions(testy, testx)
    m, c = model.conditional_coefficients(model.node_sigma)
    for j in range(2):
        mu = m @ testx[j]
        sd = np.sqrt(model.node_sigma**2 + np.einsum("i,kij,j->k", testx[j], c, testx[j]))
        for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
            assert np.sum(
                model.node_weights * norm.cdf((out[f"q{round(q * 100):02d}"][j] - mu) / sd)
            ) == pytest.approx(q, abs=2e-9)
    assert model.node_normalizer_error < 1e-8
    assert out["maximum_cdf_refinement_difference"] < 1e-7


def test_near_exact_fit_boundary_is_not_hidden_by_a_scale_floor():
    with pytest.raises(ValueError, match="exact.fit"):
        RegressionQuadrature(np.ones(3), np.ones((3, 1)), np.array([0.5]), 0.4)
    model = RegressionQuadrature(np.array([0.2]), np.ones((1, 1)), np.array([0.5]), 0.4)
    assert math.isfinite(model.log_evidence)


def test_reordered_duplicated_and_rank_deficient_designs_are_explicit():
    y = np.array([0.2, -0.1, 0.3, 0.4, -0.3])
    x = np.c_[np.ones(5), np.ones(5)]
    prior = np.array([0.5, 0.25])
    model = RegressionQuadrature(y, x, prior, 0.4)
    reduced = RegressionQuadrature(y, np.ones((5, 1)), np.array([np.sqrt(np.sum(prior**2))]), 0.4)
    assert model.rank == 1 and model.log_evidence == pytest.approx(reduced.log_evidence, abs=1e-10)
    order = np.array([3, 0, 4, 1, 2])
    reordered = RegressionQuadrature(y[order], x[order], prior, 0.4)
    assert reordered.log_evidence == pytest.approx(model.log_evidence, abs=1e-10)
    duplicated = RegressionQuadrature(np.repeat(y, 2), np.repeat(x, 2, axis=0), prior, 0.4)
    assert duplicated.n == 10 and abs(duplicated.log_evidence - model.log_evidence) > 0.1
    score = model.joint_logpdf(np.array([3.5]), np.array([[1, 1]]))
    assert score["direct_integral_agreement"] < 1e-8


def test_small_positive_orthogonal_residual_matches_independent_asymptotic_integral():
    y = 1.0 + np.arange(5) * 1e-6
    x = np.ones((5, 1))
    a = 0.4
    b = 0.5
    model = RegressionQuadrature(y, x, np.array([b]), a)
    residual2 = float(np.sum((y - y.mean()) ** 2))
    n = len(y)
    approximate = (
        -(n - 1) / 2 * math.log(2 * math.pi)
        - 0.5 * math.log(n)
        + norm.logpdf(y.mean(), scale=b)
        + math.log(math.sqrt(2 / math.pi) / a)
        - math.log(2)
        + (2 - n) / 2 * math.log(residual2 / 2)
        + math.lgamma((n - 2) / 2)
    )
    assert model.log_evidence == pytest.approx(approximate, abs=1e-6)
    assert model.tail_fraction_bound < 1e-8
