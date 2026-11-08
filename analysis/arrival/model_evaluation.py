"""Joint Gaussian new-event integration; density is scored in native reported minutes."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


def gaussian_event_logpdf(
    response: NDArray[np.float64],
    mean: NDArray[np.float64],
    record_scale: NDArray[np.float64] | float,
    event_scale: NDArray[np.float64] | float,
) -> NDArray[np.float64]:
    """Integrate one unseen Normal event effect; final axis holds its records.

    Mean/record_scale broadcast over posterior draws and records; event_scale
    broadcasts over draws. Centered quadratic form avoids subtracting large terms.
    """
    y, mu, sigma = np.broadcast_arrays(response, mean, record_scale)
    tau = np.asarray(event_scale)
    if not y.size or not np.isfinite(y).all() or not np.isfinite(mu).all():
        raise ValueError("nonempty finite event response and mean required")
    if not np.isfinite(sigma).all() or (sigma <= 0).any():
        raise ValueError("finite positive record scale required")
    if not np.isfinite(tau).all() or (tau < 0).any():
        raise ValueError("finite nonnegative event scale required")
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        weight = 1 / sigma**2
        total = weight.sum(axis=-1)
        residual = y - mu
        center = (weight * residual).sum(axis=-1) / total
        inflation = 1 + tau**2 * total
        quadratic = (weight * (residual - np.expand_dims(center, -1)) ** 2).sum(axis=-1)
        quadratic += total * center**2 / inflation
        logdet = (2 * np.log(sigma)).sum(axis=-1) + np.log(inflation)
        result = -0.5 * (y.shape[-1] * math.log(2 * math.pi) + logdet + quadratic)
    if not np.isfinite(result).all():
        raise ValueError("unrepresentable event density")
    return result


def native_event_logpdf(
    minutes: NDArray[np.float64],
    reference: NDArray[np.float64],
    target: str,
    mean: NDArray[np.float64],
    record_scale: NDArray[np.float64] | float,
    event_scale: NDArray[np.float64] | float,
) -> NDArray[np.float64]:
    """Return the same native-minute density measure for all comparable candidates."""
    if target == "T-CAL":
        return gaussian_event_logpdf(minutes, mean, record_scale, event_scale)
    if target not in {"T-OBS", "NCEI-native-duration"}:
        raise ValueError("unknown target")
    if (minutes <= 0).any() or (reference <= 0).any() or not np.isfinite(reference).all():
        raise ValueError("positive duration/reference required")
    response = np.log(minutes) - np.log(reference)
    return gaussian_event_logpdf(response, mean, record_scale, event_scale) - np.log(minutes).sum()
