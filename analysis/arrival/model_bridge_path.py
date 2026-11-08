"""Fixed geometric bridge path in full coefficient and variance coordinates."""

# pyright: basic
from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from analysis.arrival.model_bridge import _mixing, bridge_score
from analysis.arrival.model_evaluation import gaussian_event_logpdf
from analysis.arrival.model_prediction import posterior_components
from analysis.arrival.model_scale import build_scale_model, scale_weights
from analysis.arrival.model_scoring import mean_mcse


def build_path_model(lane, prior, training, held, temperature):
    """L_train × L_held**t; integrate the new event effect before taking the power.

    Priors occur once. Coefficients remain explicit throughout this path. At t=0,
    the likelihood graph is literally training-only, with no held-response node.
    """
    if (
        not math.isfinite(temperature)
        or not 0 <= temperature <= 1
        or held.ndim != 1
        or not np.issubdtype(held.dtype, np.integer)
        or not len(held)
        or len(set(held.tolist())) != len(held)
        or (held < 0).any()
        or (held >= len(lane.rows)).any()
        or not lane.included[held].all()
        or not np.isfinite(lane.response[held]).all()
        or len({lane.event_ids[int(i)] for i in held}) != 1
        or set(lane.event_ids[int(i)] for i in training) & {lane.event_ids[int(i)] for i in held}
    ):
        raise ValueError("one disjoint held event and temperature in [0,1] required")
    model = build_scale_model(lane, prior, indices=training)
    if temperature == 0:
        return model
    with model:
        sigma = pt.dot(scale_weights(lane.distance_km[held]), model["sigma_anchor"])
        precision = 1 / sigma**2
        total = cast(Any, pt.sum(precision))
        residual = lane.response[held] - model["alpha"] - model["beta"] * lane.x[held]
        center = cast(Any, pt.sum(precision * residual)) / total
        inflation = 1 + model["tau_event"] ** 2 * total
        quadratic = pt.sum(precision * (residual - center) ** 2) + total * center**2 / inflation
        logdet = 2 * cast(Any, pt.sum(pt.log(sigma))) + pt.log(inflation)
        marginal = -0.5 * (len(held) * math.log(2 * math.pi) + logdet + quadratic)
        pm.Potential("integration_powered_held_event_likelihood", float(temperature) * marginal)
    return model


def path_held_loglikelihood(lane, held, posterior):
    """Model-response joint density given α, β and scales, with only new u integrated.

    This is different from the coefficient-collapsed conditional used by the
    original endpoint bridge. Mixing these two measures invalidates the path.
    """
    if lane.target != "NCEI-native-duration" or len({lane.event_ids[int(i)] for i in held}) != 1:
        raise ValueError("one primary-source held event required")
    mean, sigma, tau = posterior_components(posterior, "distance-scale", lane.distance_km[held])
    return gaussian_event_logpdf(lane.response[held], mean, sigma, tau)


def path_score(loglikelihoods, temperatures, *, records, jacobian=0.0):
    """Sum exact adjacent normalizer ratios; retain shared-stage Monte Carlo covariance."""
    times = np.asarray(temperatures)
    if (
        times.ndim != 1
        or len(times) != len(loglikelihoods)
        or len(times) < 2
        or not np.isfinite(times).all()
        or times[0] != 0
        or times[-1] != 1
        or (np.diff(times) <= 0).any()
        or not math.isfinite(jacobian)
    ):
        raise ValueError("complete increasing temperature path and finite Jacobian required")
    combined = [np.zeros_like(a) for a in loglikelihoods]
    edges = []
    for j, delta in enumerate(np.diff(times)):
        edge, first, second = bridge_score(
            delta * loglikelihoods[j], delta * loglikelihoods[j + 1], records=records
        )
        edges.append(
            {"from_temperature": float(times[j]), "to_temperature": float(times[j + 1]), **edge}
        )
        combined[j] += first
        combined[j + 1] += second
    variances = [mean_mcse(a) ** 2 for a in combined]
    error = math.sqrt(sum(variances))
    diagnostics = [_mixing(a) for a in combined]
    joint = sum(e["joint_log_predictive"] for e in edges) - jacobian
    return {
        "joint_log_predictive": joint,
        "normalized_event_score": joint / records,
        "joint_log_mcse_delta": error,
        "normalized_mcse": error / records,
        "edges": edges,
        "stage_functional_mixing": diagnostics,
        "stage_raw_mcse": [math.sqrt(v) for v in variances],
        "precision_passed": bool(
            all(e["precision_passed"] for e in edges)
            and all(d["passed"] for d in diagnostics)
            and error / records <= 0.005
        ),
        "native_jacobian_subtracted_once": jacobian,
        "method": "fixed_geometric_full_coefficient_coordinate_path",
        "mcse_scope": "shared_middle_stage_influences_summed_before_independent_stage_variances",
        "finite_ladder_discretization_error": "not_applicable_normalizer_ratios_telescope_exactly",
    }, combined
