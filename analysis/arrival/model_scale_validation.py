"""Candidate-specific synthetic calibration; original responses never enter the likelihood."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_scale import (
    build_scale_model,
    conditional_scale_effects,
    simulate_scale_response,
)
from analysis.arrival.model_validation import rank_summary, sampling_diagnostics
from analysis.arrival.models import read_prior

PRIOR_GATE = "artifacts/models/arrival-timing/distance-scale-prior-v1/review-acceptance.json"


def verify_scale_prior(root: Path) -> None:
    gate = json.loads((root / PRIOR_GATE).read_text())
    if (
        gate.get("status") != "accepted_for_synthetic_validation"
        or gate.get("model") != "distance-scale"
        or not gate.get("independent_checker")
        or gate.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("accepted candidate-specific prior check required")
    for p, digest in gate["files"].items():
        if sha256(checked_path(root, p)) != digest:
            raise ValueError("candidate prior gate identity changed")


def scale_quantities(posterior: Any, effects: dict[str, float], truth: dict[str, Any]):
    """Eight prespecified ranks, including metadata-preselected first event and 1000km SD."""
    quantities = {k: posterior[k].values for k in ["alpha", "beta", "tau_event"]}
    truths = {k: truth[k] for k in quantities}
    anchors = posterior["sigma_anchor"].values
    for j, distance in enumerate([500, 2000, 5000]):
        quantities[f"sigma_{distance}km"] = anchors[..., j]
        truths[f"sigma_{distance}km"] = truth["sigma_anchor"][j]
    quantities["sigma_1000km"] = (anchors[..., 0] + anchors[..., 1]) / 2
    truths["sigma_1000km"] = sum(truth["sigma_anchor"][:2]) / 2
    first = str(posterior.coords["event"].values[0])
    quantities["event_effect_first"] = posterior["event_effect"].sel(event=first).values
    truths["event_effect_first"] = effects[first]
    return quantities, truths


def fit_scale_synthetic_job(root: Path, job: dict[str, Any], output: Path, store: Path) -> None:
    from scripts.run_arrival_model_batch import consumed_for

    if (
        output.exists()
        or store.exists()
        or not store.resolve().is_relative_to(root.resolve())
        or job.get("model") != "distance-scale"
        or job.get("target") != "NCEI-native-duration"
        or job.get("phase") not in {"pilot", "recovery", "sbc"}
        or any(type(job[k]) is not int or not 100 <= job[k] <= 4000 for k in ["draws", "tune"])
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 20
        or type(job.get("cores")) is not int
        or not 1 <= job["cores"] <= 2
    ):
        raise ValueError("new paths and bounded primary-source synthetic job required")
    verify_scale_prior(root)
    pins = {p: sha256(root / p) for p in consumed_for("distance-scale")[1:]}
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    prior = read_prior(root, lane.target, "base")
    seed = job["seed"]
    rng = np.random.default_rng(seed)
    truth = (
        {
            "alpha": float(rng.normal() * prior["alpha_sd"]),
            "beta": float(rng.normal() * prior["beta_sd"]),
            "tau_event": float(abs(rng.normal()) * prior["tau_sd"]),
            "sigma_anchor": (np.abs(rng.normal(size=3)) * prior["sigma_sd"]).tolist(),
        }
        if job["phase"] == "sbc"
        else job["truth"]
    )
    simulated, effects = simulate_scale_response(lane, truth, seed=seed + 1)
    native = np.exp(simulated) * lane.reference_minutes
    if not np.isfinite(native).all() or (native <= 0).any():
        raise ValueError("unrepresentable synthetic native responses")
    fake = replace(lane, response=simulated, y=native)
    selected = np.flatnonzero(fake.included)
    model = build_scale_model(fake, prior, indices=selected)
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(output / "inputs.json", {"code_and_config": pins, "frozen_data": frozen["inputs"]})
    started = time.monotonic()
    with model:
        tree = pm.sample(
            draws=job["draws"],
            tune=job["tune"],
            chains=4,
            cores=job["cores"],
            target_accept=0.95,
            random_seed=seed + 2,
            progressbar=False,
        )
    tree.to_netcdf(store)
    posterior = cast(Any, tree["posterior"])
    hyper = {k: posterior[k].values for k in ["alpha", "beta", "tau_event", "sigma_anchor"]}
    u, events = conditional_scale_effects(fake, hyper, indices=selected, seed=seed + 3)
    posterior["event_effect"] = xr.DataArray(
        u,
        dims=("chain", "draw", "event"),
        coords={"event": events},
        attrs={"draw_method": "exact_conditional_weighted_Normal"},
    )
    tree["observed_data"] = xr.DataTree(
        xr.Dataset(
            {"response": (("record",), simulated[selected])},
            coords={"record": [fake.record_ids[int(i)] for i in selected]},
        )
    )
    tree.to_netcdf(store, mode="w")
    if "nutpie" not in str(posterior.attrs).lower():
        raise ValueError("unexplained backend change")
    diagnostics, table = sampling_diagnostics(tree)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    quantities, truths = scale_quantities(posterior, effects, truth)
    estimates = []
    for j, (name, values) in enumerate(quantities.items()):
        q05, median, q95 = np.quantile(values, [0.05, 0.5, 0.95])
        estimates.append(
            {
                "parameter": name,
                "truth": truths[name],
                "mean": float(values.mean()),
                "median": float(median),
                "q05": float(q05),
                "q95": float(q95),
                "covered90": bool(q05 <= truths[name] <= q95),
                "zero_variance_boundary": False,
                **rank_summary(values, truths[name], seed + 10 + j),
                "full_draws": values.size,
            }
        )
    if job["phase"] == "sbc":
        diagnostics["rank_ready"] = all(e["rank_ready"] for e in estimates)
        diagnostics["screen_passed"] &= diagnostics["rank_ready"]
    verify_scale_prior(root)
    if any(sha256(root / p) != digest for p, digest in pins.items()):
        raise ValueError("source changed during candidate fit")
    write_json(
        output / "result.json",
        {
            "job": job,
            "truth": truth,
            "scalar_truths": truths,
            "estimates": estimates,
            "diagnostics": diagnostics,
            "elapsed_seconds": time.monotonic() - started,
            "posterior": str(store.relative_to(root)),
            "posterior_sha256": sha256(store),
            "synthetic_only": True,
            "code_and_config": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "rank_subsampling_note": "100 spaced draws are not ESS; full chains retained",
        },
    )
