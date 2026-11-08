"""One fixed smooth mean basis with existing positive distance-dependent spread."""

# pyright: basic
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pymc as pm
import pytensor.tensor as pt
from pytensor.tensor.extra_ops import bincount

from analysis.arrival.model_data import VREF_KM_MIN, Lane
from analysis.arrival.model_scale import (
    ANCHORS_KM,
    _selected,
    scale_weights,
    simulate_scale_response,
)


def curvature_basis(distance_km: np.ndarray) -> np.ndarray:
    """Fixed 500-km smooth transition, centered at 1,000 km; no query centering."""
    scale_weights(distance_km)  # shared finite-positive vector boundary
    return np.logaddexp(0, np.log(500) - np.log(distance_km)) - np.logaddexp(
        0, np.log(500) - np.log(1000)
    )


def build_curvature_model(
    lane: Lane, prior: dict[str, float], *, indices: np.ndarray | None = None
) -> pm.Model:
    """Integrate Normal event effects exactly; gamma=0 nests the scale candidate."""
    selected = _selected(lane, indices)
    if not np.isfinite(prior["gamma_sd"]) or prior["gamma_sd"] <= 0:
        raise ValueError("positive finite curvature prior SD required")
    events = sorted({lane.event_ids[int(i)] for i in selected})
    lookup = {event: i for i, event in enumerate(events)}
    event_index = np.array([lookup[lane.event_ids[int(i)]] for i in selected])
    weights = scale_weights(lane.distance_km[selected])
    basis = curvature_basis(lane.distance_km[selected])
    coords = {
        "event": events,
        "record": [lane.record_ids[int(i)] for i in selected],
        "scale_anchor_km": list(ANCHORS_KM),
    }
    with pm.Model(coords=coords) as model:
        alpha = pm.Normal("alpha", 0, prior["alpha_sd"])
        beta = pm.Normal("beta", 0, prior["beta_sd"])
        gamma = pm.Normal("gamma", 0, prior["gamma_sd"])
        tau = pm.HalfNormal("tau_event", prior["tau_sd"])
        anchors = pm.HalfNormal("sigma_anchor", prior["sigma_sd"], dims="scale_anchor_km")
        sigma = pt.dot(weights, anchors)
        precision = 1 / sigma**2
        residual = lane.response[selected] - alpha - beta * lane.x[selected] - gamma * basis
        total = bincount(event_index, weights=precision, minlength=len(events))
        weighted = bincount(event_index, weights=precision * residual, minlength=len(events))
        center = cast(Any, weighted) / total
        inflation = 1 + tau**2 * total
        within = pt.sum(precision * (residual - center[event_index]) ** 2)
        between = pt.sum(total * center**2 / inflation)
        logdet = 2 * cast(Any, pt.sum(pt.log(sigma))) + pt.sum(pt.log(inflation))
        pm.Potential(
            "event_marginal_likelihood",
            -0.5 * (len(selected) * np.log(2 * np.pi) + logdet + within + between),
        )
    return model


def simulate_curvature_response(
    lane: Lane, truth: dict[str, Any], *, seed: int
) -> tuple[np.ndarray, dict[str, float]]:
    """Independent algebraic basis in simulator; no actual response is consumed."""
    if not np.isfinite(truth["gamma"]):
        raise ValueError("finite generating curvature required")
    response, effects = simulate_scale_response(lane, truth, seed=seed)
    response += truth["gamma"] * np.log((lane.distance_km + 500) / (1.5 * lane.distance_km))
    if not np.isfinite(response).all():
        raise ValueError("unrepresentable synthetic curved response")
    return response, effects


def _validate_hyper(hyper: dict[str, np.ndarray], ndim: int) -> tuple[int, ...]:
    if set(hyper) != {"alpha", "beta", "gamma", "tau_event", "sigma_anchor"}:
        raise ValueError("seven scalar hyperparameters in five named arrays required")
    shape = hyper["alpha"].shape
    if (
        len(shape) != ndim
        or any(hyper[k].shape != shape for k in ["beta", "gamma", "tau_event"])
        or hyper["sigma_anchor"].shape != (*shape, 3)
        or any(not np.isfinite(value).all() for value in hyper.values())
        or (hyper["tau_event"] < 0).any()
        or (hyper["sigma_anchor"] <= 0).any()
    ):
        raise ValueError("aligned finite population draws and positive record scales required")
    return shape


def new_curvature_event_predictions(
    hyper: dict[str, np.ndarray], distance: np.ndarray, *, seed: int
) -> np.ndarray:
    """Native predictions share one new event effect across query records."""
    shape = _validate_hyper(hyper, 1)
    weights = scale_weights(distance)
    basis = curvature_basis(distance)
    rng = np.random.default_rng(seed)
    response = (
        hyper["alpha"][:, None]
        + hyper["beta"][:, None] * np.log(distance / 1000)
        + hyper["gamma"][:, None] * basis
        + hyper["tau_event"][:, None] * rng.normal(size=(*shape, 1))
        + (hyper["sigma_anchor"] @ weights.T) * rng.normal(size=(*shape, len(distance)))
    )
    native = np.exp(response) * (distance / VREF_KM_MIN)
    if not np.isfinite(native).all() or (native <= 0).any():
        raise ValueError("unrepresentable native curved predictions")
    return native


def conditional_curvature_effects(
    lane: Lane, hyper: dict[str, np.ndarray], *, seed: int, indices: np.ndarray
) -> tuple[np.ndarray, list[str]]:
    """Exact Normal u|hyperparameters,training values, with no SD floor."""
    selected = _selected(lane, indices)
    shape = _validate_hyper(hyper, 2)
    events = sorted({lane.event_ids[int(i)] for i in selected})
    noise = np.random.default_rng(seed).normal(size=(*shape, len(events)))
    effects = np.empty_like(noise)
    tau2 = hyper["tau_event"] ** 2
    for j, event in enumerate(events):
        ids = np.array([i for i in selected if lane.event_ids[int(i)] == event], dtype=int)
        sigma = np.einsum(
            "...j,ij->...i", hyper["sigma_anchor"], scale_weights(lane.distance_km[ids])
        )
        precision = 1 / sigma**2
        residual = (
            lane.response[ids]
            - hyper["alpha"][..., None]
            - hyper["beta"][..., None] * lane.x[ids]
            - hyper["gamma"][..., None] * curvature_basis(lane.distance_km[ids])
        )
        variance = tau2 / (1 + tau2 * precision.sum(axis=-1))
        mean = variance * np.sum(precision * residual, axis=-1)
        effects[..., j] = mean + np.sqrt(variance) * noise[..., j]
    if not np.isfinite(effects).all():
        raise ValueError("unrepresentable conditional curved effects")
    return effects, events
