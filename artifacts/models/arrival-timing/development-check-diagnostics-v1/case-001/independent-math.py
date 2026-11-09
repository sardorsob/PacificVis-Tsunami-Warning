"""Independent pure development-check oracles; no loader, Gate, file or model fit.

Use only caller-admitted held arrays/population after Root's closed-job notice.
No family selection, Gaussian coefficient collapse, clipping or numerical repair.
"""

# pyright: basic
from __future__ import annotations

import argparse
import json
import math
from typing import Any, cast

import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal, norm


def require(condition, message):
    if not condition:
        raise ValueError(message)


def components(population, distance):
    """Literal mean basis and SD interpolation, independently of production helpers."""
    distance = np.asarray(distance, dtype=float)
    p = {k: np.asarray(v, dtype=float) for k, v in population.items()}
    require(
        distance.ndim == 1
        and len(distance)
        and np.isfinite(distance).all()
        and (distance > 0).all()
        and p["alpha"].ndim == 2
        and p["alpha"].shape[0] == 4,
        "finite positive distances and four aligned chains required",
    )
    shape = p["alpha"].shape
    for key, value in p.items():
        require(
            value.shape == (*shape, 3) if key == "sigma_anchor" else value.shape == shape,
            "aligned explicit population dimensions required",
        )
        require(np.isfinite(value).all(), "finite population required")
    mean = np.broadcast_to(p["alpha"][..., None], (*shape, len(distance))).copy()
    if "beta" in p:
        mean += p["beta"][..., None] * np.log(distance / 1000)
    if "gamma" in p:
        mean += p["gamma"][..., None] * (np.log1p(500 / distance) - math.log1p(0.5))
    if "sigma_anchor" in p:
        # Interpolate each sampled SD itself, not its variance; clamp the fixed endpoints.
        sigma = np.array(
            [
                np.interp(np.log(distance), np.log([500, 2000, 5000]), a)
                for a in p["sigma_anchor"].reshape(-1, 3)
            ]
        ).reshape(*shape, len(distance))
    else:
        sigma = np.broadcast_to(p["sigma"][..., None], mean.shape)
    tau = p.get("tau_event", np.zeros(shape))
    require((sigma > 0).all() and (tau >= 0).all(), "proper residual/event scales required")
    return mean, sigma, tau


def block_loglikelihood(native, reference, distance, population, target):
    native, reference = np.asarray(native), np.asarray(reference)
    require(
        native.shape == reference.shape == np.asarray(distance).shape
        and np.isfinite(native).all()
        and np.isfinite(reference).all()
        and (reference > 0).all()
        and (target == "T-CAL" or (native > 0).all()),
        "aligned finite native values; positive durations/reference only",
    )
    response = native if target == "T-CAL" else np.log(native) - np.log(reference)
    mean, sigma, tau = components(population, distance)
    residual = response - mean
    variance = sigma * sigma
    inverse = 1 / variance
    denom = 1 + tau * tau * np.sum(inverse, axis=-1)
    logdet = np.log(variance).sum(axis=-1) + np.log(denom)
    quadratic = np.sum(residual * residual * inverse, axis=-1)
    quadratic -= tau * tau * np.sum(residual * inverse, axis=-1) ** 2 / denom
    modeled = -0.5 * (len(native) * math.log(2 * math.pi) + logdet + quadratic)
    jacobian = 0.0 if target == "T-CAL" else -float(np.log(native).sum())
    return modeled + jacobian, jacobian


def dense_points(native, reference, distance, population, target):
    logl, jacobian = block_loglikelihood(native, reference, distance, population, target)
    response = np.asarray(native) if target == "T-CAL" else np.log(native) - np.log(reference)
    mean, sigma, tau = components(population, distance)
    draws = mean.shape[1]
    points = [(c, d) for c in range(4) for d in sorted({0, draws // 2, draws - 1})]
    errors = []
    for c, d in points:
        covariance = np.diag(sigma[c, d] ** 2) + tau[c, d] ** 2 * np.ones(
            (len(native), len(native))
        )
        independent = (
            float(multivariate_normal.logpdf(response, mean=mean[c, d], cov=covariance)) + jacobian
        )
        errors.append(abs(independent - logl[c, d]))
    require(max(errors) <= 5e-8, "dense full-covariance event oracle failed")
    return dict(points=points, max_abs_error=max(errors), native_log_jacobian=jacobian)


def score_arrays(loglikelihood, records):
    """Joint density average first; normalize by event rows afterwards."""
    loglikelihood = np.asarray(loglikelihood, dtype=float)
    joint = float(cast(Any, logsumexp)(loglikelihood) - math.log(loglikelihood.size))
    weights = np.exp(loglikelihood - float(loglikelihood.max()))
    influence = weights / weights.mean() - 1
    return dict(
        joint_log_predictive=joint,
        normalized_event_score=joint / records,
        joint_influence=influence,
        weight_concentration=float(weights.sum() ** 2 / np.sum(weights**2)),
        chain_joint_scores=(
            cast(Any, logsumexp)(loglikelihood, axis=1) - math.log(loglikelihood.shape[1])
        ),
    )


def shared_influence(event_scores, event_sizes):
    require(len(event_scores) == len(event_sizes) > 0, "all event scores retained")
    return np.mean(
        np.stack(
            [s["joint_influence"] / n for s, n in zip(event_scores, event_sizes, strict=True)]
        ),
        axis=0,
    )


def marginal_streams(native, reference, distance, population, target, native_quantiles):
    """PIT and each saved quantile's CDF/density, without production prediction code."""
    mean, sigma, tau = components(population, distance)
    total = np.sqrt(sigma * sigma + tau[..., None] ** 2)
    response = np.asarray(native) if target == "T-CAL" else np.log(native) - np.log(reference)
    pit = norm.cdf((response - mean) / total)
    result: dict[str, Any] = dict(
        pit=pit.mean(axis=(0, 1)), pit_stream=pit, pit_chain_range=np.ptp(pit.mean(axis=1), axis=0)
    )
    for key, native_q in native_quantiles.items():
        values = np.asarray(native_q)
        require(
            np.isfinite(values).all() and (target == "T-CAL" or (values > 0).all()),
            "finite un-clipped native quantile required",
        )
        r = values if target == "T-CAL" else np.log(values) - np.log(reference)
        z = (r - mean) / total
        cdf = norm.cdf(z)
        density = norm.pdf(z) / total
        if target != "T-CAL":
            density /= values
        result[key] = dict(
            cdf=cdf.mean(axis=(0, 1)), cdf_stream=cdf, native_density=density.mean(axis=(0, 1))
        )
    return result


def self_test():
    rng = np.random.default_rng(20261109)
    shape = (4, 256)
    d = np.array([20, 100, 500, 1000, 2000, 5000, 20000.0])
    reference = d / (math.sqrt(9.80665 * 4000) * 60 / 1000)
    p = dict(
        alpha=rng.normal(0.1, 0.02, shape),
        beta=rng.normal(-0.1, 0.02, shape),
        gamma=rng.normal(0.3, 0.02, shape),
        sigma_anchor=np.exp(rng.normal(np.log([0.25, 0.55, 0.15]), 0.03, (*shape, 3))),
        tau_event=np.exp(rng.normal(math.log(0.35), 0.03, shape)),
    )
    positive = reference * np.exp(np.linspace(-0.4, 0.5, len(d)))
    oracles = [dense_points(positive, reference, d, p, "NCEI-native-duration")]
    signed = np.linspace(-40, 20, len(d))
    for kind in ["pooled", "distance", "event"]:
        q = dict(alpha=np.full(shape, -10.0), sigma=np.full(shape, 12.0))
        if kind != "pooled":
            q["beta"] = np.full(shape, -2.0)
        if kind == "event":
            q["tau_event"] = np.full(shape, 5.0)
        oracles.append(dense_points(signed, reference, d, q, "T-CAL"))
        mu, sd, tau = components(q, d)
        total = np.sqrt(sd * sd + tau[..., None] ** 2)
        quantiles = {
            f"q{int(prob * 100):02d}": mu[0, 0] + total[0, 0] * norm.ppf(prob)
            for prob in [0.05, 0.25, 0.5, 0.75, 0.95]
        }
        streams = marginal_streams(signed, reference, d, q, "T-CAL", quantiles)
        for key, prob in zip(quantiles, [0.05, 0.25, 0.5, 0.75, 0.95], strict=True):
            require(
                np.allclose(streams[key]["cdf"], prob, rtol=0, atol=1e-13), "mixture-CDF oracle"
            )
    simple = dict(alpha=np.full(shape, 0.12), sigma=np.full(shape, 0.3))
    mu, sd, _ = components(simple, d)
    native_q = {
        f"q{round(prob * 100):02d}": reference * np.exp(mu[0, 0] + sd[0, 0] * norm.ppf(prob))
        for prob in [0.05, 0.25, 0.5, 0.75, 0.95]
    }
    positive_cdf = marginal_streams(positive, reference, d, simple, "T-OBS", native_q)
    for key, prob in zip(native_q, [0.05, 0.25, 0.5, 0.75, 0.95], strict=True):
        require(
            np.allclose(positive_cdf[key]["cdf"], prob, rtol=0, atol=1e-13),
            "positive-native log-CDF conversion oracle",
        )
    logl, jac = block_loglikelihood(positive, reference, d, p, "NCEI-native-duration")
    response_only, _ = block_loglikelihood(
        np.log(positive) - np.log(reference), reference, d, p, "T-CAL"
    )
    require(
        np.allclose(logl - response_only, jac, rtol=0, atol=1e-12), "native Jacobian exactly once"
    )
    scores = [score_arrays(logl, len(d)), score_arrays(logl * 0.5, 3)]
    expected = (scores[0]["joint_influence"] / len(d) + scores[1]["joint_influence"] / 3) / 2
    require(
        np.array_equal(shared_influence(scores, [len(d), 3]), expected),
        "shared influence before MCSE",
    )
    print(
        json.dumps(
            dict(
                status="pure_independent_development_math_self_tests_passed",
                dense_oracles=oracles,
                actual_outcomes_or_posteriors_read=False,
                new_sampler_calls=0,
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", required=True)
    parser.parse_args()
    self_test()
