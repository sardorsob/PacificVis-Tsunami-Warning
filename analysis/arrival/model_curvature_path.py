"""A numerical power path for the unchanged three-coefficient curvature model."""

# pyright: basic
from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from analysis.arrival.model_curvature import build_curvature_model, curvature_basis
from analysis.arrival.model_curvature_cv import posterior_components
from analysis.arrival.model_evaluation import gaussian_event_logpdf
from analysis.arrival.model_scale import scale_weights


def build_curvature_path(lane, prior, training, held, temperature):
    """L_train × p(r_held|alpha,beta,gamma,scales)**t, with new u integrated first.

    Coefficients remain explicit. This density is in log-ratio response coordinates;
    the native-duration Jacobian is applied once to the telescoped final score.
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
        raise ValueError("one disjoint held event and temperature in[0,1] required")
    model = build_curvature_model(lane, prior, indices=training)
    if temperature == 0:
        return model
    with model:
        sigma = pt.dot(scale_weights(lane.distance_km[held]), model["sigma_anchor"])
        precision = 1 / sigma**2
        total = cast(Any, pt.sum(precision))
        residual = (
            lane.response[held]
            - model["alpha"]
            - model["beta"] * lane.x[held]
            - model["gamma"] * curvature_basis(lane.distance_km[held])
        )
        center = cast(Any, pt.sum(precision * residual)) / total
        inflation = 1 + model["tau_event"] ** 2 * total
        quadratic = pt.sum(precision * (residual - center) ** 2) + total * center**2 / inflation
        logdet = 2 * cast(Any, pt.sum(pt.log(sigma))) + pt.log(inflation)
        marginal = -0.5 * (len(held) * math.log(2 * math.pi) + logdet + quadratic)
        pm.Potential("integration_powered_held_event_likelihood", float(temperature) * marginal)
    return model


def curvature_held_loglikelihood(lane, held, posterior):
    """Full alpha/beta/gamma draws; one shared new-event effect, no native Jacobian."""
    if (
        lane.target != "NCEI-native-duration"
        or held.ndim != 1
        or not np.issubdtype(held.dtype, np.integer)
        or not len(held)
        or len(set(held.tolist())) != len(held)
        or (held < 0).any()
        or (held >= len(lane.rows)).any()
        or not lane.included[held].all()
        or len({lane.event_ids[int(i)] for i in held}) != 1
    ):
        raise ValueError("one primary-source held event required")
    mean, sigma, tau = posterior_components(posterior, lane.distance_km[held])
    return gaussian_event_logpdf(lane.response[held], mean, sigma, tau)
