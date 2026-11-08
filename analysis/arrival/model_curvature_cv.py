"""Three-coefficient Gaussian sequence prediction in the native-duration measure."""

# pyright: basic
from __future__ import annotations

import numpy as np

from analysis.arrival.model_collapsed import CollapsedGaussian
from analysis.arrival.model_curvature import _validate_hyper, curvature_basis
from analysis.arrival.model_data import VREF_KM_MIN
from analysis.arrival.model_scale import ANCHORS_KM, scale_weights


def curvature_design(distance):
    basis = curvature_basis(distance)
    return np.c_[np.ones(len(distance)), np.log(distance / 1000), basis]


def curvature_kernel(response, distance, events, prior):
    return CollapsedGaussian(
        response,
        curvature_design(distance),
        events,
        scale_weights(distance),
        [prior[k + "_sd"] for k in ["alpha", "beta", "gamma"]],
    )


def native_event_logpdf(kernel, variance, response, distance, native, events):
    response, native, events = [np.asarray(v) for v in [response, native, events]]
    if (
        response.ndim != 1
        or not len(response)
        or native.shape != response.shape
        or events.shape != response.shape
        or distance.shape != response.shape
        or len(set(events)) != 1
        or set(events) & set(kernel.events)
        or not np.isfinite(native).all()
        or (native <= 0).any()
        or not np.allclose(
            response, np.log(native) - np.log(distance / VREF_KM_MIN), rtol=0, atol=1e-12
        )
    ):
        raise ValueError("one wholly new event with aligned native-minute response required")
    return (
        kernel.new_event_logpdf(
            variance, response, curvature_design(distance), scale_weights(distance)
        )
        - np.log(native).sum()
    )


def posterior_components(posterior, distance):
    hyper = {
        k: np.asarray(posterior[k].values)
        for k in ["alpha", "beta", "gamma", "tau_event", "sigma_anchor"]
    }
    _validate_hyper(hyper, 2)
    if not np.array_equal(posterior.coords["scale_anchor_km"].values, ANCHORS_KM):
        raise ValueError("frozen residual SD anchor order required")
    design = curvature_design(distance)
    mean = (
        hyper["alpha"][..., None]
        + hyper["beta"][..., None] * design[:, 1]
        + hyper["gamma"][..., None] * design[:, 2]
    )
    sigma = np.einsum("cdj,ij->cdi", hyper["sigma_anchor"], scale_weights(distance))
    return mean, sigma, hyper["tau_event"]
