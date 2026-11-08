"""Ancestral checks for one smooth mean candidate, before any candidate posterior."""

# pyright: basic
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import numpy as np
import xarray as xr

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_curvature import curvature_basis, new_curvature_event_predictions
from analysis.arrival.model_data import CONTRACT, VREF_KM_MIN, load_lanes
from analysis.arrival.model_scale import ANCHORS_KM, scale_weights
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import PRIORS, read_prior

CONFIG = "config/arrival-mean-curvature-v1.toml"
VARIANTS = ("base", "gamma_wider_only", "joint_wider")


def read_curvature_prior(root: Path, variant: str) -> dict[str, float]:
    design = tomllib.loads((root / CONFIG).read_text())
    if (
        design["schema_version"] != "arrival_mean_curvature_v1"
        or design["target"] != "NCEI-native-duration"
        or design["transition_km"] != 500
        or design["reference_km"] != 1000
        or tuple(design["variants"]) != VARIANTS
        or variant not in VARIANTS
        or design["base_priors"] != PRIORS
        or sha256(root / design["base_priors"]) != design["base_priors_sha256"]
    ):
        raise ValueError("unsupported or changed fixed curvature prior design")
    gamma = design["gamma_base_sd" if variant == "base" else "gamma_wider_sd"]
    if (
        not isinstance(gamma, (int, float))
        or isinstance(gamma, bool)
        or not np.isfinite(gamma)
        or gamma <= 0
    ):
        raise ValueError("positive finite Normal curvature prior scale required")
    prior = read_prior(
        root, "NCEI-native-duration", "wider" if variant == "joint_wider" else "base"
    )
    return {**prior, "gamma_sd": float(gamma)}


def run_curvature_prior(root: Path, output: Path, store: Path) -> None:
    if (
        output.exists()
        or store.exists()
        or not store.is_relative_to(root)
        or not output.is_relative_to(root)
    ):
        raise ValueError("new project-local output and store required")
    draws, seed = 2000, 26261108
    priors = {variant: read_curvature_prior(root, variant) for variant in VARIANTS}
    lanes, contract = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    selected = np.flatnonzero(lane.included)
    events = sorted({lane.event_ids[int(i)] for i in selected})
    event_index = np.array([events.index(lane.event_ids[int(i)]) for i in selected])
    grid = np.unique(np.r_[np.geomspace(50, 20000, 60), 20, 100, ANCHORS_KM, 1000.0])
    weights = scale_weights(grid)
    basis = curvature_basis(grid)
    code = [
        CONFIG,
        CONTRACT,
        "config/arrival-model-priors-v1.toml",
        "pyproject.toml",
        "uv.lock",
        "analysis/arrival/model_curvature.py",
        "analysis/arrival/model_curvature_prior.py",
        "analysis/arrival/model_scale.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/models.py",
        "analysis/arrival/model_validation_report.py",
        "analysis/arrival/evidence.py",
        "scripts/check_arrival_curvature_prior.py",
        "scripts/run_arrival_model_validation.py",
    ]
    pins = {p: sha256(root / p) for p in [*contract["inputs"], *code]}
    output.mkdir(parents=True)
    store.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "draws": draws,
            "seed": seed,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "variants": VARIANTS,
            "coupling": "common standard-Normal draws across prior variants",
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "primary_records": len(selected),
            "events": len(events),
        },
    )
    quantiles, curves, dictionary, metrics, saved = [], [], [], [], []
    for variant, prior in priors.items():
        rng = np.random.default_rng(seed)
        hyper = {k: rng.normal(size=draws) * prior[k + "_sd"] for k in ["alpha", "beta", "gamma"]}
        hyper["tau_event"] = np.abs(rng.normal(size=draws)) * prior["tau_sd"]
        hyper["sigma_anchor"] = np.abs(rng.normal(size=(draws, 3))) * prior["sigma_sd"]
        predicted = new_curvature_event_predictions(hyper, grid, seed=seed + 1)
        effects = rng.normal(size=(draws, len(events))) * hyper["tau_event"][:, None]
        mean = (
            hyper["alpha"][:, None]
            + hyper["beta"][:, None] * lane.x[selected]
            + hyper["gamma"][:, None] * curvature_basis(lane.distance_km[selected])
        )
        response = (
            mean
            + effects[:, event_index]
            + (hyper["sigma_anchor"] @ scale_weights(lane.distance_km[selected]).T)
            * rng.normal(size=(draws, len(selected)))
        )
        native = np.exp(response) * lane.reference_minutes[selected]
        conditional_median = (grid / VREF_KM_MIN) * np.exp(
            hyper["alpha"][:, None]
            + hyper["beta"][:, None] * np.log(grid / 1000)
            + hyper["gamma"][:, None] * basis
        )
        elasticity = 1 + hyper["beta"][:, None] - hyper["gamma"][:, None] * 500 / (grid + 500)
        modifier = np.exp(hyper["gamma"][:, None] * basis)
        scales = hyper["sigma_anchor"] @ weights.T
        if any(
            not np.isfinite(v).all()
            for v in [native, predicted, conditional_median, elasticity, modifier]
        ) or any((v <= 0).any() for v in [native, conditional_median, modifier]):
            raise ValueError("unrepresentable prior prediction; no clipping or redraw")
        data = xr.Dataset(
            {
                k: (("draw", "scale_anchor_km") if k == "sigma_anchor" else ("draw",), v)
                for k, v in hyper.items()
            },
            coords={"scale_anchor_km": list(ANCHORS_KM)},
        )
        tree = xr.DataTree.from_dict(
            {
                "prior": data,
                "prior_predictive": xr.Dataset(
                    {
                        "new_event_minutes": (("draw", "distance_km"), predicted),
                        "conditional_median_minutes": (("draw", "distance_km"), conditional_median),
                        "local_median_elasticity": (("draw", "distance_km"), elasticity),
                        "full_design_minutes": (("draw", "record"), native),
                        "event_effect": (("draw", "event"), effects),
                    },
                    coords={
                        "distance_km": grid,
                        "record": [lane.record_ids[int(i)] for i in selected],
                        "event": events,
                    },
                ),
            }
        )
        path = store / (variant + ".nc")
        tree.to_netcdf(path)
        if path.stat().st_size > 64 * 1024**2:
            raise ValueError("prior file exceeds reviewed64MiB ceiling")
        saved.append(
            {"variant": variant, "path": str(path.relative_to(root)), "sha256": sha256(path)}
        )
        for name, values in [("new_event", predicted), ("conditional_median", conditional_median)]:
            q = np.quantile(values, [0.05, 0.5, 0.95], axis=0)
            quantiles.extend(
                {
                    "variant": variant,
                    "quantity": name,
                    "distance_km": float(d),
                    "q05_minutes": q[0, j],
                    "q50_minutes": q[1, j],
                    "q95_minutes": q[2, j],
                }
                for j, d in enumerate(grid)
            )
        for name, values in [
            ("gamma_median_modifier", modifier),
            ("local_median_elasticity", elasticity),
            ("record_log_SD", scales),
        ]:
            q = np.quantile(values, [0.025, 0.5, 0.975], axis=0)
            curves.extend(
                {
                    "variant": variant,
                    "quantity": name,
                    "distance_km": float(d),
                    "q025": q[0, j],
                    "q50": q[1, j],
                    "q975": q[2, j],
                    "fraction_nonpositive": float(np.mean(values[:, j] <= 0)),
                }
                for j, d in enumerate(grid)
            )
        for name, key, family in [
            ("alpha", "alpha_sd", "Normal"),
            ("beta", "beta_sd", "Normal"),
            ("gamma", "gamma_sd", "Normal"),
            ("tau_event", "tau_sd", "HalfNormal"),
            *[(f"sigma_{int(d)}km", "sigma_sd", "HalfNormal") for d in ANCHORS_KM],
        ]:
            dictionary.append(
                {
                    "variant": variant,
                    "parameter": name,
                    "family": family,
                    "location": 0,
                    "prior_scale": prior[key],
                    "source": "analyst_hypothesis_after_EDA",
                }
            )
        metrics.append(
            {
                "variant": variant,
                "primary_records": len(selected),
                "events": len(events),
                "soft_ratio_extreme_fraction": float(
                    np.mean((np.exp(response) < 0.05) | (np.exp(response) > 20))
                ),
                "limiting_near_negative_median_elasticity_fraction": float(
                    np.mean(1 + hyper["beta"] - hyper["gamma"] < 0)
                ),
                "native_second_moment_finite": variant != "joint_wider",
                "max_saved_file_bytes": path.stat().st_size,
            }
        )
    if sum((root / r["path"]).stat().st_size for r in saved) > 192 * 1024**2:
        raise ValueError("prior store exceeds reviewed192MiB ceiling")
    for name, rows in [
        ("new-event-duration-prior-quantiles", quantiles),
        ("mean-curve-prior-quantiles", curves),
        ("parameter-prior-dictionary", dictionary),
        ("prior-diagnostics", metrics),
    ]:
        write_table(output / (name + ".csv"), rows)
    write_json(output / "saved-draws.json", {"files": saved})
    write_json(
        output / "metrics.json",
        {
            "variants": metrics,
            "posterior_fitted": False,
            "hard_support_nonfinite_failures": 0,
            "soft_scope": "diagnostic yardstick, no acceptance cutoff",
            "status": "computed_pending_prior_predictive_review",
        },
    )

    for relative, expected in pins.items():
        if sha256(root / relative) != expected:
            raise ValueError("prior input changed during generation; retain failed attempt")
