"""Analyst post-EDA prior sensitivities, preserving each source-specific model.

Population coefficients remain explicit. Only Normal event effects are integrated.
Replacement Potentials preserve existing positive-variable transforms/Jacobians;
PyMC's automatic prior predictive ignores these Potentials, so use the direct
ancestral functions below. No coefficient-collapsed Gaussian scoring kernel is
valid for the Student-t alternatives. These helpers do not establish calibration.

The installed Normal log-density can have a ~1.9e-9 normalization-constant
offset from SciPy for an exactly representable Python-float SD. Synthetic checks
bound that offset separately and require unchanged density differences/gradients.
"""

# pyright: basic
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from analysis.arrival.model_curvature import build_curvature_model, curvature_basis
from analysis.arrival.model_data import VREF_KM_MIN, Lane
from analysis.arrival.model_scale import build_scale_model, scale_weights
from analysis.arrival.models import build_model

T4_MATCHED_SCALE = 0.7059257108562306
VARIANTS = ("base", "power_0.5", "power_1.5", "joint_wider", "t4_matched", "gamma_wider_only")
PRIOR_ORIGIN = "analyst_post_EDA_sensitivity_not_expert_facts"
POSITIVE_NATIVE_MOMENTS = (
    "no_mean_or_variance_claim; finite simulated draws do not establish moment existence; "
    "Student-t scale priors can imply infinite positive-native moments, even posterior"
)


def _population_spec(target: str, kind: str) -> dict[str, tuple[str, tuple[int, ...]]]:
    """List only the population variables present in the reviewed model form."""
    forms = {
        "NCEI-native-duration": {"distance-scale", "mean-curvature"},
        "T-OBS": {"pooled", "distance", "event"},
        "T-CAL": {"pooled", "distance", "event"},
    }
    if target not in forms or kind not in forms[target]:
        raise ValueError("one of the eight reviewed source-specific forms required")
    spec: dict[str, tuple[str, tuple[int, ...]]] = {"alpha": ("alpha_sd", ())}
    if kind != "pooled":
        spec["beta"] = ("beta_sd", ())
    if kind == "mean-curvature":
        spec["gamma"] = ("gamma_sd", ())
    if kind in {"event", "distance-scale", "mean-curvature"}:
        spec["tau_event"] = ("tau_sd", ())
    if target == "NCEI-native-duration":
        spec["sigma_anchor"] = ("sigma_sd", (3,))
    else:
        spec["sigma"] = ("sigma_sd", ())
    return spec


def _validated_prior(prior: dict[str, float], kind: str) -> dict[str, float]:
    """Check the existing base-prior dictionary API, without changing its units."""
    expected = {"alpha_sd", "beta_sd", "tau_sd", "sigma_sd"}
    if kind == "mean-curvature":
        expected.add("gamma_sd")
    if set(prior) != expected or any(
        isinstance(value, (bool, np.bool_)) or not np.isfinite(value) or value <= 0
        for value in prior.values()
    ):
        raise ValueError("the model's complete finite positive prior SD dictionary required")
    return dict(prior)


def _prior_settings(
    kind: str,
    base_prior: dict[str, float],
    variant: str,
    wider_prior: dict[str, float] | None,
) -> tuple[str, dict[str, float]]:
    """Return family and distribution scales; Student-t scale is not its SD."""
    scales = _validated_prior(base_prior, kind)
    if variant not in VARIANTS:
        raise ValueError("unknown frozen prior sensitivity")
    if variant == "joint_wider":
        if wider_prior is None:
            raise ValueError("existing declared wider-prior dictionary required")
        scales = _validated_prior(wider_prior, kind)
    elif variant.startswith("power_"):
        power = float(variant.split("_")[1])
        scales = {key: value / np.sqrt(power) for key, value in scales.items()}
    elif variant == "gamma_wider_only":
        if kind != "mean-curvature":
            raise ValueError("gamma-only sensitivity requires the curvature form")
        scales["gamma_sd"] = 0.8
    elif variant == "t4_matched":
        scales = {key: value * T4_MATCHED_SCALE for key, value in scales.items()}
    return ("t4" if variant == "t4_matched" else "normal"), scales


def build_sensitivity_model(
    lane: Lane,
    kind: str,
    base_prior: dict[str, float],
    variant: str,
    *,
    wider_prior: dict[str, float] | None = None,
    indices: np.ndarray | None = None,
) -> pm.Model:
    """Replace population priors, preserving the literal likelihood/training subset.

    Normal/HalfNormal powers change SD to SD/sqrt(power). The conditional Normal
    event law is never powered. Student-t(4)/HalfStudent-t(4) scales match the
    base priors' absolute central-95% quantile; their coefficients stay explicit.
    Use direct ancestral draws instead of automatic prior predictive on this model.
    """
    spec = _population_spec(lane.target, kind)
    family, scales = _prior_settings(kind, base_prior, variant, wider_prior)
    if kind == "mean-curvature":
        model = build_curvature_model(lane, base_prior, indices=indices)
    elif kind == "distance-scale":
        model = build_scale_model(lane, base_prior, indices=indices)
    else:
        model = build_model(
            lane, base_prior, kind=kind, indices=indices, parameterization="marginal"
        )
    if {variable.name for variable in model.free_RVs} != set(spec):
        raise ValueError("reviewed explicit population-variable structure changed")
    if variant == "base":
        return model
    replacement = pt.as_tensor_variable(0.0)
    with model:
        for name, (key, _) in spec.items():
            positive = name in {"tau_event", "sigma", "sigma_anchor"}
            original = (pm.HalfNormal if positive else pm.Normal).dist(sigma=base_prior[key])
            if family == "t4":
                changed = (pm.HalfStudentT if positive else pm.StudentT).dist(
                    nu=4, sigma=scales[key]
                )
            else:
                changed = (pm.HalfNormal if positive else pm.Normal).dist(sigma=scales[key])
            variable = model[name]
            replacement = replacement + pt.sum(
                cast(Any, pm.logp(changed, variable)) - cast(Any, pm.logp(original, variable))
            )
        pm.Potential("sensitivity_population_prior_replacement", replacement)
    return model


def population_prior_draws(
    target: str,
    kind: str,
    base_prior: dict[str, float],
    variant: str,
    *,
    draws: int,
    seed: int,
    wider_prior: dict[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """Draw directly from the changed population priors, without reading any lane.

    Arrays have shape (draws,), or (draws, 3) for the three residual SD anchors.
    HalfStudent-t uses absolute Student-t draws. No tail clipping/rejection occurs.
    """
    spec = _population_spec(target, kind)
    family, scales = _prior_settings(kind, base_prior, variant, wider_prior)
    if type(draws) is not int or draws < 1 or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("positive integer draws and a uint32 seed required")
    rng = np.random.default_rng(seed)
    population = {}
    for name, (key, shape) in spec.items():
        size = (draws, *shape)
        standard = rng.standard_t(4, size=size) if family == "t4" else rng.normal(size=size)
        with np.errstate(over="ignore", invalid="ignore"):
            values = standard * scales[key]
        population[name] = (
            np.abs(values) if name in {"tau_event", "sigma", "sigma_anchor"} else values
        )
    return population


def prior_predictive_log_or_native(
    target: str,
    kind: str,
    population: dict[str, np.ndarray],
    distance_km: np.ndarray,
    *,
    seed: int,
) -> dict[str, Any]:
    """Simulate one wholly new event with shared Normal u and individual noise.

    Positive-duration lanes return response log-ratios and log-native minutes,
    never exponentials; T-CAL returns signed native minutes. Every input draw is
    retained, including nonfinite arithmetic results, and validity flags describe
    whether numerical quantiles can be computed in the returned measure. A finite
    simulation does not establish finite positive-native means or variances.
    """
    spec = _population_spec(target, kind)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("uint32 seed required")
    weights = scale_weights(distance_km)
    if set(population) != set(spec):
        raise ValueError("exact population variables for the chosen form required")
    alpha = np.asarray(population["alpha"])
    if alpha.ndim != 1 or not len(alpha):
        raise ValueError("nonempty one-dimensional population draw axis required")
    count = len(alpha)
    for name, (_, shape) in spec.items():
        values = np.asarray(population[name])
        if values.shape != (count, *shape):
            raise ValueError("aligned population draw/anchor shapes required")
        if name in {"tau_event", "sigma", "sigma_anchor"} and (values < 0).any():
            raise ValueError("nonnegative population scales required")
    rng = np.random.default_rng(seed)
    with np.errstate(over="ignore", invalid="ignore"):
        response = np.broadcast_to(alpha[:, None], (count, len(distance_km))).copy()
        if "beta" in spec:
            response += population["beta"][:, None] * np.log(distance_km / 1000)
        if "gamma" in spec:
            response += population["gamma"][:, None] * curvature_basis(distance_km)
        if "tau_event" in spec:
            response += population["tau_event"][:, None] * rng.normal(size=(count, 1))
        sigma = (
            population["sigma_anchor"] @ weights.T
            if "sigma_anchor" in spec
            else population["sigma"][:, None]
        )
        response += sigma * rng.normal(size=(count, len(distance_km)))
        output = response if target == "T-CAL" else response + np.log(distance_km / VREF_KM_MIN)
    result = {
        "response": response,
        "response_measure": "signed_minutes" if target == "T-CAL" else "log_ratio",
        "quantile_space": "native_minutes" if target == "T-CAL" else "log_native_minutes",
        "quantile_valid": bool(np.isfinite(output).all()),
        "response_valid": bool(np.isfinite(response).all()),
        "nonfinite_output_values": int(np.count_nonzero(~np.isfinite(output))),
        "prior_origin": PRIOR_ORIGIN,
    }
    if target == "T-CAL":
        result["native_minutes"] = output
    else:
        result["log_native_minutes"] = output
        result["positive_native_moments"] = POSITIVE_NATIVE_MOMENTS
    return result
