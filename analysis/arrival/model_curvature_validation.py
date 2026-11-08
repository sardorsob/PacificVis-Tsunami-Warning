"""Candidate-specific synthetic inference; original outcomes never enter its likelihood."""

# pyright: basic
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_curvature import (
    build_curvature_model,
    conditional_curvature_effects,
    simulate_curvature_response,
)
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_data import (
    CONTRACT,
    METADATA,
    SOURCE_MANIFEST,
    SPLIT,
    TARGET_FILES,
    load_lanes,
)
from analysis.arrival.model_validation import rank_summary, sampling_diagnostics

PRIOR_GATE = "artifacts/models/arrival-timing/mean-curvature-prior-report-v2/review-acceptance.json"
CONSUMED = [
    "analysis/arrival/model_curvature_validation.py",
    "scripts/fit_arrival_curvature_synthetic.py",
    "analysis/arrival/model_curvature.py",
    "analysis/arrival/model_curvature_prior.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/models.py",
    "analysis/arrival/evidence.py",
    "scripts/run_arrival_model_validation.py",
    "config/arrival-mean-curvature-v1.toml",
    "config/arrival-model-priors-v1.toml",
    "config/arrival-model-contract-v1.toml",
    "pyproject.toml",
    "uv.lock",
    PRIOR_GATE,
]


REQUIRED_PRIOR_FILES = {
    "analysis/arrival/model_curvature.py",
    "analysis/arrival/model_curvature_prior.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/models.py",
    "config/arrival-mean-curvature-v1.toml",
    "config/arrival-model-priors-v1.toml",
    CONTRACT,
    METADATA,
    SOURCE_MANIFEST,
    SPLIT,
    *TARGET_FILES.values(),
    "data/processed/models/mean-curvature-prior-v1/base.nc",
    *{
        f"artifacts/models/arrival-timing/mean-curvature-prior-report-v2/{name}"
        for name in [
            "inputs.json",
            "output-checksums.json",
            "saved-draws.json",
            "new-event-duration-prior-quantiles.csv",
            "mean-curve-prior-quantiles.csv",
            "parameter-prior-dictionary.csv",
            "prior-diagnostics.csv",
            "metrics.json",
        ]
    },
}


def verify_curvature_prior(root: Path) -> None:
    gate = json.loads((root / PRIOR_GATE).read_text())
    if (
        gate.get("status") != "accepted_for_synthetic_validation"
        or gate.get("model") != "mean-curvature"
        or not gate.get("independent_checker")
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("confirmation_outcomes_parsed") is not False
    ):
        raise ValueError("accepted candidate-specific prior gate required")
    proof = gate.get("files")
    if (
        not isinstance(proof, dict)
        or not REQUIRED_PRIOR_FILES.issubset(proof)
        or any(
            not isinstance(name, str)
            or not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected) is None
            for name, expected in proof.items()
        )
    ):
        raise ValueError("complete well-formed candidate prior proof required")
    for name, expected in proof.items():
        if sha256(checked_path(root, name)) != expected:
            raise ValueError("curvature prior gate input changed")


def curvature_quantities(dataset, effects, truth):
    quantities = {k: dataset[k].values for k in ["alpha", "beta", "gamma", "tau_event"]}
    truths = {k: truth[k] for k in quantities} if truth is not None else {}
    anchors = dataset["sigma_anchor"].values
    for j, d in enumerate([500, 2000, 5000]):
        quantities[f"sigma_{d}km"] = anchors[..., j]
        if truth is not None:
            truths[f"sigma_{d}km"] = truth["sigma_anchor"][j]
    quantities["sigma_1000km"] = (anchors[..., 0] + anchors[..., 1]) / 2
    first = str(dataset.coords["event"].values[0])
    quantities["event_effect_first"] = dataset["event_effect"].sel(event=first).values
    quantities["median_elasticity_1000km"] = 1 + quantities["beta"] - quantities["gamma"] / 3
    quantities["median_ratio_100km"] = np.exp(
        quantities["alpha"] + quantities["beta"] * np.log(0.1) + quantities["gamma"] * np.log(4)
    )
    quantities["predictive_log_SD_1000km"] = np.sqrt(
        quantities["tau_event"] ** 2 + quantities["sigma_1000km"] ** 2
    )
    if truth is not None:
        s1000 = sum(truth["sigma_anchor"][:2]) / 2
        truths.update(
            {
                "sigma_1000km": s1000,
                "event_effect_first": effects[first],
                "median_elasticity_1000km": 1 + truth["beta"] - truth["gamma"] / 3,
                "median_ratio_100km": float(
                    np.exp(
                        truth["alpha"] + truth["beta"] * np.log(0.1) + truth["gamma"] * np.log(4)
                    )
                ),
                "predictive_log_SD_1000km": float(np.hypot(truth["tau_event"], s1000)),
            }
        )
    if any(not np.isfinite(value).all() for value in quantities.values()):
        raise ValueError("nonfinite scalar diagnostic quantity")
    return quantities, truths


def prior_reference_sds(root: Path) -> dict[str, float]:
    tree = xr.open_datatree(root / "data/processed/models/mean-curvature-prior-v1/base.nc")
    try:
        dataset = tree["prior"].to_dataset()
        dataset["event_effect"] = tree["prior_predictive"]["event_effect"]
        values, _ = curvature_quantities(dataset, None, None)
        references = {k: float(np.std(v, ddof=1)) for k, v in values.items()}
        if any(not np.isfinite(v) or v <= 0 for v in references.values()):
            raise ValueError("finite nonzero ancestral prior SD references required")
        return references
    finally:
        tree.close()


def prepare_curvature_synthetic(lane, truth, *, seed):
    simulated, effects = simulate_curvature_response(lane, truth, seed=seed)
    native = np.exp(simulated) * lane.reference_minutes
    if not np.isfinite(native).all() or (native <= 0).any():
        raise ValueError("unrepresentable synthetic native response")
    return replace(lane, response=simulated, y=native), effects


def fit_curvature_synthetic_job(root: Path, job: dict[str, Any], output: Path, store: Path) -> None:
    augmented = store.with_name(store.stem + "-augmented.nc")
    if (
        output.exists()
        or store.exists()
        or augmented.exists()
        or not output.resolve().is_relative_to(root.resolve())
        or not store.resolve().is_relative_to(root.resolve())
        or job.get("model") != "mean-curvature"
        or job.get("target") != "NCEI-native-duration"
        or job.get("phase") not in {"pilot", "recovery", "sbc"}
        or any(type(job.get(k)) is not int or not 100 <= job[k] <= 4000 for k in ["draws", "tune"])
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 40
        or type(job.get("cores")) is not int
        or not 1 <= job["cores"] <= 2
    ):
        raise ValueError("new project paths and bounded synthetic curvature job required")
    verify_curvature_prior(root)
    pins = {p: sha256(root / p) for p in CONSUMED}
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    prior = read_curvature_prior(root, "base")
    first_event = min(lane.event_ids[int(i)] for i in np.flatnonzero(lane.included))
    if job.get("first_event_id") != first_event:
        raise ValueError("predeclared metadata-first event identity mismatch")
    seed = job["seed"]
    rng = np.random.default_rng(seed)
    truth = (
        {
            **{k: float(rng.normal() * prior[k + "_sd"]) for k in ["alpha", "beta", "gamma"]},
            "tau_event": float(abs(rng.normal()) * prior["tau_sd"]),
            "sigma_anchor": (np.abs(rng.normal(size=3)) * prior["sigma_sd"]).tolist(),
        }
        if job["phase"] == "sbc"
        else job["truth"]
    )
    fake, effects = prepare_curvature_synthetic(lane, truth, seed=seed + 1)
    simulated, native = fake.response, fake.y
    selected = np.flatnonzero(fake.included)
    model = build_curvature_model(fake, prior, indices=selected)
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(output / "inputs.json", {"code_and_config": pins, "frozen_data": frozen["inputs"]})
    started = time.monotonic()

    def finish(diagnostics, estimates, truths):
        verify_curvature_prior(root)
        if any(sha256(root / p) != expected for p, expected in pins.items()):
            raise ValueError("synthetic worker source changed during run")
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
                "prior_sd_reference": "2000 accepted base ancestral draws; finite Monte Carlo SD",
                "rank_subsampling_note": "100 spaced draws are not ESS; full chains retained",
            },
        )

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
    if "nutpie" not in str(posterior.attrs).lower():
        raise ValueError("unexplained synthetic sampler backend change")
    sampled_diagnostics, sampled_table = sampling_diagnostics(tree)
    sampled_table.to_csv(output / "sampled-hyperparameter-diagnostics.csv", na_rep="unknown")
    if not sampled_diagnostics["screen_passed"]:
        finish(sampled_diagnostics, [], {})
        return
    hyper = {
        k: posterior[k].values for k in ["alpha", "beta", "gamma", "tau_event", "sigma_anchor"]
    }
    u, events = conditional_curvature_effects(fake, hyper, indices=selected, seed=seed + 3)
    posterior["event_effect"] = xr.DataArray(
        u,
        dims=("chain", "draw", "event"),
        coords={"event": events},
        attrs={"draw_method": "exact_conditional_weighted_Normal"},
    )
    tree["observed_data"] = xr.DataTree(
        xr.Dataset(
            {
                "response": (("record",), simulated[selected]),
                "native_minutes": (("record",), native[selected]),
            },
            coords={"record": [fake.record_ids[int(i)] for i in selected]},
        )
    )
    with augmented.open("xb"):
        pass  # reserve without overwriting an unexpectedly appearing partial
    tree.to_netcdf(augmented)
    os.replace(augmented, store)
    if "nutpie" not in str(posterior.attrs).lower():
        raise ValueError("unexplained synthetic sampler backend change")
    diagnostics, table = sampling_diagnostics(tree)
    diagnostics["sampled_hyperparameters"] = sampled_diagnostics
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    quantities, truths = curvature_quantities(posterior, effects, truth)
    prior_sds = prior_reference_sds(root)
    estimates = []
    for j, (name, values) in enumerate(quantities.items()):
        q05, median, q95 = np.quantile(values, [0.05, 0.5, 0.95])
        sd = float(values.std(ddof=1))
        boundary = name == "tau_event" and truths[name] == 0
        estimates.append(
            {
                "parameter": name,
                "truth": truths[name],
                "mean": float(values.mean()),
                "median": float(median),
                "q05": float(q05),
                "q95": float(q95),
                "covered90": None if boundary else bool(q05 <= truths[name] <= q95),
                "zero_variance_boundary": boundary,
                "posterior_sd": sd,
                "recovery_z": float((values.mean() - truths[name]) / sd) if sd > 0 else None,
                "prior_reference_sd": prior_sds[name],
                "posterior_prior_sd_ratio": sd / prior_sds[name],
                **rank_summary(values, truths[name], seed + 10 + j),
                "full_draws": values.size,
            }
        )
    if job["phase"] == "sbc":
        diagnostics["rank_ready"] = all(r["rank_ready"] for r in estimates)
        diagnostics["screen_passed"] &= diagnostics["rank_ready"]
    finish(diagnostics, estimates, truths)
