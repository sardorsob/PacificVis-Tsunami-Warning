"""Independent Gaussian oracles for a fixed, positive distance-dependent SD curve."""

# pyright: basic
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from scipy.stats import multivariate_normal

from analysis.arrival.model_data import VREF_KM_MIN
from analysis.arrival.model_scale import (
    build_scale_model,
    conditional_scale_effects,
    new_scale_event_predictions,
    scale_prior_moments,
    scale_weights,
    simulate_scale_response,
)
from analysis.arrival.model_validation import conditional_event_effects
from analysis.arrival.models import build_model, read_prior
from tests.test_arrival_models import tiny_lane


def grouped_lane():
    lane = tiny_lane()
    response = np.array([0.2, -0.1, 0.3])
    distance = np.array([500.0, 3000.0, 10000.0])
    reference = distance / VREF_KM_MIN
    native = np.exp(response) * reference
    event_ids = ("e1", "e1", "e2")
    return replace(
        lane,
        target="NCEI-native-duration",
        rows=tuple(
            {
                **row,
                "target": "NCEI-native-duration",
                "event_id": event_ids[i],
                "distance_km": str(distance[i]),
                "reference_minutes": str(reference[i]),
                "target_minutes": str(native[i]),
            }
            for i, row in enumerate(lane.rows)
        ),
        event_ids=event_ids,
        distance_km=distance,
        reference_minutes=reference,
        x=np.log(distance / 1000),
        response=response,
        y=native,
    )


def test_scale_curve_is_convex_fixed_and_clamped_without_query_dependence() -> None:
    distances = np.array([10.0, 500.0, 1000.0, 2000.0, np.sqrt(2000 * 5000), 5000.0, 20000.0])
    weights = scale_weights(distances)
    np.testing.assert_allclose(weights.sum(axis=1), 1)
    assert (weights >= 0).all()
    np.testing.assert_allclose(
        weights[[0, 1, 2, 3, 4, 5, 6]],
        [[1, 0, 0], [1, 0, 0], [0.5, 0.5, 0], [0, 1, 0], [0, 0.5, 0.5], [0, 0, 1], [0, 0, 1]],
        atol=1e-15,
    )
    np.testing.assert_array_equal(scale_weights(np.array([1000.0]))[0], weights[2])
    mean, second = scale_prior_moments(weights, 0.4)
    np.testing.assert_allclose(mean, 0.4 * np.sqrt(2 / np.pi))
    assert second[1] == pytest.approx(0.16) and second[2] == pytest.approx(0.16 * (0.5 + 1 / np.pi))
    with pytest.raises(ValueError):
        scale_weights(np.array([0.0]))


def test_simulator_ignores_actual_outcomes_and_predictions_share_a_new_event() -> None:
    lane = grouped_lane()
    truth = {"alpha": 0.15, "beta": -0.05, "tau_event": 0.2, "sigma_anchor": [0.6, 0.3, 0.12]}
    first, _ = simulate_scale_response(lane, truth, seed=17)
    second, _ = simulate_scale_response(
        replace(lane, response=np.full(3, 999.0), y=np.ones(3)), truth, seed=17
    )
    np.testing.assert_array_equal(first, second)
    hyper = {
        "alpha": np.zeros(1000),
        "beta": np.zeros(1000),
        "tau_event": np.full(1000, 0.2),
        "sigma_anchor": np.full((1000, 3), 1e-10),
    }
    distance = np.array([500.0, 5000.0])
    native = new_scale_event_predictions(hyper, distance, seed=18)
    np.testing.assert_allclose(
        native[:, 0] / (distance[0] / VREF_KM_MIN),
        native[:, 1] / (distance[1] / VREF_KM_MIN),
        atol=1e-8,
    )


def test_heteroskedastic_integral_matches_dense_covariance_and_equal_scale_baseline() -> None:
    lane = grouped_lane()
    prior = read_prior(Path.cwd(), lane.target, "base")
    model = build_scale_model(lane, prior)
    point = {
        "alpha": 0.1,
        "beta": -0.05,
        "tau_event_log__": np.log(0.2),
        "sigma_anchor_log__": np.log([0.6, 0.3, 0.12]),
    }
    potential = model.compile_logp(vars=[model["event_marginal_likelihood"]])
    sigma = np.interp(np.log(lane.distance_km), np.log([500, 2000, 5000]), [0.6, 0.3, 0.12])
    assert len(set(sigma)) == 3 and np.linalg.matrix_rank(scale_weights(lane.distance_km)) == 3
    expected = 0.0
    for e in set(lane.event_ids):
        i = np.array([j for j, v in enumerate(lane.event_ids) if v == e])
        expected += cast(Any, multivariate_normal).logpdf(
            lane.response[i],
            mean=0.1 - 0.05 * lane.x[i],
            cov=np.diag(sigma[i] ** 2) + 0.2**2 * np.ones((len(i), len(i))),
        )
    assert potential(point) == pytest.approx(expected, abs=1e-10)
    base = build_model(lane, prior, parameterization="marginal")
    base_likelihood = base.compile_logp(vars=[base["event_marginal_likelihood"]])
    equal = {**point, "sigma_anchor_log__": np.log([0.3, 0.3, 0.3])}
    assert potential(equal) == pytest.approx(
        base_likelihood(
            {
                k: v
                for k, v in {**point, "sigma_log__": np.log(0.3)}.items()
                if k != "sigma_anchor_log__"
            }
        ),
        abs=1e-10,
    )

    def dense_target(p):
        a, b = float(p["alpha"]), float(p["beta"])
        tau = float(np.exp(p["tau_event_log__"]))
        anchors = np.exp(p["sigma_anchor_log__"])
        s = np.interp(np.log(lane.distance_km), np.log([500, 2000, 5000]), anchors)
        result = 0.0
        for event in set(lane.event_ids):
            idx = np.array([i for i, e in enumerate(lane.event_ids) if e == event])
            result += cast(Any, multivariate_normal).logpdf(
                lane.response[idx],
                mean=a + b * lane.x[idx],
                cov=np.diag(s[idx] ** 2) + tau**2 * np.ones((len(idx), len(idx))),
            )
        result -= 0.5 * (
            (a / prior["alpha_sd"]) ** 2
            + (b / prior["beta_sd"]) ** 2
            + (tau / prior["tau_sd"]) ** 2
            + np.sum((anchors / prior["sigma_sd"]) ** 2)
        )
        return result + float(p["tau_event_log__"]) + np.sum(p["sigma_anchor_log__"])

    gradient = model.compile_dlogp()(point)
    expected_gradient = []
    for key in ["alpha", "beta", "tau_event_log__", "sigma_anchor_log__"]:
        for index in range(3 if key == "sigma_anchor_log__" else 1):
            plus, minus = (
                {k: np.array(v).copy() for k, v in point.items()},
                {k: np.array(v).copy() for k, v in point.items()},
            )
            if key == "sigma_anchor_log__":
                plus[key][index] += 1e-5
                minus[key][index] -= 1e-5
            else:
                plus[key] += 1e-5
                minus[key] -= 1e-5
            expected_gradient.append((dense_target(plus) - dense_target(minus)) / (2e-5))
    np.testing.assert_allclose(gradient, expected_gradient, atol=1e-6, rtol=1e-5)
    for anchors, tau in [([0.02, 0.4, 1.0], 2.0), ([0.6, 0.3, 0.12], 1e-12)]:
        p = {**point, "sigma_anchor_log__": np.log(anchors), "tau_event_log__": np.log(tau)}
        s = np.interp(np.log(lane.distance_km), np.log([500, 2000, 5000]), anchors)
        expected = 0.0
        for e in set(lane.event_ids):
            i = np.array([j for j, v in enumerate(lane.event_ids) if v == e])
            expected += cast(Any, multivariate_normal).logpdf(
                lane.response[i],
                mean=0.1 - 0.05 * lane.x[i],
                cov=np.diag(s[i] ** 2) + tau**2 * np.ones((len(i), len(i))),
            )
        assert potential(p) == pytest.approx(expected, abs=1e-9)
    permuted = build_scale_model(lane, prior, indices=np.array([2, 0, 1]))
    assert permuted.compile_logp(vars=[permuted["event_marginal_likelihood"]])(
        point
    ) == pytest.approx(potential(point), abs=1e-10)


def test_weighted_conditional_effects_match_normal_and_ignore_unused_outcomes() -> None:
    lane = grouped_lane()
    hyper = {
        "alpha": np.full((4, 10000), 0.1),
        "beta": np.full((4, 10000), -0.05),
        "tau_event": np.full((4, 10000), 0.2),
        "sigma_anchor": np.broadcast_to([0.6, 0.3, 0.12], (4, 10000, 3)),
    }
    values, events = conditional_scale_effects(lane, hyper, seed=17, indices=np.arange(3))
    sigma = np.interp(np.log(lane.distance_km), np.log([500, 2000, 5000]), [0.6, 0.3, 0.12])
    for k, e in enumerate(events):
        idx = np.array([i for i, v in enumerate(lane.event_ids) if v == e])
        w = 1 / sigma[idx] ** 2
        variance = 0.2**2 / (1 + 0.2**2 * w.sum())
        mean = variance * np.sum(w * (lane.response[idx] - 0.1 + 0.05 * lane.x[idx]))
        assert values[..., k].mean() == pytest.approx(mean, abs=0.002)
        assert values[..., k].var() == pytest.approx(variance, abs=0.0005)
    changed = replace(lane, response=np.array([0.2, 9999, 0.3]))
    first, _ = conditional_scale_effects(lane, hyper, seed=17, indices=np.array([0, 2]))
    second, _ = conditional_scale_effects(changed, hyper, seed=17, indices=np.array([0, 2]))
    np.testing.assert_array_equal(first, second)
    equal = {**hyper, "sigma_anchor": np.full((4, 10000, 3), 0.3)}
    profile, _ = conditional_scale_effects(lane, equal, seed=17, indices=np.arange(3))
    base, _ = conditional_event_effects(
        lane,
        {
            k: v
            for k, v in {**hyper, "sigma": np.full((4, 10000), 0.3)}.items()
            if k != "sigma_anchor"
        },
        seed=17,
        indices=np.arange(3),
    )
    np.testing.assert_allclose(profile, base, atol=1e-14)
    invalid = replace(lane, included=np.array([True, False, True]))
    with pytest.raises(ValueError, match="approved"):
        conditional_scale_effects(invalid, hyper, seed=17, indices=np.array([1]))
    prior = read_prior(Path.cwd(), lane.target, "base")
    one = build_scale_model(lane, prior, indices=np.array([0, 2]))
    two = build_scale_model(changed, prior, indices=np.array([0, 2]))
    assert one.compile_logp()(one.initial_point()) == two.compile_logp()(two.initial_point())
