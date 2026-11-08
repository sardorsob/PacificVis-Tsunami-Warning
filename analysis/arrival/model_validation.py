"""Known-truth simulation and computational diagnostics before scientific posterior fits."""

# pyright: basic
from __future__ import annotations

import json
import math
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import arviz_stats as azs
import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_data import Lane, load_lanes
from analysis.arrival.models import PRIORS, build_model, read_prior


def simulate_response(
    lane: Lane,
    truth: dict[str, float],
    *,
    seed: int,
    additive_minutes: float = 0,
) -> tuple[np.ndarray, dict[str, float]]:
    """Condition on observed design, independently implementing the generative equations."""
    if not all(math.isfinite(value) for value in truth.values()):
        raise ValueError("nonfinite simulation truth")
    if truth["tau_event"] < 0 or truth["sigma"] < 0:
        raise ValueError("negative simulation scale")
    if not math.isfinite(additive_minutes) or additive_minutes < 0:
        raise ValueError("invalid additive-duration scenario")
    rng = np.random.default_rng(seed)
    effects = {
        event: float(rng.normal() * truth["tau_event"]) for event in sorted(set(lane.event_ids))
    }
    response = (
        truth["alpha"]
        + truth["beta"] * lane.x
        + np.array([effects[e] for e in lane.event_ids])
        + rng.normal(size=len(lane.rows)) * truth["sigma"]
    )
    if additive_minutes:
        if lane.target == "T-CAL" or additive_minutes < 0:
            raise ValueError("additive-delay scenario requires positive-duration target")
        response = np.log(np.exp(response) * lane.reference_minutes + additive_minutes)
        response -= np.log(lane.reference_minutes)
    if not np.isfinite(response).all():
        raise ValueError("unrepresentable simulated responses")
    return response, effects


def sampling_diagnostics(tree: xr.DataTree) -> tuple[dict[str, Any], Any]:
    """Screen all fitted coordinates, preserving nonfinite and missing diagnostics as failures."""
    table = cast(Any, azs).summary(tree, ci_prob=0.9, ci_kind="eti", round_to="none")
    stats = cast(Any, tree["sample_stats"])
    energy = stats["energy"].values
    bfmi = np.mean(np.diff(energy, axis=1) ** 2, axis=1) / np.var(energy, axis=1)
    values = table[["r_hat", "ess_bulk", "ess_tail", "mcse_mean"]].to_numpy()
    finite = bool(np.isfinite(values).all() and np.isfinite(bfmi).all())
    diagnostics = {
        "finite_diagnostics": finite,
        "max_rhat": float(table.r_hat.max()) if finite else None,
        "min_ess_bulk": float(table.ess_bulk.min()) if finite else None,
        "min_ess_tail": float(table.ess_tail.min()) if finite else None,
        "min_bfmi": float(bfmi.min()) if finite else None,
        "divergences": int(stats["diverging"].values.sum()),
        "maxdepth_reached": int(stats["maxdepth_reached"].values.sum()),
        "max_mcse_mean": float(table.mcse_mean.max()) if finite else None,
    }
    diagnostics["screen_passed"] = bool(
        finite
        and diagnostics["max_rhat"] <= 1.01
        and diagnostics["min_ess_bulk"] >= 400
        and diagnostics["min_ess_tail"] >= 400
        and diagnostics["min_bfmi"] >= 0.3
        and diagnostics["divergences"] == 0
        and diagnostics["maxdepth_reached"] == 0
    )
    return diagnostics, table


def conditional_event_effects(
    lane: Lane,
    hyper: dict[str, np.ndarray],
    *,
    seed: int,
    indices: np.ndarray,
) -> tuple[np.ndarray, list[str]]:
    """Draw exact u|hyperparameters,y after integrating Normal event effects in sampling."""
    selected = indices
    if (
        selected.ndim != 1
        or not np.issubdtype(selected.dtype, np.integer)
        or not len(selected)
        or len(set(selected.tolist())) != len(selected)
        or (selected < 0).any()
        or (selected >= len(lane.rows)).any()
    ):
        raise ValueError("invalid explicit training subset for conditional effects")
    if not lane.included[selected].all():
        raise ValueError("conditional effects require approved training evidence units")
    if set(hyper) != {"alpha", "beta", "sigma", "tau_event"}:
        raise ValueError("conditional effects require four scalar hyperparameters")
    shape = hyper["alpha"].shape
    if len(shape) != 2 or any(value.shape != shape for value in hyper.values()):
        raise ValueError("hyperparameters require common (chain,draw) shape")
    if any(not np.isfinite(value).all() for value in hyper.values()):
        raise ValueError("nonfinite hyperparameter draws")
    if (hyper["sigma"] <= 0).any() or (hyper["tau_event"] < 0).any():
        raise ValueError("invalid conditional Normal scales")
    events = sorted({lane.event_ids[int(i)] for i in selected})
    counts = np.array([sum(lane.event_ids[int(i)] == e for i in selected) for e in events])
    xbar = np.array(
        [np.mean([lane.x[int(i)] for i in selected if lane.event_ids[int(i)] == e]) for e in events]
    )
    ybar = np.array(
        [
            np.mean([lane.response[int(i)] for i in selected if lane.event_ids[int(i)] == e])
            for e in events
        ]
    )
    sigma2 = hyper["sigma"][..., None] ** 2
    tau2 = hyper["tau_event"][..., None] ** 2
    variance = tau2 * sigma2 / (sigma2 + counts * tau2)
    mean = (
        counts
        * tau2
        / (sigma2 + counts * tau2)
        * (ybar - hyper["alpha"][..., None] - hyper["beta"][..., None] * xbar)
    )
    rng = np.random.default_rng(seed)
    return mean + np.sqrt(variance) * rng.normal(size=mean.shape), events


def rank_summary(values: np.ndarray, truth: float, seed: int) -> dict[str, Any]:
    """Keep original ESS separate from approximately independent, spaced SBC rank draws."""
    locations = np.linspace(0, values.shape[1] - 1, 25, dtype=int)
    subset = values[:, locations].reshape(-1)
    rank = int(np.sum(subset < truth))
    lag = int(np.min(np.diff(locations)))
    centered = values - values.mean(axis=1, keepdims=True)
    variance = np.var(values, axis=1)
    if lag <= 0 or (variance <= 0).any():
        raise ValueError("insufficient nonconstant posterior draws for rank diagnostics")
    correlation = np.mean(centered[:, lag:] * centered[:, :-lag], axis=1) / variance
    rhat = float(cast(Any, azs).rhat(values))
    bulk = float(cast(Any, azs).ess(values, method="bulk"))
    tail = float(cast(Any, azs).ess(values, method="tail", prob=(0.05, 0.95)))
    finite = bool(np.isfinite([rhat, bulk, tail, *correlation]).all())
    return {
        "rank": rank,
        "rank_draws": len(subset),
        "rank_stride": lag,
        "randomized_rank_pit": float(
            (rank + np.random.default_rng(seed).uniform()) / (len(subset) + 1)
        ),
        "quantity_rhat": rhat if finite else None,
        "quantity_ess_bulk": bulk if finite else None,
        "quantity_ess_tail": tail if finite else None,
        "max_abs_rank_lag_correlation": float(np.max(np.abs(correlation))) if finite else None,
        "rank_ready": bool(
            finite
            and rhat <= 1.01
            and bulk >= 1000
            and tail >= 1000
            and np.max(np.abs(correlation)) <= 0.2
        ),
        "rank_caveat": "spaced MCMC ranks approximate iid ranks; thresholds are diagnostics",
    }


def fit_synthetic_job(root: Path, job: dict[str, Any], output: Path, store: Path) -> None:
    """Save one synthetic fit before diagnostics; actual reported responses are never fitted."""
    if output.exists() or store.exists():
        raise ValueError("retain previous attempts; require new job output/store")
    if job["phase"] not in {"pilot", "recovery", "sbc"}:
        raise ValueError("unknown computational validation phase")
    if any(type(job[key]) is not int or not 100 <= job[key] <= 4000 for key in ["draws", "tune"]):
        raise ValueError("fit allocation requires integer draws/tune in 100..4000")
    if type(job["seed"]) is not int or not 0 <= job["seed"] <= 2**32 - 10:
        raise ValueError("invalid simulation seed allocation")
    cores = job.get("cores", 4)
    if type(cores) is not int or not 1 <= cores <= 4:
        raise ValueError("sampler cores must be an integer in 1..4")
    if not store.resolve().is_relative_to(root.resolve()):
        raise ValueError("posterior store must be inside the project")
    approved = json.loads(
        (root / "artifacts/models/arrival-timing/prior-checks-v1/inputs.json").read_text(
            encoding="utf-8"
        )
    )["files"]
    # Centering is a tested change of coordinates with identical priors, not a new prior family.
    for name in [PRIORS]:
        if sha256(root / name) != approved[name]:
            raise ValueError("approved base priors changed; repeat relevant review")
    lanes, _ = load_lanes(root)
    lane = lanes[job["target"]]
    prior = read_prior(root, lane.target, "base")
    seed = int(job["seed"])
    rng = np.random.default_rng(seed)
    if job["phase"] == "sbc":
        truth = {
            "alpha": float(rng.normal() * prior["alpha_sd"]),
            "beta": float(rng.normal() * prior["beta_sd"]),
            "tau_event": float(abs(rng.normal()) * prior["tau_sd"]),
            "sigma": float(abs(rng.normal()) * prior["sigma_sd"]),
        }
    else:
        truth = {key: float(value) for key, value in job["truth"].items()}
    simulated, effects = simulate_response(
        lane, truth, seed=seed + 1, additive_minutes=job.get("additive_minutes", 0)
    )
    # Private simulation arrays never overwrite or export original source observations.
    native = simulated if lane.target == "T-CAL" else np.exp(simulated) * lane.reference_minutes
    fake = replace(lane, response=simulated, y=native)
    model = build_model(fake, prior, parameterization=job.get("parameterization", "noncentered"))
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    consumed = [
        "analysis/arrival/model_validation.py",
        "analysis/arrival/models.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/evidence.py",
        PRIORS,
        "config/arrival-model-contract-v1.toml",
        "pyproject.toml",
        "uv.lock",
        "scripts/run_arrival_model_validation.py",
    ]
    source_pins = {p: sha256(root / p) for p in consumed}
    write_json(
        output / "inputs.json",
        {
            "code_and_config": source_pins,
            "frozen_data": json.loads(
                (
                    root / "artifacts/models/arrival-timing/exploration-contract-v1/inputs.json"
                ).read_text(encoding="utf-8")
            )["files"],
            "git_dirty_paths": subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True
            ).splitlines(),
        },
    )
    started = time.monotonic()
    with model:
        fitted = pm.sample(
            draws=job["draws"],
            tune=job["tune"],
            chains=4,
            cores=cores,
            target_accept=0.95,
            random_seed=seed + 2,
            progressbar=False,
        )
    fitted.to_netcdf(store)
    if job.get("parameterization") == "marginal":
        hyper = {
            key: cast(Any, fitted["posterior"])[key].values
            for key in ["alpha", "beta", "tau_event", "sigma"]
        }
        effects_draws, events = conditional_event_effects(
            fake, hyper, seed=seed + 3, indices=np.flatnonzero(fake.included)
        )
        fitted["posterior"]["event_effect"] = xr.DataArray(
            effects_draws,
            dims=("chain", "draw", "event"),
            coords={"event": events},
            attrs={
                "draw_method": "exact_conditional_Normal_u_given_hyperparameters_and_training_y"
            },
        )
        selected = np.flatnonzero(fake.included)
        fitted["observed_data"] = xr.DataTree(
            xr.Dataset(
                {
                    "response": (("record",), fake.response[selected]),
                },
                coords={"record": [fake.record_ids[int(i)] for i in selected]},
            )
        )
        fitted.to_netcdf(store, mode="w")
    elapsed = time.monotonic() - started
    if "nutpie" not in str(fitted["posterior"].attrs).lower():
        raise ValueError("unexplained sampling backend change")
    diagnostics, table = sampling_diagnostics(fitted)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    posterior = cast(Any, fitted["posterior"])
    estimates: list[dict[str, Any]] = []
    quantities = {key: posterior[key].values for key in truth}
    event_coords = model.coords["event"]
    if not event_coords:
        raise ValueError("missing fitted event coordinates")
    first = str(event_coords[0])
    quantities["event_effect_first"] = posterior["event_effect"].sel(event=first).values
    truth["event_effect_first"] = effects[first]
    quantities["mean_response_at_5000km"] = quantities["alpha"] + quantities["beta"] * math.log(5)
    truth["mean_response_at_5000km"] = truth["alpha"] + truth["beta"] * math.log(5)
    for number, (name, values) in enumerate(quantities.items()):
        q05, median, q95 = np.quantile(values, [0.05, 0.5, 0.95])
        estimates.append(
            {
                "parameter": name,
                "truth": truth[name],
                "mean": float(values.mean()),
                "median": float(median),
                "q05": float(q05),
                "q95": float(q95),
                "covered90": None
                if name == "tau_event" and truth[name] == 0
                else bool(q05 <= truth[name] <= q95),
                "zero_variance_boundary": bool(name == "tau_event" and truth[name] == 0),
                **rank_summary(values, truth[name], seed + 10 + number),
                "full_draws": values.size,
            }
        )
    if job["phase"] == "sbc":
        diagnostics["rank_ready"] = all(row["rank_ready"] for row in estimates)
        diagnostics["screen_passed"] &= diagnostics["rank_ready"]
    if any(sha256(root / p) != digest for p, digest in source_pins.items()):
        raise ValueError("source changed during fit; retain attempt without promotion")
    write_json(
        output / "result.json",
        {
            "job": job,
            "truth": truth,
            "estimates": estimates,
            "diagnostics": diagnostics,
            "elapsed_seconds": elapsed,
            "posterior": str(store.relative_to(root)),
            "posterior_sha256": sha256(store),
            "synthetic_only": True,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "code_and_config": source_pins,
            "rank_subsampling_note": "100 spaced draws are not ESS; full chains retained",
        },
    )
