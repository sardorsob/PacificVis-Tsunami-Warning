"""Independent mean-curve, likelihood and protected-training oracles."""

# pyright: basic
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from scipy.stats import multivariate_normal

from analysis.arrival import model_curvature as curve
from analysis.arrival.model_scale import (
    build_scale_model,
    conditional_scale_effects,
    new_scale_event_predictions,
    simulate_scale_response,
)
from analysis.arrival.models import read_prior
from tests.test_arrival_model_scale import grouped_lane


def test_fixed_basis_reference_derivative_and_query_independence():
    d = np.array([20.0, 100.0, 500.0, 1000.0, 5000.0, 20000.0])
    b = curve.curvature_basis(d)
    np.testing.assert_allclose(b, np.log((d + 500) / (1.5 * d)), atol=1e-14)
    assert b[3] == 0
    assert curve.curvature_basis(np.array([100.0]))[0] == b[1]
    eps = 1e-5
    derivative = (
        curve.curvature_basis(d * np.exp(eps)) - curve.curvature_basis(d * np.exp(-eps))
    ) / (2 * eps)
    np.testing.assert_allclose(derivative, -500 / (d + 500), atol=1e-10)
    for invalid in [np.array([0.0]), np.array([-1.0]), np.array([np.inf])]:
        with pytest.raises(ValueError):
            curve.curvature_basis(invalid)


def test_curved_integral_matches_dense_covariance_and_nested_likelihood():
    lane = grouped_lane()
    prior = {**read_prior(Path.cwd(), lane.target, "base"), "gamma_sd": 0.5}
    model = curve.build_curvature_model(lane, prior)
    potential = model.compile_logp(vars=[model["event_marginal_likelihood"]])
    point = {
        "alpha": 0.1,
        "beta": -0.05,
        "gamma": 0.4,
        "tau_event_log__": np.log(0.2),
        "sigma_anchor_log__": np.log([0.6, 0.3, 0.12]),
    }
    d = lane.distance_km
    mean = 0.1 - 0.05 * np.log(d / 1000) + 0.4 * np.log((d + 500) / (1.5 * d))
    sigma = np.interp(np.log(d), np.log([500, 2000, 5000]), [0.6, 0.3, 0.12])
    expected = 0.0
    for event in set(lane.event_ids):
        ids = np.array([i for i, e in enumerate(lane.event_ids) if e == event])
        expected += cast(Any, multivariate_normal).logpdf(
            lane.response[ids],
            mean=mean[ids],
            cov=np.diag(sigma[ids] ** 2) + 0.2**2 * np.ones((len(ids), len(ids))),
        )
    assert potential(point) == pytest.approx(expected, abs=1e-10)
    old = build_scale_model(lane, prior)
    old_likelihood = old.compile_logp(vars=[old["event_marginal_likelihood"]])
    assert potential({**point, "gamma": 0.0}) == pytest.approx(
        old_likelihood({k: v for k, v in point.items() if k != "gamma"}), abs=1e-10
    )


def test_held_response_and_distance_mutations_cannot_change_training_target():
    lane = grouped_lane()
    prior = {**read_prior(Path.cwd(), lane.target, "base"), "gamma_sd": 0.5}
    ids = np.array([0, 2])
    changed = replace(
        lane, response=lane.response.copy(), distance_km=lane.distance_km.copy(), x=lane.x.copy()
    )
    changed.response[1] = 9999
    changed.distance_km[1] = 99
    changed.x[1] = -9
    first = curve.build_curvature_model(lane, prior, indices=ids)
    second = curve.build_curvature_model(changed, prior, indices=ids)
    point = first.initial_point()
    assert first.compile_logp()(point) == second.compile_logp()(point)


def test_simulation_and_new_event_predictions_nest_existing_model():
    lane = grouped_lane()
    truth = {
        "alpha": 0.15,
        "beta": -0.05,
        "gamma": 0.4,
        "tau_event": 0.2,
        "sigma_anchor": [0.6, 0.3, 0.12],
    }
    response, effects = curve.simulate_curvature_response(lane, truth, seed=411)
    baseline, old_effects = simulate_scale_response(lane, truth, seed=411)
    np.testing.assert_allclose(
        response - baseline, 0.4 * np.log((lane.distance_km + 500) / (1.5 * lane.distance_km))
    )
    assert effects == old_effects
    changed, _ = curve.simulate_curvature_response(
        replace(lane, response=np.full(3, 9999)), truth, seed=411
    )
    np.testing.assert_array_equal(response, changed)
    hyper = {
        "alpha": np.zeros(1000),
        "beta": np.zeros(1000),
        "gamma": np.zeros(1000),
        "tau_event": np.full(1000, 0.2),
        "sigma_anchor": np.full((1000, 3), 0.1),
    }
    old = {k: v for k, v in hyper.items() if k != "gamma"}
    np.testing.assert_allclose(
        curve.new_curvature_event_predictions(hyper, lane.distance_km, seed=412),
        new_scale_event_predictions(old, lane.distance_km, seed=412),
    )
    chain = {
        k: v.reshape((4, 250, 3) if k == "sigma_anchor" else (4, 250)) for k, v in hyper.items()
    }
    oldchain = {k: v for k, v in chain.items() if k != "gamma"}
    expected, events = conditional_scale_effects(lane, oldchain, seed=413, indices=np.arange(3))
    actual, actual_events = curve.conditional_curvature_effects(
        lane, chain, seed=413, indices=np.arange(3)
    )
    assert events == actual_events
    np.testing.assert_allclose(actual, expected, atol=1e-15)


def test_seven_parameter_gradient_matches_independent_dense_target():
    lane = grouped_lane()
    prior = {**read_prior(Path.cwd(), lane.target, "base"), "gamma_sd": 0.5}
    model = curve.build_curvature_model(lane, prior)
    point = {
        "alpha": 0.1,
        "beta": -0.05,
        "gamma": 0.4,
        "tau_event_log__": np.log(0.2),
        "sigma_anchor_log__": np.log([0.6, 0.3, 0.12]),
    }
    d = lane.distance_km

    def dense(p):
        tau = np.exp(p["tau_event_log__"])
        anchors = np.exp(p["sigma_anchor_log__"])
        sigma = np.interp(np.log(d), np.log([500, 2000, 5000]), anchors)
        mean = (
            p["alpha"] + p["beta"] * np.log(d / 1000) + p["gamma"] * np.log((d + 500) / (1.5 * d))
        )
        answer = 0.0
        for event in set(lane.event_ids):
            ids = np.array([i for i, e in enumerate(lane.event_ids) if e == event])
            answer += cast(Any, multivariate_normal).logpdf(
                lane.response[ids],
                mean=mean[ids],
                cov=np.diag(sigma[ids] ** 2) + tau**2 * np.ones((len(ids), len(ids))),
            )
        answer -= 0.5 * sum((p[k] / prior[k + "_sd"]) ** 2 for k in ["alpha", "beta", "gamma"])
        answer -= 0.5 * ((tau / prior["tau_sd"]) ** 2 + np.sum((anchors / prior["sigma_sd"]) ** 2))
        return answer + p["tau_event_log__"] + np.sum(p["sigma_anchor_log__"])

    expected = []
    for key in point:
        for j in range(3 if key == "sigma_anchor_log__" else 1):
            plus, minus = ({k: np.array(v).copy() for k, v in point.items()} for _ in range(2))
            if key == "sigma_anchor_log__":
                plus[key][j] += 1e-5
                minus[key][j] -= 1e-5
            else:
                plus[key] += 1e-5
                minus[key] -= 1e-5
            expected.append((dense(plus) - dense(minus)) / (2e-5))
    np.testing.assert_allclose(model.compile_dlogp()(point), expected, atol=1e-6, rtol=1e-5)


def test_nonzero_curvature_conditional_effect_and_new_event_covariance():
    lane = grouped_lane()
    count = 12000
    hyper = {
        "alpha": np.full((4, 3000), 0.1),
        "beta": np.full((4, 3000), -0.05),
        "gamma": np.full((4, 3000), 0.4),
        "tau_event": np.full((4, 3000), 0.2),
        "sigma_anchor": np.broadcast_to([0.6, 0.3, 0.12], (4, 3000, 3)).copy(),
    }
    u, events = curve.conditional_curvature_effects(lane, hyper, seed=761, indices=np.arange(3))
    d = lane.distance_km[:2]
    sigma = np.interp(np.log(d), np.log([500, 2000, 5000]), [0.6, 0.3, 0.12])
    covariance = np.diag(sigma**2) + 0.04 * np.ones((2, 2))
    residual = lane.response[:2] - (
        0.1 - 0.05 * np.log(d / 1000) + 0.4 * np.log((d + 500) / (1.5 * d))
    )
    mean = 0.04 * np.ones(2) @ np.linalg.solve(covariance, residual)
    variance = 0.04 - 0.04**2 * np.ones(2) @ np.linalg.solve(covariance, np.ones(2))
    assert events[0] == "e1"
    assert abs(u[:, :, 0].mean() - mean) < 4 * np.sqrt(variance / count)
    assert u[:, :, 0].var() == pytest.approx(variance, rel=0.03)
    flat = {k: v.reshape((count, 3) if k == "sigma_anchor" else (count,)) for k, v in hyper.items()}
    flat["sigma_anchor"][:] = 1e-10
    native = curve.new_curvature_event_predictions(flat, lane.distance_km, seed=762)
    normal = np.log(native / lane.reference_minutes) - (
        0.1 - 0.05 * lane.x + 0.4 * np.log((lane.distance_km + 500) / (1.5 * lane.distance_km))
    )
    np.testing.assert_allclose(normal[:, 0], normal[:, 2], atol=1e-8)
