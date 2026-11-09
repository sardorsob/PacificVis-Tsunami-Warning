"""Synthetic prior replacements and ancestral checks, without MCMC or source outcomes."""

# pyright: basic
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pytest
from scipy.stats import halfnorm, multivariate_normal, norm, t

from analysis.arrival import model_sensitivity_priors as sensitivity
from tests.test_arrival_model_scale import grouped_lane

BASE = {"alpha_sd": 0.5, "beta_sd": 0.25, "tau_sd": 0.4, "sigma_sd": 0.4}
CURVED = {**BASE, "gamma_sd": 0.5}
FORMS = [("NCEI-native-duration", kind) for kind in ["distance-scale", "mean-curvature"]] + [
    (target, kind) for target in ["T-OBS", "T-CAL"] for kind in ["pooled", "distance", "event"]
]


def toy(target):
    return replace(grouped_lane(), target=target)


@pytest.mark.parametrize("target,kind", FORMS)
def test_baseline_nesting_and_actual_population_names(target, kind):
    prior = CURVED if kind == "mean-curvature" else BASE
    model = sensitivity.build_sensitivity_model(toy(target), kind, prior, "base")
    expected = {"alpha", "sigma_anchor" if target == "NCEI-native-duration" else "sigma"}
    if kind != "pooled":
        expected.add("beta")
    if kind in {"event", "distance-scale", "mean-curvature"}:
        expected.add("tau_event")
    if kind == "mean-curvature":
        expected.add("gamma")
    assert {rv.name for rv in model.free_RVs} == expected
    assert not any("replacement" in str(term.name) for term in model.potentials)
    assert "z_event" not in model.named_vars
    draws = sensitivity.population_prior_draws(target, kind, prior, "base", draws=20, seed=8)
    assert set(draws) == expected
    assert all(
        value.shape == ((20, 3) if name == "sigma_anchor" else (20,))
        for name, value in draws.items()
    )


def test_t4_absolute95_match_is_analytic_not_a_sample_moment_claim():
    factor = sensitivity.T4_MATCHED_SCALE
    assert factor == pytest.approx(norm.ppf(0.975) / t.ppf(0.975, 4), abs=2e-15)
    assert t.ppf(0.975, 4) * factor == pytest.approx(halfnorm.ppf(0.95), abs=1e-14)


def point(vector):
    return {
        "alpha": vector[0],
        "beta": vector[1],
        "gamma": vector[2],
        "tau_event_log__": vector[3],
        "sigma_anchor_log__": vector[4:],
    }


def independent_prior(vector, *, family, scales):
    coeff = np.array(vector[:3])
    positive = np.exp(vector[3:])
    coeff_sd = np.array([scales[k] for k in ["alpha_sd", "beta_sd", "gamma_sd"]])
    positive_sd = np.array([scales["tau_sd"], *[scales["sigma_sd"]] * 3])
    if family == "t4":
        density = t.logpdf(coeff / coeff_sd, 4) - np.log(coeff_sd)
        half = t.logpdf(positive / positive_sd, 4) - np.log(positive_sd) + np.log(2)
    else:
        density = norm.logpdf(coeff, scale=coeff_sd)
        half = halfnorm.logpdf(positive, scale=positive_sd)
    return density.sum() + half.sum() + vector[3:].sum()


@pytest.mark.parametrize(
    "variant", ["power_0.5", "power_1.5", "joint_wider", "gamma_wider_only", "t4_matched"]
)
def test_prior_replacement_dense_density_and_all7_gradients(variant):
    lane = toy("NCEI-native-duration")
    wider = {key: value * 1.7 for key, value in CURVED.items()}
    base = sensitivity.build_sensitivity_model(lane, "mean-curvature", CURVED, "base")
    model = sensitivity.build_sensitivity_model(
        lane, "mean-curvature", CURVED, variant, wider_prior=wider
    )
    assert {rv.name for rv in model.free_RVs} == {
        "alpha",
        "beta",
        "gamma",
        "tau_event",
        "sigma_anchor",
    }
    base_logp, changed_logp = base.compile_logp(), model.compile_logp()
    base_grad, changed_grad = base.compile_dlogp(), model.compile_dlogp()
    vector = np.array([0.1, -0.05, 0.4, *np.log([0.2, 0.6, 0.3, 0.12])])
    scales = dict(CURVED)
    family = "normal"
    if variant.startswith("power_"):
        scales = {
            key: value / np.sqrt(float(variant.split("_")[1])) for key, value in scales.items()
        }
    elif variant == "joint_wider":
        scales = wider
    elif variant == "gamma_wider_only":
        scales["gamma_sd"] = 0.8
    else:
        family = "t4"
        scales = {key: value * sensitivity.T4_MATCHED_SCALE for key, value in scales.items()}

    def prior_delta(value):
        return independent_prior(value, family=family, scales=scales) - independent_prior(
            value, family="normal", scales=CURVED
        )

    # The installed Normal constant differs at ~1.9e-9/coordinate. Bound it
    # separately; parameter-dependent density/gradient errors retain tight gates.
    vectors = [vector, vector + 0.123, np.array([-0.3, 0.12, 0.7, *np.log([0.7, 0.2, 0.1, 0.4])])]
    actual, expected = [], []
    for vector in vectors:
        actual.append(changed_logp(point(vector)) - base_logp(point(vector)))
        expected.append(prior_delta(vector))
        eps = 1e-6
        finite_gradient = np.array(
            [
                (
                    prior_delta(vector + np.eye(7)[j] * eps)
                    - prior_delta(vector - np.eye(7)[j] * eps)
                )
                / (2 * eps)
                for j in range(7)
            ]
        )
        np.testing.assert_allclose(
            changed_grad(point(vector)) - base_grad(point(vector)),
            finite_gradient,
            rtol=0,
            atol=1e-7,
        )
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-8)
    np.testing.assert_allclose(
        np.array(actual) - actual[0], np.array(expected) - expected[0], rtol=0, atol=1e-10
    )


def test_installed_normal_normalization_constant_is_explicitly_bounded():
    value = np.float64(0.1)
    actual = sensitivity.pm.logp(sensitivity.pm.Normal.dist(sigma=0.5), value).eval()
    assert actual - norm.logpdf(value, scale=0.5) == pytest.approx(1.904654323148236e-9, abs=1e-13)


@pytest.mark.parametrize("power", [0.5, 1.5])
def test_power_scales_only_population_density_up_to_constant(power):
    scales = {key: value / np.sqrt(power) for key, value in CURVED.items()}
    constants = []
    for vector in [
        np.array([0.1, -0.05, 0.4, *np.log([0.2, 0.6, 0.3, 0.12])]),
        np.array([-0.3, 0.12, 0.7, *np.log([0.7, 0.2, 0.1, 0.4])]),
    ]:
        # Jacobian belongs to the sampling coordinates, never to the powered prior.
        jac = vector[3:].sum()
        original = independent_prior(vector, family="normal", scales=CURVED) - jac
        powered = independent_prior(vector, family="normal", scales=scales) - jac
        constants.append(powered - power * original)
    assert constants[0] == pytest.approx(constants[1], abs=1e-12)


def test_ancestral_draws_use_correct_t_population_without_prior_predictive(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Potential is ignored by automatic prior predictive")

    monkeypatch.setattr(sensitivity.pm, "sample_prior_predictive", forbidden)
    seed, count = 918, 40
    actual = sensitivity.population_prior_draws(
        "NCEI-native-duration", "mean-curvature", CURVED, "t4_matched", draws=count, seed=seed
    )
    rng = np.random.default_rng(seed)
    for name, prior_key in [
        ("alpha", "alpha_sd"),
        ("beta", "beta_sd"),
        ("gamma", "gamma_sd"),
        ("tau_event", "tau_sd"),
        ("sigma_anchor", "sigma_sd"),
    ]:
        size = (count, 3) if name == "sigma_anchor" else (count,)
        expected = rng.standard_t(4, size=size) * CURVED[prior_key] * sensitivity.T4_MATCHED_SCALE
        if name in {"tau_event", "sigma_anchor"}:
            expected = np.abs(expected)
        np.testing.assert_allclose(actual[name], expected, rtol=1e-15, atol=0)


def test_new_event_effect_is_shared_and_record_noise_is_individual():
    population = {
        "alpha": np.zeros(4),
        "beta": np.zeros(4),
        "tau_event": np.full(4, 0.7),
        "sigma_anchor": np.full((4, 3), 0.1),
    }
    distance = np.array([500.0, 5000.0, 2000.0])
    actual = sensitivity.prior_predictive_log_or_native(
        "NCEI-native-duration", "distance-scale", population, distance, seed=18
    )
    rng = np.random.default_rng(18)
    expected = 0.7 * rng.normal(size=(4, 1)) + 0.1 * rng.normal(size=(4, 3))
    np.testing.assert_allclose(actual["response"], expected, rtol=0, atol=1e-15)
    assert actual["quantile_valid"] is True and actual["response_measure"] == "log_ratio"
    assert "native_minutes" not in actual


def test_log_native_avoids_exponential_overflow_and_keeps_every_draw():
    population = {"alpha": np.array([1000.0, -1000.0]), "sigma": np.ones(2)}
    actual = sensitivity.prior_predictive_log_or_native(
        "T-OBS", "pooled", population, np.array([1000.0]), seed=1
    )
    assert actual["log_native_minutes"].shape == (2, 1)
    assert np.isfinite(actual["log_native_minutes"]).all() and actual["quantile_valid"] is True
    assert "no_mean_or_variance_claim" in actual["positive_native_moments"]


def test_signed_native_generator_and_units_differ_from_duration():
    population = {"alpha": np.array([-30.0, 20.0]), "sigma": np.ones(2)}
    result = sensitivity.prior_predictive_log_or_native(
        "T-CAL", "pooled", population, np.array([1000.0]), seed=1
    )
    assert "log_native_minutes" not in result
    np.testing.assert_array_equal(result["response"], result["native_minutes"])
    assert result["native_minutes"][0, 0] < 0 and result["response_measure"] == "signed_minutes"


def test_gamma_only_leaves_other_population_draws_identical_and_inputs_unmutated():
    original = dict(CURVED)
    base = sensitivity.population_prior_draws(
        "NCEI-native-duration", "mean-curvature", CURVED, "base", draws=20, seed=88
    )
    changed = sensitivity.population_prior_draws(
        "NCEI-native-duration", "mean-curvature", CURVED, "gamma_wider_only", draws=20, seed=88
    )
    for key in set(base) - {"gamma"}:
        np.testing.assert_array_equal(base[key], changed[key])
    np.testing.assert_allclose(changed["gamma"], base["gamma"] * 0.8 / 0.5)
    assert CURVED == original


@pytest.mark.parametrize(
    "target,kind,variant",
    [
        ("T-CAL", "mean-curvature", "base"),
        ("T-OBS", "distance-scale", "base"),
        ("NCEI-native-duration", "event", "base"),
        ("T-OBS", "event", "gamma_wider_only"),
        ("T-OBS", "event", "joint_wider"),
        ("T-OBS", "event", "invented"),
    ],
)
def test_unreviewed_form_or_variant_is_refused(target, kind, variant):
    with pytest.raises(ValueError):
        sensitivity.build_sensitivity_model(toy(target), kind, BASE, variant)


@pytest.mark.parametrize("variant", ["base", "power_0.5", "t4_matched"])
def test_normal_event_conditional_integral_is_unchanged_by_population_priors(variant):
    lane = toy("T-OBS")
    model = sensitivity.build_sensitivity_model(lane, "event", BASE, variant)
    evaluate = model.compile_logp(vars=[model["event_marginal_likelihood"]])
    values = {
        "alpha": 0.1,
        "beta": -0.05,
        "tau_event_log__": np.log(0.2),
        "sigma_log__": np.log(0.3),
    }
    expected = 0.0
    for event in set(lane.event_ids):
        indices = np.array([i for i, name in enumerate(lane.event_ids) if name == event])
        expected += cast(Any, multivariate_normal).logpdf(
            lane.response[indices],
            mean=0.1 - 0.05 * lane.x[indices],
            cov=0.3**2 * np.eye(len(indices)) + 0.2**2 * np.ones((len(indices), len(indices))),
        )
    assert evaluate(values) == pytest.approx(expected, abs=1e-12)


def test_ancestral_overflow_is_retained_and_quantile_validity_is_false():
    population = {"alpha": np.array([0.0, np.inf]), "sigma": np.ones(2)}
    result = sensitivity.prior_predictive_log_or_native(
        "T-OBS", "pooled", population, np.array([1000.0, 2000.0]), seed=1
    )
    assert result["log_native_minutes"].shape == (2, 2)
    assert result["nonfinite_output_values"] == 2 and result["quantile_valid"] is False
    assert np.isinf(result["log_native_minutes"][1]).all()


@pytest.mark.parametrize("target,kind", FORMS)
def test_t4_replaces_only_actual_population_priors_for_every_form(target, kind):
    prior = CURVED if kind == "mean-curvature" else BASE
    model = sensitivity.build_sensitivity_model(toy(target), kind, prior, "t4_matched")
    names = {str(potential.name) for potential in model.potentials}
    assert "sensitivity_population_prior_replacement" in names
    assert "alpha" in model.named_vars and ("beta" in model.named_vars) == (kind != "pooled")
    assert "z_event" not in model.named_vars


@pytest.mark.parametrize(
    "variant,multiplier",
    [("power_0.5", 1 / np.sqrt(0.5)), ("power_1.5", 1 / np.sqrt(1.5)), ("joint_wider", 1.7)],
)
def test_direct_ancestral_normal_scales_match_each_population_variant(variant, multiplier):
    base = sensitivity.population_prior_draws(
        "NCEI-native-duration", "mean-curvature", CURVED, "base", draws=30, seed=98
    )
    changed = sensitivity.population_prior_draws(
        "NCEI-native-duration",
        "mean-curvature",
        CURVED,
        variant,
        draws=30,
        seed=98,
        wider_prior={key: value * 1.7 for key, value in CURVED.items()},
    )
    for key in base:
        np.testing.assert_allclose(changed[key], base[key] * multiplier, rtol=1e-15, atol=0)
