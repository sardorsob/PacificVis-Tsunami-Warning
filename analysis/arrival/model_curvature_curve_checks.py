"""Frozen on-grid population-median diagnostics for synthetic calibration only."""

# pyright: basic
from __future__ import annotations

from typing import Any, cast

import arviz_stats as azs
import numpy as np

from analysis.arrival.model_curvature import curvature_basis
from analysis.arrival.model_validation import rank_summary

GRID_KM = (20.0, 50.0, 100.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0)
FAMILY_SIZE = 21


def unbiased_rank(values, truth, seed, original):
    """Keep old fields unless equal-valued samples require an unbiased tie permutation."""
    locations = np.linspace(0, values.shape[1] - 1, 25, dtype=int)
    subset = values[:, locations].reshape(-1)
    ties = int(np.sum(subset == truth))
    less = int(np.sum(subset < truth))
    if original.get("rank") != less or original.get("rank_draws") != len(subset):
        raise ValueError("original rank does not match retained posterior states")
    result = {**original, "tie_count": ties, "rank_tie_handling": "uniform_permutation_if_equal"}
    if ties:
        rng = np.random.default_rng(seed)
        rank = less + int(rng.integers(ties + 1))
        result.update(
            rank=rank, randomized_rank_pit=float((rank + rng.uniform()) / (len(subset) + 1))
        )
    if result["rank_draws"] != 100 or not 0 <= result["rank"] <= 100:
        raise ValueError("four-chain100-spaced rank reference required")
    return result


def curve_checks(posterior, truth, prior, seed):
    coefficients = {k: posterior[k].values for k in ["alpha", "beta", "gamma"]}
    shape = coefficients["alpha"].shape
    if (
        len(shape) != 2
        or shape[0] != 4
        or any(v.shape != shape or not np.isfinite(v).all() for v in coefficients.values())
    ):
        raise ValueError("four aligned finite coefficient chains required")
    d = np.array(GRID_KM)
    x = np.log(d / 1000)
    b = curvature_basis(d)
    values = (
        coefficients["alpha"][..., None]
        + coefficients["beta"][..., None] * x
        + coefficients["gamma"][..., None] * b
    )
    # Deliberately independent algebra for the known generating curve.
    actual = truth["alpha"] + truth["beta"] * x + truth["gamma"] * np.log((d + 500) / (1.5 * d))
    center = np.median(values, axis=(0, 1))
    sd = np.std(values, axis=(0, 1), ddof=1)
    if (
        not np.isfinite(values).all()
        or not np.isfinite(actual).all()
        or not np.isfinite(sd).all()
        or (sd <= 0).any()
    ):
        raise ValueError("finite curves and positive posterior pointwise SDs required")
    maximum = np.max(np.abs((values - center) / sd), axis=-1)
    q90 = float(np.quantile(maximum, 0.9))
    true_max = float(np.max(np.abs((actual - center) / sd)))
    q90_mcse = float(cast(Any, azs).mcse(maximum, method="quantile", prob=0.9))
    functional = {
        "rhat": float(cast(Any, azs).rhat(maximum)),
        "ess_bulk": float(cast(Any, azs).ess(maximum, method="bulk")),
        "ess_tail": float(cast(Any, azs).ess(maximum, method="tail", prob=(0.05, 0.95))),
        "q90_mcse": q90_mcse,
    }
    finite = bool(np.isfinite([*functional.values(), q90, true_max]).all())
    functional["screen_passed"] = bool(
        finite
        and functional["rhat"] <= 1.01
        and functional["ess_bulk"] >= 1000
        and functional["ess_tail"] >= 1000
    )
    estimates = []
    for j, distance in enumerate(d):
        draws = values[..., j]
        qs = np.quantile(draws, [0.05, 0.5, 0.95])
        summary = rank_summary(draws, float(actual[j]), seed + 30 + j)
        summary = unbiased_rank(draws, float(actual[j]), seed + 30 + j, summary)
        prior_sd = float(
            np.sqrt(
                prior["alpha_sd"] ** 2
                + (prior["beta_sd"] * x[j]) ** 2
                + (prior["gamma_sd"] * b[j]) ** 2
            )
        )
        estimates.append(
            {
                "parameter": f"log_median_ratio_{distance:g}km",
                "distance_km": float(distance),
                "truth": float(actual[j]),
                "q05": float(qs[0]),
                "median": float(qs[1]),
                "q95": float(qs[2]),
                "covered90": bool(qs[0] <= actual[j] <= qs[2]),
                "posterior_sd": float(sd[j]),
                "prior_reference_sd": prior_sd,
                "prior_sd_reference": "analytic_Normal_coefficient_prior",
                "posterior_prior_sd_ratio": float(sd[j] / prior_sd),
                "recovery_z": float((draws.mean() - actual[j]) / sd[j]),
                "grid_band_lower": float(center[j] - q90 * sd[j]),
                "grid_band_upper": float(center[j] + q90 * sd[j]),
                **summary,
            }
        )
    return {
        "grid_km": GRID_KM,
        "estimates": estimates,
        "maximum_deviation_diagnostics": functional,
        "grid_band90": {
            "q90": q90,
            "true_maximum_deviation": true_max,
            "covered": bool(true_max <= q90),
            "borderline": bool(abs(true_max - q90) <= max(1e-10, 2 * q90_mcse)),
            "borderline_rule": "distance within2quantileMCSE or1e-10; "
            "coverage classification unchanged",
            "posterior_fraction_within": float(np.mean(maximum <= q90)),
            "scope": "simultaneous_on9grid_population_median_at_zero_event;"
            "excludes_event_record_noise;no_offgrid_guarantee",
        },
        "rank_ready": all(row["rank_ready"] for row in estimates) and functional["screen_passed"],
    }


def sbc_rank_ecdf_screen(ranks, *, family_size=FAMILY_SIZE, alpha=0.05):
    """Fixed N=100, discrete Uniform{0,...,100}; union bound permits dependent quantities."""
    values = np.asarray(ranks)
    if (
        values.shape != (100,)
        or not np.isfinite(values).all()
        or (values != values.astype(int)).any()
        or (values < 0).any()
        or (values > 100).any()
        or family_size != FAMILY_SIZE
        or alpha != 0.05
    ):
        raise ValueError("fixed100-dataset21-quantitySBC screen required")
    grid = np.arange(101)
    empirical = np.mean(values[:, None] <= grid, axis=0)
    reference = (grid + 1) / 101
    maximum = float(np.max(np.abs(empirical - reference)))
    epsilon = float(np.sqrt(np.log(2 * family_size / alpha) / (2 * len(values))))
    return {
        "datasets": 100,
        "family_size": family_size,
        "family_alpha": alpha,
        "max_discrete_ecdf_difference": maximum,
        "dkw_union_halfwidth": epsilon,
        "screen_exceeded": bool(maximum > epsilon),
        "qualification": "approximate_independent_spaced_posterior_ranks;"
        "correlated_quantities_union_bound;notphysical_or_predictive_calibration",
    }
