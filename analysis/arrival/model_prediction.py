"""Explicit new-event Gaussian predictions in native reported units."""

# pyright: basic
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr

from analysis.arrival.model_scale import scale_weights


def posterior_components(posterior: Any, kind: str, distance: np.ndarray):
    if kind not in {"pooled", "distance", "event", "distance-scale"}:
        raise ValueError("unknown prediction model")
    alpha = np.asarray(posterior["alpha"].values)
    beta = np.asarray(posterior["beta"].values) if kind != "pooled" else np.zeros_like(alpha)
    tau = (
        np.asarray(posterior["tau_event"].values)
        if kind in {"event", "distance-scale"}
        else np.zeros_like(alpha)
    )
    weights = scale_weights(distance)
    mean = alpha[..., None] + beta[..., None] * np.log(distance / 1000)
    sigma = (
        np.einsum("cdj,ij->cdi", posterior["sigma_anchor"].values, weights)
        if kind == "distance-scale"
        else np.broadcast_to(posterior["sigma"].values[..., None], mean.shape)
    )
    if alpha.ndim != 2 or tau.shape != alpha.shape or beta.shape != alpha.shape:
        raise ValueError("chain/draw coordinates must align")
    if (
        not np.isfinite(mean).all()
        or not np.isfinite(sigma).all()
        or not np.isfinite(tau).all()
        or (sigma <= 0).any()
        or (tau < 0).any()
    ):
        raise ValueError("invalid Gaussian posterior draws")
    return mean, sigma, tau


def marginal_report_predictions(
    response: np.ndarray,
    mean: np.ndarray,
    sigma: np.ndarray,
    tau: np.ndarray,
    reference: np.ndarray,
    target: str,
):
    """Integrate event/record noise analytically; invert posterior-mixture marginal CDFs.

    These marginal summaries complement, and never replace, the joint event score.
    Gaussian noise integration and root tolerance are separate from posterior MC error.
    """
    if (
        target not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or mean.ndim != 3
        or sigma.shape != mean.shape
        or tau.shape != mean.shape[:2]
        or response.shape != (mean.shape[-1],)
        or reference.shape != response.shape
        or not np.isfinite(response).all()
        or (reference <= 0).any()
    ):
        raise ValueError("aligned native-unit Gaussian prediction arrays required")
    total = np.sqrt(sigma**2 + tau[..., None] ** 2)
    pit_draws = ndtr((response - mean) / total)
    out = {
        "pit": pit_draws.mean(axis=(0, 1)),
        "pit_chain_range": np.ptp(pit_draws.mean(axis=1), axis=0),
    }
    for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
        roots = []
        for j in range(len(response)):
            mu, sd = mean[..., j].reshape(-1), total[..., j].reshape(-1)
            roots.append(
                brentq(
                    lambda z, m=mu, s=sd, p=q: float(ndtr((z - m) / s).mean() - p),
                    float(np.min(mu - 12 * sd)),
                    float(np.max(mu + 12 * sd)),
                    xtol=1e-10,
                )
            )
        values = np.asarray(roots)
        native = values if target == "T-CAL" else np.exp(values) * reference
        if not np.isfinite(native).all() or (target != "T-CAL" and (native <= 0).any()):
            raise ValueError("unrepresentable native predictive quantile")
        out[f"q{round(q * 100):02d}"] = native
    return out
