"""The numerical power path must retain gamma and the unchanged model at its ends."""

# pyright: basic
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import xarray as xr
from scipy.stats import halfnorm, multivariate_normal, norm

from analysis.arrival.model_curvature import build_curvature_model
from analysis.arrival.model_curvature_path import build_curvature_path, curvature_held_loglikelihood
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_scale import scale_weights
from tests.test_arrival_model_scale import grouped_lane


def test_fractional_path_density_and_seven_gradients_match_independent_dense_gaussian():
    lane = grouped_lane()
    prior = read_curvature_prior(Path.cwd(), "base")
    train, held = np.array([0, 1]), np.array([2])
    point = {
        "alpha": np.array(0.1),
        "beta": np.array(-0.05),
        "gamma": np.array(0.4),
        "tau_event_log__": np.log(0.2),
        "sigma_anchor_log__": np.log([0.6, 0.3, 0.12]),
    }

    def dense(p, temperature):
        a, b, g = [float(p[k]) for k in ["alpha", "beta", "gamma"]]
        tau, sd = (
            float(np.exp(p["tau_event_log__"])),
            scale_weights(lane.distance_km) @ np.exp(p["sigma_anchor_log__"]),
        )
        total = sum(
            norm.logpdf(v, scale=prior[k + "_sd"])
            for k, v in [("alpha", a), ("beta", b), ("gamma", g)]
        )
        total += (
            halfnorm.logpdf(tau, scale=prior["tau_sd"])
            + halfnorm.logpdf(np.exp(p["sigma_anchor_log__"]), scale=prior["sigma_sd"]).sum()
        )
        total += float(p["tau_event_log__"]) + p["sigma_anchor_log__"].sum()
        for ids, power in [(train, 1.0), (held, temperature)]:
            mu = (
                a
                + b * np.log(lane.distance_km[ids] / 1000)
                + g * np.log((lane.distance_km[ids] + 500) / (1.5 * lane.distance_km[ids]))
            )
            total += power * cast(Any, multivariate_normal).logpdf(
                lane.response[ids],
                mu,
                np.diag(sd[ids] ** 2) + tau**2 * np.ones((len(ids), len(ids))),
            )
        return total

    for temperature in [0.0, 0.125, 0.5, 1.0]:
        model = build_curvature_path(lane, prior, train, held, temperature)
        assert model.compile_logp()(point) == pytest.approx(dense(point, temperature), abs=1e-8)
        if temperature in [0.0, 1.0]:
            base = build_curvature_model(
                lane, prior, indices=train if temperature == 0 else np.arange(3)
            )
            assert model.compile_logp()(point) == pytest.approx(
                base.compile_logp()(point), abs=1e-10
            )
        if temperature == 0.5:
            gradient = []
            for key in point:
                for j in range(3 if key == "sigma_anchor_log__" else 1):
                    plus, minus = [
                        {k: np.array(v).copy() for k, v in point.items()} for _ in range(2)
                    ]
                    if key == "sigma_anchor_log__":
                        plus[key][j] += 1e-5
                        minus[key][j] -= 1e-5
                    else:
                        plus[key] += 1e-5
                        minus[key] -= 1e-5
                    gradient.append((dense(plus, 0.5) - dense(minus, 0.5)) / 2e-5)
            np.testing.assert_allclose(model.compile_dlogp()(point), gradient, atol=2e-6)
    altered = replace(lane, response=lane.response + np.array([0, 0, 999.0]))
    assert build_curvature_path(altered, prior, train, held, 0).compile_logp()(
        point
    ) == build_curvature_path(lane, prior, train, held, 0).compile_logp()(point)
    with pytest.raises(ValueError):
        build_curvature_path(lane, prior, np.array([0]), np.array([1]), 0.5)


def test_path_held_density_keeps_full_joint_coefficients_and_one_shared_event():
    lane, held = grouped_lane(), np.array([0, 1])
    post = xr.Dataset(
        {
            k: (("chain", "draw"), np.full((4, 1000), v))
            for k, v in [("alpha", 0.1), ("beta", -0.05), ("gamma", 0.4), ("tau_event", 0.2)]
        }
    )
    post["sigma_anchor"] = xr.DataArray(
        np.tile([0.6, 0.3, 0.12], (4, 1000, 1)),
        dims=("chain", "draw", "scale_anchor_km"),
        coords={"scale_anchor_km": [500, 2000, 5000]},
    )
    distance = lane.distance_km[held]
    mu = 0.1 - 0.05 * np.log(distance / 1000) + 0.4 * np.log((distance + 500) / (1.5 * distance))
    sd = scale_weights(distance) @ [0.6, 0.3, 0.12]
    expected = cast(Any, multivariate_normal).logpdf(
        lane.response[held], mu, np.diag(sd**2) + 0.04 * np.ones((2, 2))
    )
    first = curvature_held_loglikelihood(lane, held, post)
    np.testing.assert_allclose(first, expected, atol=1e-12)
    post["gamma"] += 0.5
    assert not np.allclose(curvature_held_loglikelihood(lane, held, post), first)


@pytest.mark.parametrize(
    "held",
    [np.array([0, 0]), np.array([-1]), np.array([3]), np.array([0.5]), np.array([], dtype=int)],
)
def test_invalid_held_indices_cannot_change_the_integration_measure(held):
    with pytest.raises(ValueError, match="one primary-source"):
        curvature_held_loglikelihood(grouped_lane(), held, None)
