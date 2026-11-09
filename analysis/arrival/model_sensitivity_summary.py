"""Pure finite-draw summaries and fitted-event PPCs for the eight MS-5 forms.

Population coefficients stay explicit under every prior family. Positive-native
quantiles are calculated in log space and then exponentiated; no finite draws
are removed and no predictive means or variances are estimated.
"""

# pyright: basic
from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival.model_curvature import conditional_curvature_effects, curvature_basis
from analysis.arrival.model_data import VREF_KM_MIN, Lane
from analysis.arrival.model_scale import conditional_scale_effects, scale_weights
from analysis.arrival.model_sensitivity_design import support_summary
from analysis.arrival.model_sensitivity_priors import (
    POSITIVE_NATIVE_MOMENTS,
    _population_spec,
    prior_predictive_log_or_native,
)
from analysis.arrival.model_validation import conditional_event_effects

GRID_KM = np.array([20, 50, 100, 500, 1000, 2000, 5000, 10000, 20000], dtype=float)
QUANTILES = (0.05, 0.5, 0.95)


def _validated(lane, kind, posterior, indices, seed, draws):
    support = support_summary(lane, kind, indices)
    spec = _population_spec(lane.target, kind)
    if (
        not isinstance(posterior, xr.Dataset)
        or posterior.sizes.get("chain") != 4
        or posterior.sizes.get("draw", 0) < 1
        or type(seed) is not int
        or not 0 <= seed < 2**32
        or type(draws) is not int
        or not 1 <= draws <= 4 * posterior.sizes.get("draw", 0)
    ):
        raise ValueError("four nonempty chains, bounded draw count and uint32 seed required")
    if any(not posterior.get_index(axis).is_unique for axis in ["chain", "draw"]):
        raise ValueError("unique chain and draw coordinates required")
    if not set(spec) <= set(posterior.data_vars):
        raise ValueError("complete explicit population posterior required")
    hyper = {}
    for name, (_, shape) in spec.items():
        variable = posterior[name]
        expected_dims = ("chain", "draw", "scale_anchor_km") if shape else ("chain", "draw")
        values = np.asarray(variable.values)
        if variable.dims != expected_dims or values.shape != (4, posterior.sizes["draw"], *shape):
            raise ValueError("literal aligned population chain/draw/anchor dimensions required")
        if not np.issubdtype(values.dtype, np.number) or not np.isfinite(values).all():
            raise ValueError("finite real population posterior required")
        if np.iscomplexobj(values):
            raise ValueError("finite real population posterior required")
        if name in {"sigma", "sigma_anchor"} and (values <= 0).any():
            raise ValueError("positive residual scales required")
        if name == "tau_event" and (values < 0).any():
            raise ValueError("nonnegative event scale required")
        hyper[name] = values.astype(float, copy=False)
    if "sigma_anchor" in spec and posterior.scale_anchor_km.values.tolist() != [500, 2000, 5000]:
        raise ValueError("literal500/2000/5000km residual anchor order required")
    return hyper, support


def _components(population, distance):
    count = len(population["alpha"])
    with np.errstate(over="ignore", invalid="ignore"):
        mean = np.broadcast_to(population["alpha"][:, None], (count, len(distance))).copy()
        if "beta" in population:
            mean += population["beta"][:, None] * np.log(distance / 1000)
        if "gamma" in population:
            mean += population["gamma"][:, None] * curvature_basis(distance)
        sigma = (
            population["sigma_anchor"] @ scale_weights(distance).T
            if "sigma_anchor" in population
            else np.broadcast_to(population["sigma"][:, None], mean.shape)
        )
    return mean, sigma


def predictive_draws(
    lane: Lane,
    kind: str,
    posterior: xr.Dataset,
    *,
    indices: np.ndarray,
    seed: int,
    draws: int = 800,
) -> dict[str, Any]:
    """Return auditably selected draws; positive predictions stay log-native.

    Conditional event effects use the existing exact Normal conditional law,
    independently of the population-prior family. One effect is shared by all
    reports from an event. The new-event curve shares one new effect across its
    nine distances and draws independent observation noise at each distance.
    """
    hyper, support = _validated(lane, kind, posterior, indices, seed, draws)
    seeds = [int(value) for value in np.random.SeedSequence(seed).generate_state(4)]
    total = 4 * posterior.sizes["draw"]
    take = np.sort(np.random.default_rng(seeds[0]).choice(total, size=draws, replace=False))
    population = {k: v.reshape((total, *v.shape[2:]))[take] for k, v in hyper.items()}
    events = sorted({lane.event_ids[int(i)] for i in indices})
    event_index = np.array([events.index(lane.event_ids[int(i)]) for i in indices])
    if "tau_event" in hyper:
        helper = {
            "mean-curvature": conditional_curvature_effects,
            "distance-scale": conditional_scale_effects,
            "event": conditional_event_effects,
        }[kind]
        all_effects, actual_events = helper(lane, hyper, seed=seeds[1], indices=indices)
        if actual_events != events:
            raise ValueError("conditional event coordinate order changed")
        effects = all_effects.reshape(total, len(events))[take]
    else:
        effects = np.zeros((draws, len(events)))
    mean, sigma = _components(population, lane.distance_km[indices])
    with np.errstate(over="ignore", invalid="ignore"):
        conditional = (
            mean
            + effects[:, event_index]
            + sigma * np.random.default_rng(seeds[2]).normal(size=mean.shape)
        )
        conditional_measure = (
            conditional
            if lane.target == "T-CAL"
            else conditional + np.log(lane.reference_minutes[indices])
        )
    new_event = prior_predictive_log_or_native(
        lane.target, kind, population, GRID_KM, seed=seeds[3]
    )
    return {
        "population": population,
        "conditional_effects": effects,
        "events": events,
        "conditional_response": conditional,
        "conditional_measure": conditional_measure,
        "new_event_response": new_event["response"],
        "new_event_measure": new_event[
            "native_minutes" if lane.target == "T-CAL" else "log_native_minutes"
        ],
        "measure": "native_minutes" if lane.target == "T-CAL" else "log_native_minutes",
        "posterior_flat_indices": take,
        "stream_seeds": seeds,
        "support": support,
    }


def _empirical_quantiles(values, probabilities, *, axis=None):
    """Linear empirical quantiles without subtracting opposite-sign extremes."""
    values = np.asarray(values, dtype=float)
    if axis is None:
        values, axis = values.reshape(-1), 0
    ordered = np.sort(values, axis=axis)
    position = np.asarray(probabilities) * (values.shape[axis] - 1)
    lower = np.take(ordered, np.floor(position).astype(int), axis=axis)
    upper = np.take(ordered, np.ceil(position).astype(int), axis=axis)
    shape = [1] * lower.ndim
    shape[axis] = len(position)
    weight = (position - np.floor(position)).reshape(shape)
    with np.errstate(over="ignore", invalid="ignore"):
        result = (1 - weight) * lower + weight * upper
    return np.where(lower == upper, lower, result)


def _quantiles(values):
    bad = int(np.count_nonzero(~np.isfinite(values)))
    quantiles = [None] * 3
    quantile_bad = 0
    if not bad:
        computed = _empirical_quantiles(values, QUANTILES)
        quantile_bad = int(np.count_nonzero(~np.isfinite(computed)))
        quantiles = [float(v) if np.isfinite(v) else None for v in computed]
    return {
        **dict(zip(["q05", "q50", "q95"], quantiles, strict=True)),
        "nonfinite_values": bad,
        "nonfinite_quantile_values": quantile_bad,
        "quantile_valid": bad == quantile_bad == 0,
    }


def _native_quantiles(values, positive):
    result = _quantiles(values)
    if not positive:
        return {**result, "native_representable": result["quantile_valid"]}
    for key in ["q05", "q50", "q95"]:
        value = result[key]
        result["log_" + key] = value
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            native = None if value is None else float(np.exp(value))
        result[key] = native if native is not None and np.isfinite(native) and native > 0 else None
    result["native_representable"] = all(result[k] is not None for k in ["q05", "q50", "q95"])
    return result


def summarize_posterior(
    lane: Lane,
    kind: str,
    posterior: xr.Dataset,
    *,
    indices: np.ndarray,
    seed: int,
    draws: int = 800,
) -> dict[str, Any]:
    """Serializable population/derived quantiles and conditional, in-sample PPCs.

    A native-unrepresentable quantile is None with its finite log quantile kept.
    Nonfinite modeled replicates invalidate affected quantiles; none are dropped.
    Empty distance strata are omitted. These checks are not held-out validation.
    """
    simulated = predictive_draws(lane, kind, posterior, indices=indices, seed=seed, draws=draws)
    positive = lane.target != "T-CAL"
    hyper = {k: np.asarray(posterior[k].values, dtype=float) for k in simulated["population"]}
    parameters = []
    for name, values in hyper.items():
        for anchor in range(3) if name == "sigma_anchor" else [None]:
            parameters.append(
                {
                    "parameter": name,
                    "anchor_km": None if anchor is None else [500, 2000, 5000][anchor],
                    **_quantiles(values if anchor is None else values[..., anchor]),
                }
            )
    total = 4 * posterior.sizes["draw"]
    flat = {k: v.reshape((total, *v.shape[2:])) for k, v in hyper.items()}
    mean, sigma = _components(flat, GRID_KM)
    with np.errstate(over="ignore", invalid="ignore"):
        medians = mean if not positive else mean + np.log(GRID_KM / VREF_KM_MIN)
    support = simulated["support"]
    curves, derived = [], []
    for j, distance in enumerate(GRID_KM):
        extrapolation = (
            "below"
            if distance < support["distance_km_min"]
            else "above"
            if distance > support["distance_km_max"]
            else "within"
        )
        labels = {
            "distance_km": float(distance),
            "support": extrapolation,
            "within_training_distance_range": extrapolation == "within",
            "residual_scale_endpoint_clamped": bool(
                "sigma_anchor" in flat and (distance < 500 or distance > 5000)
            ),
        }
        for curve, values in [
            ("population_median", medians),
            ("new_event", simulated["new_event_measure"]),
        ]:
            curves.append({**labels, "curve": curve, **_native_quantiles(values[:, j], positive)})
        derived.append(
            {**labels, "quantity": "residual_sd_modeled_response", **_quantiles(sigma[:, j])}
        )
        if positive:
            with np.errstate(over="ignore", invalid="ignore"):
                elasticity = (
                    np.ones(total)
                    + flat.get("beta", np.zeros(total))
                    - flat.get("gamma", np.zeros(total)) * 500 / (distance + 500)
                )
            derived.append(
                {
                    **labels,
                    "quantity": "population_median_log_distance_elasticity",
                    **_quantiles(elasticity),
                }
            )
    records = [
        {
            "record_id": lane.record_ids[int(i)],
            "event_id": lane.event_ids[int(i)],
            "sequence": lane.sequences[int(i)],
            "site_id": lane.site_ids[int(i)],
            "distance_km": float(lane.distance_km[i]),
            "observed_native_minutes": float(lane.y[i]),
            **_native_quantiles(simulated["conditional_measure"][:, j], positive),
        }
        for j, i in enumerate(indices)
    ]
    distance = lane.distance_km[indices]
    ppc = []
    for label, mask in [
        ("all", np.ones(len(indices), dtype=bool)),
        ("under-500km", distance < 500),
        ("500-to-2000km", (distance >= 500) & (distance < 2000)),
        ("2000-to-5000km", (distance >= 2000) & (distance < 5000)),
        ("5000km-and-above", distance >= 5000),
    ]:
        if not mask.any():
            continue
        for scale, observed, replicated, native_positive in [
            ("modeled-response", lane.response[indices], simulated["conditional_response"], False),
            (
                "native-minutes",
                np.log(lane.y[indices]) if positive else lane.y[indices],
                simulated["conditional_measure"],
                positive,
            ),
        ]:
            for q in QUANTILES:
                # A nonfinite replicate invalidates the cell, even if this quantile is finite.
                bad = int(np.count_nonzero(~np.isfinite(replicated[:, mask])))
                if bad:
                    stats = {
                        "q05": None,
                        "q50": None,
                        "q95": None,
                        "quantile_valid": False,
                        "nonfinite_values": bad,
                        "nonfinite_quantile_values": 0,
                        "native_representable": False,
                    }
                    if native_positive:
                        stats.update(log_q05=None, log_q50=None, log_q95=None)
                else:
                    replicate_quantiles = _empirical_quantiles(replicated[:, mask], [q], axis=1)[
                        :, 0
                    ]
                    stats = _native_quantiles(replicate_quantiles, native_positive)
                observed_q = float(_empirical_quantiles(observed[mask], [q])[0])
                observed_stats = _native_quantiles(np.array([observed_q]), native_positive)
                ppc.append(
                    {
                        "stratum": label,
                        "scale": scale,
                        "quantile": q,
                        "records": int(mask.sum()),
                        "observed": observed_stats["q50"],
                        "observed_log_native": observed_q
                        if native_positive and np.isfinite(observed_q)
                        else None,
                        "observed_quantile_valid": observed_stats["quantile_valid"],
                        **{"replicated_" + key: value for key, value in stats.items()},
                    }
                )
    arrays = {
        k: simulated[k]
        for k in [
            "conditional_response",
            "conditional_measure",
            "new_event_response",
            "new_event_measure",
        ]
    }
    arrays["population_median_measure"] = medians
    nonfinite = {k: int(np.count_nonzero(~np.isfinite(v))) for k, v in arrays.items()}
    unrepresentable = {}
    if positive:
        for key in ["conditional_measure", "new_event_measure", "population_median_measure"]:
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                native = np.exp(arrays[key])
            unrepresentable[key] = int(np.count_nonzero(~np.isfinite(native) | (native <= 0)))
    return {
        "target": lane.target,
        "kind": kind,
        "parameters": parameters,
        "derived": derived,
        "curves": curves,
        "conditional_ppc": ppc,
        "record_intervals": records,
        "membership": [lane.record_ids[int(i)] for i in indices],
        "support": support,
        "posterior_flat_indices": simulated["posterior_flat_indices"].tolist(),
        "stream_seeds": simulated["stream_seeds"],
        "posterior_draws": total,
        "conditional_predictive_draws": draws,
        "nonfinite_values": nonfinite,
        "unrepresentable_native_draws": unrepresentable,
        "positive_native_moments": POSITIVE_NATIVE_MOMENTS
        if positive
        else "not_applicable_signed_target",
        "quantile_calculation": (
            "positive_native_quantiles_computed_in_log_space_then_exponentiated"
        ),
        "conditional_ppc_scope": "fitted_events_in_sample_not_held_out_validation",
        "modeled_response_measure": "log_ratio" if positive else "signed_minutes",
        "native_units": "minutes",
        "native_predictive_means_or_variances_reported": False,
    }
