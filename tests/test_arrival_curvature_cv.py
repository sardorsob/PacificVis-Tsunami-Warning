"""Independent dense three-coefficient oracles, native units and held-event guards."""

# pyright: basic
import numpy as np
import pytest
import xarray as xr
from scipy.stats import multivariate_normal

from analysis.arrival.model_collapsed import CollapsedGaussian
from analysis.arrival.model_curvature_cv import (
    curvature_kernel,
    native_event_logpdf,
    posterior_components,
)
from analysis.arrival.model_data import VREF_KM_MIN
from analysis.arrival.model_scale import scale_weights


def fixture():
    y = np.array([0.2, -0.1, 0.4, 0.3, -0.2, 0.5, 0.1, -0.3])
    d = np.array([20.0, 700, 1200, 2500, 4000, 7000, 10000, 15000])
    e = np.array(["e0", "e0", "e1", "e1", "e2", "e2", "e3", "e3"])
    prior = {"alpha_sd": 0.5, "beta_sd": 0.25, "gamma_sd": 0.5}
    x = np.c_[np.ones(8), np.log(d / 1000), np.log((d + 500) / (1.5 * d))]
    return y, d, e, prior, x


def dense(y, x, e, w, prior, v):
    a = x * np.array([prior[k + "_sd"] for k in ["alpha", "beta", "gamma"]])
    covariance = np.diag((w @ v[:-1]) ** 2) + v[-1] ** 2 * (e[:, None] == e[None, :]) + a @ a.T
    return multivariate_normal.logpdf(y, cov=covariance)


def test_three_column_integral_conditional_native_density_and_gradients_match_dense():
    y, d, e, prior, x = fixture()
    kernel = curvature_kernel(y, d, e, prior)
    w = scale_weights(d)
    newd = np.array([100.0, 2000, 9000])
    newy = np.array([0.4, -0.2, 0.1])
    newe = np.array(["new"] * 3)
    native = np.exp(newy) * (newd / VREF_KM_MIN)
    nx = np.c_[np.ones(3), np.log(newd / 1000), np.log((newd + 500) / (1.5 * newd))]

    def reference(v):
        augmented = dense(
            np.r_[y, newy], np.r_[x, nx], np.r_[e, newe], scale_weights(np.r_[d, newd]), prior, v
        )
        return augmented - dense(y, x, e, w, prior, v) - np.log(native).sum()

    values = np.array([[0.6, 0.3, 0.1, 0.2], [0.3, 0.3, 0.3, 0.0], [0.05, 0.08, 0.12, 1.0]])
    np.testing.assert_allclose(
        kernel.evaluate(values), [dense(y, x, e, w, prior, v) for v in values], atol=1e-9
    )
    got = native_event_logpdf(kernel, values, newy, newd, native, newe)
    np.testing.assert_allclose(got, [reference(v) for v in values], atol=1e-9)
    for j in range(4):
        delta = np.eye(4)[j] * 1e-5
        center = values[0]
        observed = (
            native_event_logpdf(kernel, (center + delta)[None], newy, newd, native, newe)[0]
            - native_event_logpdf(kernel, (center - delta)[None], newy, newd, native, newe)[0]
        ) / 2e-5
        expected = (reference(center + delta) - reference(center - delta)) / 2e-5
        assert observed == pytest.approx(expected, abs=1e-5)
    with pytest.raises(ValueError, match="wholly new"):
        native_event_logpdf(kernel, values, newy, newd, native, np.array(["e0"] * 3))
    with pytest.raises(ValueError, match="aligned native"):
        native_event_logpdf(kernel, values, newy, newd, native * 60, newe)


def test_zero_prior_mean_does_not_remove_curvature_but_vanishing_sd_does():
    y, d, e, prior, x = fixture()
    values = np.array([[0.6, 0.3, 0.1, 0.2]])
    linear = CollapsedGaussian(y, x[:, :2], e, scale_weights(d), [0.5, 0.25])
    curved = curvature_kernel(y, d, e, prior)
    tiny = curvature_kernel(y, d, e, {**prior, "gamma_sd": 1e-12})
    np.testing.assert_allclose(tiny.evaluate(values), linear.evaluate(values), atol=1e-10)
    assert abs(curved.evaluate(values)[0] - linear.evaluate(values)[0]) > 1e-3


def test_predictive_components_keep_joint_coefficient_draws_and_anchor_order():
    rng = np.random.default_rng(43)
    beta = rng.normal(size=(4, 300))
    gamma = rng.normal(size=(4, 300))
    alpha = -beta * np.log(2) - gamma * np.log(5 / 6)
    post = xr.Dataset(
        {
            k: (("chain", "draw"), v)
            for k, v in [
                ("alpha", alpha),
                ("beta", beta),
                ("gamma", gamma),
                ("tau_event", np.full_like(alpha, 0.2)),
            ]
        }
    )
    post["sigma_anchor"] = xr.DataArray(
        np.full((4, 300, 3), 0.4),
        dims=("chain", "draw", "scale_anchor_km"),
        coords={"scale_anchor_km": [500, 2000, 5000]},
    )
    mean, sigma, tau = posterior_components(post, np.array([2000.0, 1000.0]))
    np.testing.assert_allclose(mean[..., 0], 0, atol=1e-14)
    np.testing.assert_allclose(sigma, 0.4, atol=1e-14)
    np.testing.assert_allclose(tau, 0.2)
    with pytest.raises(ValueError, match="anchor order"):
        posterior_components(
            post.assign_coords(scale_anchor_km=[5000, 2000, 500]), np.array([1000.0])
        )
