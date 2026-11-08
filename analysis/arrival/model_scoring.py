"""Event joint predictive integration and chain-aware delta-method Monte Carlo precision."""

# pyright: basic
from __future__ import annotations

import math
from typing import Any, cast

import arviz_stats as azs
import numpy as np
from scipy.special import logsumexp


def mean_mcse(values: np.ndarray) -> float:
    if np.ptp(values) == 0:
        return 0.0
    result = float(cast(Any, azs).mcse(values, method="mean", chain_axis=0, draw_axis=1))
    if not math.isfinite(result) or result < 0:
        raise ValueError("unresolved mean Monte Carlo precision")
    return result


def event_score(log_density: np.ndarray, *, records: int) -> tuple[dict[str, float], np.ndarray]:
    """Log mean density, not mean log density; input includes the native-measure Jacobian.

    Influence draws permit covariance-aware MCSE for events sharing a training fit.
    Delta MCSE is asymptotic and cannot certify severely concentrated density weights.
    """
    if (
        log_density.ndim != 2
        or log_density.shape[0] < 2
        or log_density.shape[1] < 100
        or not np.isfinite(log_density).all()
        or type(records) is not int
        or records < 1
    ):
        raise ValueError("finite (chain,draw) density array and positive event size required")
    normalizer = float(cast(Any, logsumexp)(log_density) - math.log(log_density.size))
    weights = np.exp(log_density - log_density.max())
    relative = weights / weights.mean()
    influence = (relative - 1) / records
    score = normalizer / records
    mcse = mean_mcse(influence)
    chain_values = np.asarray(cast(Any, logsumexp)(log_density, axis=1))
    chain_values -= math.log(log_density.shape[1])
    return {
        "joint_log_predictive": normalizer,
        "normalized_event_score": score,
        "normalized_mcse": mcse,
        "joint_log_mcse_delta": mcse * records,
        "density_weight_concentration_ess": float(weights.sum() ** 2 / np.sum(weights**2)),
        "chain_joint_log_predictive_range": float(np.ptp(chain_values)),
        "records": float(records),
    }, influence


def fold_score(log_density: np.ndarray, event_sizes: np.ndarray) -> dict[str, float]:
    """Equal-event score within one refit; its MCSE retains between-event covariance."""
    if (
        log_density.ndim != 3
        or event_sizes.shape != (log_density.shape[0],)
        or not np.issubdtype(event_sizes.dtype, np.integer)
        or not len(event_sizes)
    ):
        raise ValueError("event x chain x draw densities and integer event sizes required")
    values = [event_score(log_density[i], records=int(n)) for i, n in enumerate(event_sizes)]
    influence = np.mean(np.stack([value[1] for value in values]), axis=0)
    return {
        "equal_event_score": float(np.mean([v[0]["normalized_event_score"] for v in values])),
        "mcse_equal_event_score": mean_mcse(influence),
        "events": float(len(values)),
        "min_density_weight_concentration_ess": min(
            v[0]["density_weight_concentration_ess"] for v in values
        ),
    }


def aggregate_score(folds: list[dict[str, Any]], *, max_mcse: float) -> dict[str, Any]:
    """Weight by event count; combine independent-refit Monte Carlo variance only.

    Overlapping training sets do not create MC dependence when seeds are independent.
    They still limit a sequence-cluster SE's interpretation as transfer uncertainty.
    """
    if not folds or not math.isfinite(max_mcse) or max_mcse <= 0:
        raise ValueError("nonempty sequence folds and positive precision threshold required")
    n = np.array([f["events"] for f in folds], dtype=float)
    score = np.array([f["equal_event_score"] for f in folds], dtype=float)
    error = np.array([f["mcse_equal_event_score"] for f in folds], dtype=float)
    if (
        not np.isfinite([*n, *score, *error]).all()
        or (n < 1).any()
        or not np.equal(n, np.floor(n)).all()
        or (error < 0).any()
    ):
        raise ValueError("finite event counts, scores and MCSEs required")
    weights = n / n.sum()
    mcse = float(np.sqrt(np.sum((weights * error) ** 2)))
    return {
        "equal_event_score": float(np.sum(weights * score)),
        "mcse_equal_event_score": mcse,
        "events": int(n.sum()),
        "sequence_refits": len(folds),
        "precision_passed": bool(
            mcse <= max_mcse and all(f["event_precision_passed"] for f in folds)
        ),
        "mcse_scope": "independent_refit_MC_not_sampling_or_transfer_uncertainty",
    }
