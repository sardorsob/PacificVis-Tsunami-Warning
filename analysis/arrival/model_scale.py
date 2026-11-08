"""Positive residual SD, linear in log distance between three fixed anchors."""

# pyright: basic
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pymc as pm
import pytensor.tensor as pt
from pytensor.tensor.extra_ops import bincount

from analysis.arrival.model_data import VREF_KM_MIN, Lane

ANCHORS_KM = (500.0, 2000.0, 5000.0)


def simulate_scale_response(
    lane: Lane, truth: dict[str, Any], *, seed: int
) -> tuple[np.ndarray, dict[str, float]]:
    """Independent simulator uses literal interpolation and design, never actual responses."""
    anchors = np.asarray(truth["sigma_anchor"], dtype=float)
    if (
        anchors.shape != (3,)
        or not np.isfinite(anchors).all()
        or (anchors <= 0).any()
        or not np.isfinite([truth[k] for k in ["alpha", "beta", "tau_event"]]).all()
        or truth["tau_event"] < 0
    ):
        raise ValueError("finite generating parameters and positive anchor SDs required")
    rng = np.random.default_rng(seed)
    effects = {
        event: float(rng.normal() * truth["tau_event"]) for event in sorted(set(lane.event_ids))
    }
    sigma = np.interp(np.log(lane.distance_km), np.log(ANCHORS_KM), anchors)
    response = (
        truth["alpha"]
        + truth["beta"] * lane.x
        + np.array([effects[e] for e in lane.event_ids])
        + sigma * rng.normal(size=len(lane.rows))
    )
    if not np.isfinite(response).all():
        raise ValueError("unrepresentable synthetic response")
    return response, effects


def new_scale_event_predictions(
    hyper: dict[str, np.ndarray], distance: np.ndarray, *, seed: int
) -> np.ndarray:
    """Native-minute predictions for one new event; its effect is shared across query rows."""
    weights = scale_weights(distance)
    count = len(hyper["alpha"])
    if (
        any(hyper[k].shape != (count,) for k in ["alpha", "beta", "tau_event"])
        or hyper["sigma_anchor"].shape != (count, 3)
        or any(not np.isfinite(v).all() for v in hyper.values())
        or (hyper["sigma_anchor"] <= 0).any()
        or (hyper["tau_event"] < 0).any()
    ):
        raise ValueError("aligned finite population draws and positive record scales required")
    rng = np.random.default_rng(seed)
    response = (
        hyper["alpha"][:, None]
        + hyper["beta"][:, None] * np.log(distance / 1000)
        + hyper["tau_event"][:, None] * rng.normal(size=(count, 1))
        + (hyper["sigma_anchor"] @ weights.T) * rng.normal(size=(count, len(distance)))
    )
    native = np.exp(response) * (distance / VREF_KM_MIN)
    if not np.isfinite(native).all() or (native <= 0).any():
        raise ValueError("unrepresentable native prediction")
    return native


def scale_weights(distance_km: np.ndarray) -> np.ndarray:
    """Fixed convex interpolation, with constant endpoint extrapolation; no learned centering."""
    if (
        distance_km.ndim != 1
        or not len(distance_km)
        or not np.isfinite(distance_km).all()
        or (distance_km <= 0).any()
    ):
        raise ValueError("finite positive distance vector required")
    x = np.log(distance_km)
    anchors = np.log(ANCHORS_KM)
    return np.column_stack([np.interp(x, anchors, np.eye(3)[j]) for j in range(3)])


def scale_prior_moments(weights: np.ndarray, sd: float) -> tuple[np.ndarray, np.ndarray]:
    """Marginal prior mean and second moment of the interpolated SD, not response variance."""
    if (
        not np.isfinite(sd)
        or sd <= 0
        or weights.ndim != 2
        or weights.shape[1] != 3
        or not np.isfinite(weights).all()
        or (weights < 0).any()
        or not np.allclose(weights.sum(axis=1), 1)
    ):
        raise ValueError("positive HalfNormal scale and convex weight matrix required")
    return np.full(len(weights), sd * np.sqrt(2 / np.pi)), sd**2 * (
        2 / np.pi + (1 - 2 / np.pi) * np.sum(weights**2, axis=1)
    )


def _selected(lane: Lane, indices: np.ndarray | None) -> np.ndarray:
    if lane.target != "NCEI-native-duration":
        raise ValueError("this scale candidate is scoped to primary NCEI")
    selected = np.flatnonzero(lane.included) if indices is None else indices
    if (
        selected.ndim != 1
        or not np.issubdtype(selected.dtype, np.integer)
        or not len(selected)
        or len(set(selected.tolist())) != len(selected)
        or (selected < 0).any()
        or (selected >= len(lane.rows)).any()
        or not lane.included[selected].all()
    ):
        raise ValueError("explicit approved training subset required")
    return selected


def build_scale_model(
    lane: Lane, prior: dict[str, float], *, indices: np.ndarray | None = None
) -> pm.Model:
    """Exact stable heteroskedastic Normal event integral; prediction is explicit."""
    selected = _selected(lane, indices)
    events = sorted({lane.event_ids[int(i)] for i in selected})
    lookup = {event: i for i, event in enumerate(events)}
    event_index = np.array([lookup[lane.event_ids[int(i)]] for i in selected])
    weights = scale_weights(lane.distance_km[selected])
    coords = {
        "event": events,
        "record": [lane.record_ids[int(i)] for i in selected],
        "scale_anchor_km": list(ANCHORS_KM),
    }
    with pm.Model(coords=coords) as model:
        alpha = pm.Normal("alpha", 0, prior["alpha_sd"])
        beta = pm.Normal("beta", 0, prior["beta_sd"])
        tau = pm.HalfNormal("tau_event", prior["tau_sd"])
        anchors = pm.HalfNormal("sigma_anchor", prior["sigma_sd"], dims="scale_anchor_km")
        sigma = pt.dot(weights, anchors)
        precision = 1 / sigma**2
        residual = lane.response[selected] - alpha - beta * lane.x[selected]
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


def conditional_scale_effects(
    lane: Lane, hyper: dict[str, np.ndarray], *, seed: int, indices: np.ndarray
) -> tuple[np.ndarray, list[str]]:
    """Exact u|hyperparameters,training data, with per-record precisions and shared event u."""
    selected = _selected(lane, indices)
    if set(hyper) != {"alpha", "beta", "tau_event", "sigma_anchor"}:
        raise ValueError("six scalar hyperparameters in four named arrays required")
    shape = hyper["alpha"].shape
    if (
        len(shape) != 2
        or hyper["beta"].shape != shape
        or hyper["tau_event"].shape != shape
        or hyper["sigma_anchor"].shape != (*shape, 3)
        or any(not np.isfinite(value).all() for value in hyper.values())
        or (hyper["tau_event"] < 0).any()
        or (hyper["sigma_anchor"] <= 0).any()
    ):
        raise ValueError(
            "finite aligned chain/draw hyperparameters and positive record scales required"
        )
    events = sorted({lane.event_ids[int(i)] for i in selected})
    noise = np.random.default_rng(seed).normal(size=(*shape, len(events)))
    effects = np.empty_like(noise)
    tau2 = hyper["tau_event"] ** 2
    for j, event in enumerate(events):
        ids = np.array([i for i in selected if lane.event_ids[int(i)] == event], dtype=int)
        weights = scale_weights(lane.distance_km[ids])
        sigma = np.einsum("...j,ij->...i", hyper["sigma_anchor"], weights)
        precision = 1 / sigma**2
        residual = (
            lane.response[ids] - hyper["alpha"][..., None] - hyper["beta"][..., None] * lane.x[ids]
        )
        variance = tau2 / (1 + tau2 * precision.sum(axis=-1))
        mean = variance * np.sum(precision * residual, axis=-1)
        effects[..., j] = mean + np.sqrt(variance) * noise[..., j]
    if not np.isfinite(effects).all():
        raise ValueError("unrepresentable conditional effects; no SD floor applied")
    return effects, events
