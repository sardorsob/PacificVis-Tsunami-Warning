"""Source-specific exploration fits, gated on accepted computational validation."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json, write_rows
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_validation import conditional_event_effects, sampling_diagnostics
from analysis.arrival.model_validation_report import csv_rows
from analysis.arrival.models import build_model, read_prior

CONSUMED = [
    "scripts/fit_arrival_model.py",
    "analysis/arrival/model_fit.py",
    "analysis/arrival/models.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/model_validation_report.py",
    "analysis/arrival/evidence.py",
    "config/arrival-model-contract-v1.toml",
    "config/arrival-model-priors-v1.toml",
    "pyproject.toml",
    "uv.lock",
]


def validate_fit_job(job: dict[str, Any]) -> None:
    if job["target"] not in {"NCEI-native-duration", "T-OBS", "T-CAL"}:
        raise ValueError("source-specific target required")
    if job["kind"] not in {"pooled", "distance", "event"}:
        raise ValueError("unknown scaffold")
    if any(type(job[key]) is not int or not 1000 <= job[key] <= 4000 for key in ["draws", "tune"]):
        raise ValueError("bounded draws/tune in 1000..4000 required")
    if type(job["cores"]) is not int or not 1 <= job["cores"] <= 2:
        raise ValueError("at most two sampler cores")
    if type(job["seed"]) is not int or not 0 <= job["seed"] <= 2**32 - 10:
        raise ValueError("invalid sampler seed")


def verify_computational_gate(root: Path, receipt: Path, target: str) -> None:
    """A human-reviewed stage receipt pins the accepted reports and model definition."""
    gate = json.loads(receipt.read_text())
    if (
        gate.get("schema_version") != "arrival_ms2_acceptance_v1"
        or gate.get("status") != "accepted"
        or target not in gate.get("targets", [])
        or not gate.get("independent_checker")
        or gate.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("accepted source-specific computational gate required")
    required = {
        "analysis/arrival/models.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/model_validation.py",
        "config/arrival-model-priors-v1.toml",
        "config/arrival-model-contract-v1.toml",
        "pyproject.toml",
        "uv.lock",
    }
    if not required <= set(gate["files"]):
        raise ValueError("gate lacks model/config identities")
    for path, digest in gate["files"].items():
        if sha256(checked_path(root, path)) != digest:
            raise ValueError("computational gate identity changed")


def conditional_replicates(
    hyper: dict[str, np.ndarray],
    effects: np.ndarray,
    event_index: np.ndarray,
    x: np.ndarray,
    reference: np.ndarray,
    *,
    target: str,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Replicate reports conditional on fitted events; these are in-sample PPCs."""
    rng = np.random.default_rng(seed)
    response = (
        hyper["alpha"][:, None]
        + hyper["beta"][:, None] * x
        + effects[:, event_index]
        + hyper["sigma"][:, None] * rng.normal(size=(len(hyper["alpha"]), len(x)))
    )
    if target not in {"NCEI-native-duration", "T-OBS", "T-CAL"}:
        raise ValueError("unknown reported target")
    native = response if target == "T-CAL" else np.exp(response) * reference
    if not np.isfinite(native).all() or (target != "T-CAL" and (native <= 0).any()):
        raise ValueError("nonfinite predictive replicate")
    return response, native


def fit_exploration_job(
    root: Path, job: dict[str, Any], gate: Path, output: Path, store: Path
) -> None:
    validate_fit_job(job)
    verify_computational_gate(root, gate, job["target"])
    if output.exists() or store.exists() or not store.resolve().is_relative_to(root.resolve()):
        raise ValueError("new output and project-local posterior store required")
    pins = {p: sha256(root / p) for p in CONSUMED}
    pins[str(gate.relative_to(root))] = sha256(gate)
    lanes, source_pins = load_lanes(root)
    lane = lanes[job["target"]]
    selected = np.flatnonzero(lane.included)
    events = sorted({lane.event_ids[int(i)] for i in selected})
    event_index = np.array([events.index(lane.event_ids[int(i)]) for i in selected])
    model = build_model(
        lane,
        read_prior(root, lane.target, "base"),
        kind=job["kind"],
        indices=selected,
        parameterization="marginal",
    )
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "code_and_config": pins,
            "source_files": source_pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    )
    with model:
        tree = pm.sample(
            draws=job["draws"],
            tune=job["tune"],
            chains=4,
            cores=job["cores"],
            target_accept=0.95,
            random_seed=job["seed"],
            progressbar=False,
        )
    tree.to_netcdf(store)
    posterior = cast(Any, tree["posterior"])
    if job["kind"] == "event":
        hyper = {key: posterior[key].values for key in ["alpha", "beta", "tau_event", "sigma"]}
        effects, _ = conditional_event_effects(lane, hyper, seed=job["seed"] + 1, indices=selected)
        tree["posterior"]["event_effect"] = xr.DataArray(
            effects, dims=("chain", "draw", "event"), coords={"event": events}
        )
        tree["observed_data"] = xr.DataTree(
            xr.Dataset(
                {"response": (("record",), lane.response[selected])},
                coords={"record": [lane.record_ids[int(i)] for i in selected]},
            )
        )
        tree.to_netcdf(store, mode="w")
    diagnostics, table = sampling_diagnostics(tree)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    write_json(output / "diagnostics.json", diagnostics)
    if not diagnostics["screen_passed"]:
        write_json(
            output / "result.json",
            {
                "job": job,
                "status": "diagnostic_failure",
                "diagnostics": diagnostics,
                "posterior": str(store.relative_to(root)),
                "posterior_sha256": sha256(store),
            },
        )
        return
    posterior = cast(Any, tree["posterior"])
    samples = job["draws"] * 4
    locations = np.linspace(0, samples - 1, 800, dtype=int)
    hyper = {
        p: posterior[p].values.reshape(-1)[locations] if p in posterior else np.zeros(800)
        for p in ["alpha", "beta", "sigma"]
    }
    effects = (
        posterior["event_effect"].values.reshape(samples, len(events))[locations]
        if job["kind"] == "event"
        else np.zeros((800, len(events)))
    )
    response, native = conditional_replicates(
        hyper,
        effects,
        event_index,
        lane.x[selected],
        lane.reference_minutes[selected],
        target=lane.target,
        seed=job["seed"] + 2,
    )
    rows = []
    distance = lane.distance_km[selected]
    for label, mask in [
        ("all", np.ones(len(selected), dtype=bool)),
        ("under-500km", distance < 500),
        ("500-to-2000km", (distance >= 500) & (distance < 2000)),
        ("2000-to-5000km", (distance >= 2000) & (distance < 5000)),
        ("5000km-and-above", distance >= 5000),
    ]:
        if not mask.any():
            continue
        for name, observed, replicates in [
            ("modeled-response", lane.response[selected], response),
            ("native-minutes", lane.y[selected], native),
        ]:
            for q in [0.05, 0.5, 0.95]:
                draws = np.quantile(replicates[:, mask], q, axis=1)
                lower, median, upper = np.quantile(draws, [0.05, 0.5, 0.95])
                rows.append(
                    {
                        "stratum": label,
                        "scale": name,
                        "quantile": q,
                        "records": int(mask.sum()),
                        "observed": float(np.quantile(observed[mask], q)),
                        "replicated_q05": float(lower),
                        "replicated_q50": float(median),
                        "replicated_q95": float(upper),
                    }
                )
    write_rows(output / "conditional-predictive-quantiles-by-distance.csv", csv_rows(rows))
    quantiles = np.quantile(native, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    write_rows(
        output / "in-sample-record-predictions.csv",
        csv_rows(
            [
                {
                    "record_id": lane.record_ids[int(i)],
                    "event_id": lane.event_ids[int(i)],
                    "distance_km": lane.distance_km[int(i)],
                    "observed_minutes": lane.y[int(i)],
                    **{
                        f"q{q:02d}_minutes": float(quantiles[k, j])
                        for k, q in enumerate([5, 25, 50, 75, 95])
                    },
                }
                for j, i in enumerate(selected)
            ]
        ),
    )
    derived = {"alpha": posterior["alpha"].values, "sigma": posterior["sigma"].values}
    if "beta" in posterior:
        derived["beta"] = posterior["beta"].values
        if lane.target != "T-CAL":
            derived["distance_exponent"] = 1 + derived["beta"]
    if lane.target != "T-CAL":
        derived["median_reference_ratio_1000km"] = np.exp(derived["alpha"])
    if "tau_event" in posterior:
        derived["tau_event"] = posterior["tau_event"].values
    write_rows(
        output / "population-parameter-quantiles.csv",
        csv_rows(
            [
                {
                    "parameter": key,
                    "q05": float(np.quantile(value, 0.05)),
                    "q50": float(np.quantile(value, 0.5)),
                    "q95": float(np.quantile(value, 0.95)),
                    "mcse_note": "see chain diagnostics for base quantities",
                }
                for key, value in derived.items()
            ]
        ),
    )
    if any(sha256(root / p) != digest for p, digest in pins.items()):
        raise ValueError("consumed source changed during fit; do not promote")
    write_json(
        output / "result.json",
        {
            "job": job,
            "status": "computed_pending_scientific_review",
            "diagnostics": diagnostics,
            "posterior": str(store.relative_to(root)),
            "posterior_sha256": sha256(store),
            "ppc": "conditional_fitted_events_not_held_out",
            "predictive_replicates": 800,
            "records": len(selected),
            "events": len(events),
            "target_population": "eligible_reported_archive_records",
            "reserved_outcomes": "sealed",
        },
    )
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
