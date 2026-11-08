"""Two-posterior bridge estimate of a joint new-event predictive normalizer ratio.

Meng--Wong identity; monotone root and implicit-root influence MCSE. The augmented
posterior is an integration device only. It never supplies held-out predictions.
"""

# pyright: basic
from __future__ import annotations

import math
from typing import Any, cast

import arviz_stats as azs
import numpy as np
from scipy.optimize import brentq
from scipy.special import log_expit, logsumexp

from analysis.arrival.model_scoring import mean_mcse


def _logmean(x):
    return float(cast(Any, logsumexp)(x) - math.log(x.size))


def _root(a, b, s0, s1):
    shift = math.log(s1 / s0)

    def equation(r):
        return (
            _logmean(log_expit(shift + a - r))
            - math.log(s1)
            - (_logmean(log_expit(-shift - b + r)) - math.log(s0))
        )

    lower = float(min(a.min(), b.min()) - 40)
    upper = float(max(a.max(), b.max()) + 40)
    root = float(cast(Any, brentq)(equation, lower, upper, xtol=1e-10, maxiter=100))
    return root, abs(equation(root))


def _mixing(values):
    if np.ptp(values) == 0:
        return {"constant": True, "passed": True}
    rhat = float(cast(Any, azs).rhat(values))
    bulk = float(cast(Any, azs).ess(values, method="bulk"))
    tail = float(cast(Any, azs).ess(values, method="tail", prob=(0.05, 0.95)))
    finite = bool(np.isfinite([rhat, bulk, tail]).all())
    return {
        "constant": False,
        "rhat": rhat if finite else None,
        "ess_bulk": bulk if finite else None,
        "ess_tail": tail if finite else None,
        "passed": bool(finite and rhat <= 1.01 and bulk >= 400 and tail >= 400),
    }


def bridge_score(a, b, *, records: int):
    """Inputs are log(f_aug/f_train) on independent train/augmented ensembles.

    Both ensembles retain chain/draw structure. Output influences are on the raw
    joint-log-ratio scale; callers combine shared-training influences before MCSE.
    Overlap .1 and |D| .25 are conservative analyst numerical screens, not a proof
    of global posterior exploration. Weight concentration is distinct from ESS.
    """
    a, b = np.asarray(a), np.asarray(b)
    if (
        any(v.ndim != 2 or v.shape[0] < 2 or v.shape[1] < 100 for v in [a, b])
        or a.shape[0] != b.shape[0]
        or any(not np.isfinite(v).all() for v in [a, b])
        or type(records) is not int
        or records < 1
    ):
        raise ValueError("finite independent chain/draw ensembles and event size required")
    s0, s1 = a.size / (a.size + b.size), b.size / (a.size + b.size)
    root, residual = _root(a, b, s0, s1)
    shift = math.log(s1 / s0)
    lq0 = log_expit(shift + a - root)
    lp1 = log_expit(-shift - b + root)
    relative0 = np.exp(lq0 - _logmean(lq0))
    relative1 = np.exp(lp1 - _logmean(lp1))
    # K = 1-D, evaluated without subtracting nearly equal numbers.
    q0, p1 = np.exp(lq0), np.exp(lp1)
    k = float(np.mean(relative0 * np.exp(log_expit(-shift - a + root))))
    k += float(np.mean(relative1 * np.exp(log_expit(shift + b - root))))
    if not math.isfinite(k) or k <= 1e-10:
        raise ValueError("unresolved bridge root conditioning")
    first = (relative0 - relative0.mean()) / k
    second = -(relative1 - relative1.mean()) / k
    error0, error1 = mean_mcse(first), mean_mcse(second)
    error = math.hypot(error0, error1)
    overlap0 = math.exp(_logmean(lq0) - math.log(s1))
    overlap1 = math.exp(_logmean(lp1) - math.log(s0))
    concentration0 = float(relative0.sum() ** 2 / np.sum(relative0**2))
    concentration1 = float(relative1.sum() ** 2 / np.sum(relative1**2))
    chain_roots = [_root(a[i], b[i], s0, s1)[0] for i in range(a.shape[0])]
    mixing0, mixing1 = _mixing(first), _mixing(second)
    score = {
        "joint_log_predictive": root,
        "normalized_event_score": root / records,
        "normalized_mcse": error / records,
        "joint_log_mcse_delta": error,
        "training_influence_mcse": error0,
        "augmented_influence_mcse": error1,
        "overlap": min(overlap0, overlap1),
        "overlap_training": overlap0,
        "overlap_augmented": overlap1,
        "fixedpoint_derivative": 1 - k,
        "implicit_root_denominator": k,
        "root_log_equation_residual": residual,
        "training_weight_concentration": concentration0,
        "augmented_weight_concentration": concentration1,
        "training_functional_mixing": mixing0,
        "augmented_functional_mixing": mixing1,
        "training_q_quantiles": np.quantile(q0, [0, 0.01, 0.1, 0.5, 0.9, 0.99, 1]).tolist(),
        "augmented_q_quantiles": np.quantile(1 - p1, [0, 0.01, 0.1, 0.5, 0.9, 0.99, 1]).tolist(),
        "training_chain_overlap": (q0.mean(axis=1) / s1).tolist(),
        "augmented_chain_overlap": (p1.mean(axis=1) / s0).tolist(),
        "chain_joint_log_predictive": chain_roots,
        "chain_joint_log_predictive_range": float(np.ptp(chain_roots)),
        "s0": s0,
        "s1": s1,
        "records": records,
        "method": "two_posterior_marginal_hyperparameter_bridge",
    }
    score["precision_passed"] = bool(
        score["normalized_mcse"] <= 0.005
        and score["overlap"] >= 0.1
        and abs(score["fixedpoint_derivative"]) <= 0.25
        and residual <= 1e-8
        and min(concentration0, concentration1) >= 100
        and mixing0["passed"]
        and mixing1["passed"]
        and np.ptp(chain_roots) / records <= max(0.005, 6 * error / records)
    )
    return score, first, second


def bridge_fold_score(scores, training_influences, augmented_influences):
    """One shared training ensemble, independent augmented ensembles per held event.

    Production callers must enforce independent sampling seeds/ensembles across
    augmented events and folds. This algebra cannot detect reused random streams.
    """
    if (
        not scores
        or len(scores) != len(training_influences)
        or len(scores) != len(augmented_influences)
    ):
        raise ValueError("one score and paired influence arrays per held event required")
    shape = training_influences[0].shape
    if any(a.shape != shape for a in training_influences):
        raise ValueError("shared training influences must align by chain and draw")
    count = len(scores)
    shared = (
        np.sum([a / s["records"] for a, s in zip(training_influences, scores, strict=True)], axis=0)
        / count
    )
    variance = mean_mcse(shared) ** 2
    variance += sum(
        (mean_mcse(a) / s["records"] / count) ** 2
        for a, s in zip(augmented_influences, scores, strict=True)
    )
    return {
        "equal_event_score": float(np.mean([s["normalized_event_score"] for s in scores])),
        "mcse_equal_event_score": math.sqrt(variance),
        "events": count,
        "event_precision_passed": all(s["precision_passed"] for s in scores),
        "min_bridge_overlap": min(s["overlap"] for s in scores),
        "mcse_scope": "shared_training_covariance_and_independent_augmented_ensembles",
    }
