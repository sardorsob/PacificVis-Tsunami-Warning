"""Full-coordinate power path: endpoint targets, gradients and shared-stage covariance."""

# pyright: basic
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import xarray as xr
from scipy.optimize import brentq
from scipy.special import expit
from scipy.stats import halfnorm, multivariate_normal, norm

from analysis.arrival.model_bridge_path import build_path_model, path_held_loglikelihood, path_score
from analysis.arrival.model_bridge_path_validation import known_geometry, normal_path
from analysis.arrival.model_scale import build_scale_model, scale_weights
from analysis.arrival.models import read_prior
from tests.test_arrival_model_scale import grouped_lane


def test_path_endpoints_and_fractional_density_gradient_match_dense_gaussians():
    lane = grouped_lane()
    prior = read_prior(Path.cwd(), lane.target, "base")
    train, held = np.array([0, 1]), np.array([2])
    point = {
        "alpha": np.array(0.1),
        "beta": np.array(-0.05),
        "tau_event_log__": np.log(0.2),
        "sigma_anchor_log__": np.log([0.6, 0.3, 0.12]),
    }

    def dense(p, t, prior_only=False):
        a, b = float(p["alpha"]), float(p["beta"])
        tau, s = float(np.exp(p["tau_event_log__"])), np.exp(p["sigma_anchor_log__"])
        sd = scale_weights(lane.distance_km) @ s
        total = norm.logpdf(a, scale=prior["alpha_sd"]) + norm.logpdf(b, scale=prior["beta_sd"])
        total += halfnorm.logpdf(tau, scale=prior["tau_sd"])
        total += halfnorm.logpdf(s, scale=prior["sigma_sd"]).sum()
        total += float(p["tau_event_log__"]) + np.sum(p["sigma_anchor_log__"])
        if prior_only:
            return total
        for ids, power in [(train, 1.0), (held, t)]:
            total += power * cast(Any, multivariate_normal).logpdf(
                lane.response[ids],
                a + b * lane.x[ids],
                np.diag(sd[ids] ** 2) + tau**2 * np.ones((len(ids), len(ids))),
            )
        return total

    for t in [0.0, 0.125, 0.5, 0.875, 1.0]:
        model = build_path_model(lane, prior, train, held, t)
        # The installed PyMC prior constants differ from SciPy by 5.714e-9,
        # independent of t and the checked variance values. They cancel in ratios.
        assert model.compile_logp()(point) == pytest.approx(dense(point, t), abs=1e-8)
        expected_likelihood = dense(point, t) - dense(point, t, prior_only=True)
        assert model.compile_logp(vars=model.potentials)(point) == pytest.approx(
            expected_likelihood, abs=1e-10
        )
        if t in [0.0, 1.0]:
            original = build_scale_model(lane, prior, indices=train if t == 0 else np.arange(3))
            assert model.compile_logp()(point) == pytest.approx(
                original.compile_logp()(point), abs=1e-10
            )
        if t == 0.5:
            expected = []
            for key in ["alpha", "beta", "tau_event_log__", "sigma_anchor_log__"]:
                for k in range(3 if key == "sigma_anchor_log__" else 1):
                    plus, minus = (
                        {n: np.array(v).copy() for n, v in point.items()} for _ in range(2)
                    )
                    if key == "sigma_anchor_log__":
                        plus[key][k] += 1e-5
                        minus[key][k] -= 1e-5
                    else:
                        plus[key] += 1e-5
                        minus[key] -= 1e-5
                    expected.append((dense(plus, t) - dense(minus, t)) / 2e-5)
            np.testing.assert_allclose(model.compile_dlogp()(point), expected, atol=2e-6)
    changed = replace(lane, response=lane.response + np.array([0, 0, 999.0]))
    first = build_path_model(lane, prior, train, held, 0).compile_logp()(point)
    assert build_path_model(changed, prior, train, held, 0).compile_logp()(point) == first
    with pytest.raises(ValueError):
        build_path_model(lane, prior, np.array([0]), np.array([1]), 0.5)


def test_constant_ratio_telescopes_and_native_jacobian_is_applied_once():
    logs = [np.full((4, 1000), -1700.0) for _ in range(9)]
    score, stages = path_score(logs, np.linspace(0, 1, 9), records=100, jacobian=300)
    assert score["joint_log_predictive"] == pytest.approx(-2000, abs=1e-9)
    assert score["normalized_mcse"] == 0 and score["precision_passed"]
    assert all(np.all(v == 0) for v in stages)


def test_shared_middle_influence_matches_independent_implicit_root_perturbation():
    rng = np.random.default_rng(18261108)
    times = np.array([0.0, 0.5, 1.0])
    samples = [rng.normal(t, 1, (4, 4000)) for t in times]
    logs = [-10 + s - 0.5 for s in samples]
    score, combined = path_score(logs, times, records=100)
    assert score["precision_passed"]
    assert abs(score["joint_log_predictive"] + 10) < 5 * score["joint_log_mcse_delta"]
    naive = np.sqrt(sum(s["joint_log_mcse_delta"] ** 2 for s in score["edges"]))
    assert score["joint_log_mcse_delta"] > 1.1 * naive

    def weighted_root(a, b, which, epsilon):
        weights = np.ones_like(a if which == 0 else b)
        weights[0, 0] += epsilon

        def equation(r):
            left, right = expit(a - r), expit(r - b)
            return (np.average(left, weights=weights) if which == 0 else left.mean()) - (
                np.average(right, weights=weights) if which == 1 else right.mean()
            )

        return cast(Any, brentq)(equation, -30, 10, xtol=1e-13)

    estimates = []
    for delta in [-0.01, 0.01]:
        estimates.append(
            weighted_root(0.5 * logs[0], 0.5 * logs[1], 1, delta)
            + weighted_root(0.5 * logs[1], 0.5 * logs[2], 0, delta)
        )
    derivative = (estimates[1] - estimates[0]) / 0.02
    assert derivative == pytest.approx(combined[1][0, 0] / combined[1].size, rel=0.005, abs=1e-9)


def test_known_gaussian_path_normalizers_include_quadratic_and_determinant_terms():
    mean0, mean1, cov0, cov1 = known_geometry()
    times = np.linspace(0, 1, 9)
    points = np.random.default_rng(17).normal(size=(7, 6))
    states = normal_path(mean0, mean1, cov0, cov1, times, -1700)
    for t, (mean, cov, logz) in zip(times, states, strict=True):
        expected = (1 - t) * cast(Any, multivariate_normal).logpdf(points, mean0, cov0)
        expected += t * (-1700 + cast(Any, multivariate_normal).logpdf(points, mean1, cov1))
        np.testing.assert_allclose(
            cast(Any, multivariate_normal).logpdf(points, mean, cov) + logz, expected, atol=1e-11
        )


def test_path_ratio_keeps_coefficients_explicit_and_integrates_one_shared_event():
    lane = grouped_lane()
    held = np.array([0, 1])
    post = xr.Dataset(
        {
            "alpha": (("chain", "draw"), np.full((4, 1000), 0.1)),
            "beta": (("chain", "draw"), np.full((4, 1000), -0.05)),
            "tau_event": (("chain", "draw"), np.full((4, 1000), 0.2)),
            "sigma_anchor": (("chain", "draw", "anchor"), np.tile([0.6, 0.3, 0.12], (4, 1000, 1))),
        }
    )
    sd = scale_weights(lane.distance_km[held]) @ [0.6, 0.3, 0.12]
    expected = cast(Any, multivariate_normal).logpdf(
        lane.response[held], 0.1 - 0.05 * lane.x[held], np.diag(sd**2) + 0.2**2 * np.ones((2, 2))
    )
    first = path_held_loglikelihood(lane, held, post)
    np.testing.assert_allclose(first, expected, atol=1e-12)
    post["alpha"] = post.alpha + 0.5
    assert not np.allclose(path_held_loglikelihood(lane, held, post), first)
    with pytest.raises(ValueError):
        path_held_loglikelihood(lane, np.array([0, 2]), post)
