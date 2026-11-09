"""Synthetic conditional hierarchy/native-coordinate oracles; no fit or loader."""

# pyright: basic
import json
from dataclasses import replace
from typing import Any

import numpy as np
import pytest
import xarray as xr

from analysis.arrival.model_data import VREF_KM_MIN
from analysis.arrival.model_sensitivity_summary import (
    GRID_KM,
    predictive_draws,
    summarize_posterior,
)
from tests.test_arrival_model_scale import grouped_lane


def lane(target="NCEI-native-duration"):
    original = grouped_lane()
    reference = original.distance_km / VREF_KM_MIN
    response = np.array([0.2, -0.1, 0.3]) if target != "T-CAL" else np.array([-20.0, 5.0, -8.0])
    return replace(
        original,
        target=target,
        response=response,
        y=response if target == "T-CAL" else np.exp(response) * reference,
        reference_minutes=reference,
    )


def posterior(kind="mean-curvature", *, alpha=0.1, sigma=0.3, tau=0.2, draws=100):
    variables: dict[str, Any] = {"alpha": (("chain", "draw"), np.full((4, draws), alpha))}
    if kind != "pooled":
        variables["beta"] = (("chain", "draw"), np.full((4, draws), -0.05))
    if kind == "mean-curvature":
        variables["gamma"] = (("chain", "draw"), np.full((4, draws), 0.4))
    if kind in {"event", "distance-scale", "mean-curvature"}:
        variables["tau_event"] = (("chain", "draw"), np.full((4, draws), tau))
    if kind in {"mean-curvature", "distance-scale"}:
        variables["sigma_anchor"] = (
            ("chain", "draw", "scale_anchor_km"),
            np.tile([sigma, sigma * 0.7, sigma * 0.4], (4, draws, 1)),
        )
    else:
        variables["sigma"] = (("chain", "draw"), np.full((4, draws), sigma))
    return xr.Dataset(
        variables,
        coords={
            "chain": range(4),
            "draw": range(draws),
            **(
                {"scale_anchor_km": [500, 2000, 5000]}
                if kind in {"mean-curvature", "distance-scale"}
                else {}
            ),
        },
    )


@pytest.mark.parametrize("kind", ["mean-curvature", "distance-scale", "event"])
def test_conditional_u_matches_independent_dense_normal_conditioning(kind):
    target = "T-OBS" if kind == "event" else "NCEI-native-duration"
    data, post = lane(target), posterior(kind)
    result = predictive_draws(data, kind, post, indices=np.arange(3), seed=991, draws=200)
    d = data.distance_km[:2]
    sd = (
        np.interp(np.log(d), np.log([500, 2000, 5000]), [0.3, 0.21, 0.12])
        if kind != "event"
        else np.full(2, 0.3)
    )
    mean = 0.1 - 0.05 * np.log(d / 1000)
    if kind == "mean-curvature":
        mean += 0.4 * np.log((d + 500) / (1.5 * d))
    covariance = np.diag(sd**2) + 0.04 * np.ones((2, 2))
    conditional_mean = 0.04 * np.ones(2) @ np.linalg.solve(covariance, data.response[:2] - mean)
    conditional_variance = 0.04 - 0.04**2 * np.ones(2) @ np.linalg.solve(covariance, np.ones(2))
    noise = np.random.default_rng(result["stream_seeds"][1]).normal(size=(4, 100, 2))
    expected = conditional_mean + np.sqrt(conditional_variance) * noise[..., 0]
    np.testing.assert_allclose(
        result["conditional_effects"][:, 0],
        expected.reshape(-1)[result["posterior_flat_indices"]],
        atol=1e-14,
    )


def test_fitted_event_effect_shared_but_record_noise_independent_and_new_u_shared_along_grid():
    data, post = lane(), posterior()
    out = predictive_draws(data, "mean-curvature", post, indices=np.arange(3), seed=14, draws=400)
    population = out["population"]
    d = data.distance_km
    mean = 0.1 - 0.05 * np.log(d / 1000) + 0.4 * np.log((d + 500) / (1.5 * d))
    sd = np.interp(np.log(d), np.log([500, 2000, 5000]), [0.3, 0.21, 0.12])
    noise = np.random.default_rng(out["stream_seeds"][2]).normal(size=(400, 3))
    residual = out["conditional_response"] - mean - sd * noise
    np.testing.assert_allclose(residual[:, 0], out["conditional_effects"][:, 0], atol=1e-15)
    np.testing.assert_allclose(residual[:, 1], out["conditional_effects"][:, 0], atol=1e-15)
    assert not np.array_equal(noise[:, 0], noise[:, 1])
    rng = np.random.default_rng(out["stream_seeds"][3])
    new_u = population["tau_event"][:, None] * rng.normal(size=(400, 1))
    new_noise = rng.normal(size=(400, len(GRID_KM)))
    grid_mean = (
        0.1 - 0.05 * np.log(GRID_KM / 1000) + 0.4 * np.log((GRID_KM + 500) / (1.5 * GRID_KM))
    )
    grid_sd = np.interp(np.log(GRID_KM), np.log([500, 2000, 5000]), [0.3, 0.21, 0.12])
    np.testing.assert_allclose(
        out["new_event_response"], grid_mean + new_u + grid_sd * new_noise, atol=1e-15
    )


@pytest.mark.parametrize(
    "target,kind",
    [
        ("NCEI-native-duration", "mean-curvature"),
        ("NCEI-native-duration", "distance-scale"),
        *[
            (target, kind)
            for target in ["T-OBS", "T-CAL"]
            for kind in ["pooled", "distance", "event"]
        ],
    ],
)
def test_all_eight_forms_export_native_quantiles_membership_support_and_no_moments(target, kind):
    result = summarize_posterior(
        lane(target), kind, posterior(kind), indices=np.array([0, 1]), seed=45, draws=200
    )
    assert result["membership"] == list(lane(target).record_ids[:2])
    assert len(result["curves"]) == 18 and len(result["record_intervals"]) == 2
    assert len(result["posterior_flat_indices"]) == 200
    assert not result["native_predictive_means_or_variances_reported"]
    assert result["curves"][0]["support"] == "below"
    assert result["curves"][-1]["support"] == "above"
    assert all(v == 0 for v in result["nonfinite_values"].values())
    assert {row["scale"] for row in result["conditional_ppc"]} == {
        "native-minutes",
        "modeled-response",
    }
    middle = next(
        row
        for row in result["curves"]
        if row["curve"] == "population_median" and row["distance_km"] == 1000
    )
    expected = 0.1 if target == "T-CAL" else np.exp(0.1) * 1000 / VREF_KM_MIN
    assert middle["q50"] == pytest.approx(expected)
    if target == "T-CAL":
        assert result["record_intervals"][0]["observed_native_minutes"] < 0
    else:
        assert (
            "finite simulated draws do not establish moment existence"
            in result["positive_native_moments"]
        )
    json.dumps(result, allow_nan=False)


def test_positive_overflow_keeps_log_quantiles_and_every_replicate_without_clipping():
    result = summarize_posterior(
        lane("T-OBS"),
        "pooled",
        posterior("pooled", alpha=1000),
        indices=np.arange(3),
        seed=4,
        draws=400,
    )
    assert all(row["q50"] is None and row["log_q50"] > 900 for row in result["curves"])
    assert all(
        row["quantile_valid"] and not row["native_representable"] for row in result["curves"]
    )
    assert result["unrepresentable_native_draws"]["conditional_measure"] == 400 * 3
    for row in result["conditional_ppc"]:
        if row["scale"] == "native-minutes":
            assert row["replicated_q50"] is None
            assert row["replicated_log_q50"] > 900
            assert not row["replicated_native_representable"]
    json.dumps(result, allow_nan=False)


def test_explicit_non_gaussian_population_draws_are_preserved_without_coefficient_collapse():
    post = posterior(draws=300)
    post["gamma"].values[:] = np.random.default_rng(45).standard_t(4, size=(4, 300)) * 0.4
    post["alpha"].values[:] = np.random.default_rng(46).standard_t(4, size=(4, 300)) * 0.5
    result = summarize_posterior(lane(), "mean-curvature", post, indices=np.arange(3), seed=11)
    row = next(row for row in result["parameters"] if row["parameter"] == "gamma")
    np.testing.assert_allclose(
        [row["q05"], row["q50"], row["q95"]], np.quantile(post.gamma.values, [0.05, 0.5, 0.95])
    )
    assert result["conditional_predictive_draws"] == 800


def test_nonfinite_modeled_arithmetic_invalidates_quantiles_without_dropping_draws():
    post = posterior("distance")
    post["beta"].values[:] = 1e308
    result = summarize_posterior(
        lane("T-OBS"), "distance", post, indices=np.arange(3), seed=6, draws=400
    )
    first = next(
        row for row in result["curves"] if row["curve"] == "new_event" and row["distance_km"] == 20
    )
    assert first["nonfinite_values"] == 400
    assert not first["quantile_valid"] and first["q50"] is None and first["log_q50"] is None
    assert result["nonfinite_values"]["new_event_response"] > 0
    assert len(result["posterior_flat_indices"]) == 400
    json.dumps(result, allow_nan=False)


def test_finite_mixed_sign_extremes_have_stable_parameter_curve_record_and_ppc_quantiles():
    data = lane("T-CAL")
    data = replace(
        data, y=np.array([-1e308, 1e308, -1e308]), response=np.array([-1e308, 1e308, -1e308])
    )
    post = posterior("pooled")
    post["alpha"].values[:, :50] = -1e308
    post["alpha"].values[:, 50:] = 1e308
    result = summarize_posterior(data, "pooled", post, indices=np.array([0, 1]), seed=90, draws=400)
    alpha = next(row for row in result["parameters"] if row["parameter"] == "alpha")
    assert [alpha["q05"], alpha["q50"], alpha["q95"]] == [-1e308, 0.0, 1e308]
    for row in [*result["curves"], *result["record_intervals"]]:
        assert [row["q05"], row["q50"], row["q95"]] == [-1e308, 0.0, 1e308]
        assert row["quantile_valid"] and row["native_representable"]
        assert row["nonfinite_values"] == row["nonfinite_quantile_values"] == 0
    for row in result["conditional_ppc"]:
        assert row["replicated_q50"] == 0.0
        assert row["replicated_quantile_valid"] and row["observed_quantile_valid"]
        if row["stratum"] == "all" and row["quantile"] == 0.5:
            assert row["observed"] == 0.0
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "change",
    [
        "chain",
        "nan",
        "anchor",
        "scale",
        "indices",
        "ids",
        "target",
        "draws",
        "dimensions",
        "missing_parameter",
        "duplicate_draw",
        "negative_tau",
    ],
)
def test_invalid_inputs_fail_before_any_summary(change):
    data, post, indices, count = lane(), posterior(), np.arange(3), 200
    if change == "chain":
        post = post.isel(chain=slice(3))
    elif change == "nan":
        post["alpha"].values[0, 0] = np.nan
    elif change == "anchor":
        post = post.assign_coords(scale_anchor_km=[5000, 2000, 500])
    elif change == "scale":
        post["sigma_anchor"].values[:] = 0
    elif change == "indices":
        indices = np.array([0, 0])
    elif change == "ids":
        data = replace(data, record_ids=("same", "same", "third"))
    elif change == "target":
        data = replace(data, target="T-CAL")
    elif change == "draws":
        count = 401
    elif change == "dimensions":
        post["gamma"] = post["gamma"].transpose("draw", "chain")
    elif change == "missing_parameter":
        post = post.drop_vars("gamma")
    elif change == "duplicate_draw":
        post = post.assign_coords(draw=[0] * 100)
    else:
        post["tau_event"].values[:] = -0.1
    with pytest.raises(ValueError):
        summarize_posterior(data, "mean-curvature", post, indices=indices, seed=1, draws=count)
