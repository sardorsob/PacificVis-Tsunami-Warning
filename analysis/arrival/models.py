"""Source-specific reported-timing scaffolds; no cross-source likelihood pooling."""

# pyright: basic
from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
from numpy.typing import NDArray

from analysis.arrival.model_data import Lane

PRIORS = "config/arrival-model-priors-v1.toml"


def read_prior(root: Path, target: str, variant: str) -> dict[str, float]:
    """Load a declared scale hypothesis, keeping duration and signed-minute units distinct."""
    if target not in {"NCEI-native-duration", "T-OBS", "T-CAL"} or variant not in {"base", "wider"}:
        raise ValueError("unknown target or prior hypothesis")
    config = tomllib.loads((root / PRIORS).read_text(encoding="utf-8"))
    if config["schema_version"] != "arrival_model_priors_v1":
        raise ValueError("unknown prior schema")
    if config["alpha_mean"] != 0 or config["beta_mean"] != 0:
        raise ValueError("this scaffold requires declared zero prior locations")
    for field, expected in {
        "observation": "working_continuous_density_for_native_reported_values",
        "origin_error": "not_separately_identified_from_event_variation",
        "display_precision": "metadata_only_not_accuracy",
        "selection": "conditional_on_archive_reporting_not_corrected_MNAR",
    }.items():
        if config.get(field) != expected:
            raise ValueError(f"prior metadata contract mismatch: {field}")
    family = "calibration" if target == "T-CAL" else "duration"
    prior = {key: float(value) for key, value in config[family][variant].items()}
    if set(prior) != {"alpha_sd", "beta_sd", "tau_sd", "sigma_sd"} or not all(
        math.isfinite(value) and value > 0 for value in prior.values()
    ):
        raise ValueError("invalid prior scale dictionary")
    return prior


def build_model(
    lane: Lane,
    prior: dict[str, float],
    *,
    kind: str = "event",
    indices: NDArray[np.int64] | None = None,
) -> pm.Model:
    """Build a literal training subset; no held-out outcome contributes to its graph."""
    if kind not in {"pooled", "distance", "event"}:
        raise ValueError("unknown scaffold")
    selected = np.flatnonzero(lane.included) if indices is None else indices
    if (
        selected.ndim != 1
        or not np.issubdtype(selected.dtype, np.integer)
        or not len(selected)
        or len(set(selected.tolist())) != len(selected)
        or (selected < 0).any()
        or (selected >= len(lane.rows)).any()
    ):
        raise ValueError("invalid training indices")
    if not lane.included[selected].all():
        raise ValueError("training includes unresolved evidence units")
    events = sorted({lane.event_ids[int(i)] for i in selected})
    lookup = {event: i for i, event in enumerate(events)}
    event_index = np.array([lookup[lane.event_ids[int(i)]] for i in selected])
    coords = {"record": [lane.record_ids[int(i)] for i in selected], "event": events}
    with pm.Model(coords=coords) as model:
        x = cast(Any, pm.Data("x", lane.x[selected], dims="record"))
        alpha = pm.Normal("alpha", 0, prior["alpha_sd"])
        mu = alpha + 0 * x
        if kind != "pooled":
            beta = pm.Normal("beta", 0, prior["beta_sd"])
            mu = mu + beta * x
        if kind == "event":
            tau = pm.HalfNormal("tau_event", prior["tau_sd"])
            z = pm.Normal("z_event", 0, 1, dims="event")
            effect = cast(Any, pm.Deterministic("event_effect", tau * z, dims="event"))
            mu = mu + effect[event_index]
        sigma = pm.HalfNormal("sigma", prior["sigma_sd"])
        pm.Normal("response", mu, sigma, observed=lane.response[selected], dims="record")
    return model
