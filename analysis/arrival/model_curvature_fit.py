"""Conditional replication for the mean-curvature exploration candidate."""

# pyright: basic
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_curvature import (
    build_curvature_model,
    conditional_curvature_effects,
    curvature_basis,
)
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_curvature_validation import CONSUMED as SYNTHETIC_CONSUMED
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_scale import scale_weights
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.model_validation_report import write_table

FIT_GATE = "artifacts/models/arrival-timing/mean-curvature-fit-design-v1/review-acceptance.json"
CALIBRATION_GATE = (
    "artifacts/models/arrival-timing/mean-curvature-calibration-v1/"
    "calibration-review-acceptance.json"
)
CONSUMED = [
    *SYNTHETIC_CONSUMED,
    "analysis/arrival/model_curvature_fit.py",
    "scripts/fit_arrival_curvature.py",
    "analysis/arrival/model_validation_report.py",
    "scripts/run_arrival_curvature_calibration.py",
    CALIBRATION_GATE,
]


def verify_fit_gate(root: Path, job: dict[str, Any], output: Path, store: Path) -> dict[str, str]:
    gate = json.loads((root / FIT_GATE).read_text())
    if (
        gate.get("status") != "accepted_single_curvature_exploration_fit"
        or gate.get("independent_checker") is not True
        or gate.get("max_sampler_call_slots") != 1
        or gate.get("job") != job
        or gate.get("output") != str(output.relative_to(root))
        or gate.get("store") != str(store.relative_to(root))
        or not set(CONSUMED).issubset(gate.get("files", {}))
    ):
        raise ValueError("independent single-fit inference design required")
    for name, digest in gate["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("fit design source changed")
    calibration = json.loads((root / CALIBRATION_GATE).read_text())
    if (
        calibration.get("status") != "accepted_150_curvature_calibration"
        or calibration.get("independent_checker") is not True
        or calibration.get("recovery_cases") != 50
        or calibration.get("sbc_cases") != 100
    ):
        raise ValueError("complete independently accepted recovery and SBC required")
    prefix = "artifacts/models/arrival-timing/mean-curvature-calibration-v1"
    required = {prefix + "/plan.json", prefix + "/recovery-review-acceptance.json"}
    for phase, count in [("recovery", 50), ("sbc", 100)]:
        required.update(
            {
                prefix + f"/{phase}-report-v1/{name}"
                for name in [
                    "inputs.json",
                    "metrics.json",
                    "output-checksums.json",
                    "estimates-by-dataset.csv",
                    "grid-band-coverage.csv",
                ]
            }
        )
        for j in range(count):
            case = f"{phase}-{j:03d}"
            required.update(
                {
                    prefix + f"/jobs/{case}/{name}"
                    for name in ["result.json", "calibration-checks.json", "attempt-evidence.json"]
                }
            )
            required.add(f"data/processed/models/mean-curvature-calibration-v1/{case}.nc")
    required.add(prefix + "/sbc-report-v1/final-discrete-rank-ecdf-screen.csv")
    if not required.issubset(calibration.get("files", {})):
        raise ValueError("complete150-case calibration proof required")
    for name, digest in calibration["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("calibration source changed")

    def require(entries):
        if not entries or any(calibration["files"].get(n) != h for n, h in entries.items()):
            raise ValueError("incomplete referenced calibration closure")

    plan = json.loads((root / prefix / "plan.json").read_text())
    from scripts.run_arrival_curvature_calibration import make_cases

    if plan["cases"] != make_cases():
        raise ValueError("calibration allocation changed")
    require(plan["files"])
    recovery_gate = json.loads((root / prefix / "recovery-review-acceptance.json").read_text())
    require(recovery_gate["files"])
    for case in plan["cases"]:
        base = prefix + "/jobs/" + case["id"]
        manifest = json.loads((root / base / "attempt-evidence.json").read_text())
        mandatory = {
            base + "/" + name
            for name in [
                "job.json",
                "inputs.json",
                "result.json",
                "sampled-hyperparameter-diagnostics.csv",
                "sampling-diagnostics.csv",
                "calibration-checks.json",
            ]
        }
        mandatory.update({base + suffix for suffix in ["-spec.json", ".log", ".supervisor.json"]})
        mandatory.add("data/processed/models/mean-curvature-calibration-v1/" + case["id"] + ".nc")
        if manifest.get("case_id") != case["id"] or not mandatory.issubset(
            manifest.get("files", {})
        ):
            raise ValueError("complete immutable calibration attempt proof required")
        require(manifest["files"])
    for phase in ["recovery", "sbc"]:
        report = prefix + f"/{phase}-report-v1"
        source = json.loads((root / report / "inputs.json").read_text())
        require(source["files"])
        outputs = json.loads((root / report / "output-checksums.json").read_text())
        expected = {
            "inputs.json",
            "metrics.json",
            "estimates-by-dataset.csv",
            "sampling-and-functional-diagnostics.csv",
            "pointwise-coverage-and-recovery.csv",
            "grid-band-by-dataset.csv",
            "grid-band-coverage.csv",
            "findings.md",
        }
        if phase == "sbc":
            expected.add("final-discrete-rank-ecdf-screen.csv")
        if set(outputs) != expected:
            raise ValueError("complete contained calibration report proof required")
        require({report + "/" + name: h for name, h in outputs.items()})
    return {**gate["files"], FIT_GATE: sha256(root / FIT_GATE)}


def conditional_curvature_replicates(
    hyper: dict[str, np.ndarray],
    effects: np.ndarray,
    event_index: np.ndarray,
    distance: np.ndarray,
    reference: np.ndarray,
    *,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    count = len(hyper["alpha"])
    weights = scale_weights(distance)
    if (
        hyper["alpha"].shape != (count,)
        or hyper["beta"].shape != (count,)
        or hyper["gamma"].shape != (count,)
        or hyper["sigma_anchor"].shape != (count, 3)
        or effects.ndim != 2
        or effects.shape[0] != count
        or event_index.shape != distance.shape
        or reference.shape != distance.shape
        or not np.issubdtype(event_index.dtype, np.integer)
        or (event_index < 0).any()
        or (event_index >= effects.shape[1]).any()
        or (reference <= 0).any()
        or not np.isfinite(reference).all()
        or any(not np.isfinite(v).all() for v in [*hyper.values(), effects])
        or (hyper["sigma_anchor"] <= 0).any()
    ):
        raise ValueError("aligned fitted-event draws and positive residual scales required")
    response = (
        hyper["alpha"][:, None]
        + hyper["beta"][:, None] * np.log(distance / 1000)
        + hyper["gamma"][:, None] * curvature_basis(distance)
        + effects[:, event_index]
        + (hyper["sigma_anchor"] @ weights.T)
        * np.random.default_rng(seed).normal(size=(count, len(distance)))
    )
    native = np.exp(response) * reference
    if not np.isfinite(native).all() or (native <= 0).any():
        raise ValueError("unrepresentable conditional reports")
    return response, native


def fit_exploration_curvature(root: Path, job: dict[str, Any], output: Path, store: Path) -> None:
    if (
        output.exists()
        or store.with_name(store.stem + "-augmented.nc").exists()
        or not output.resolve().is_relative_to(root.resolve())
        or store.exists()
        or not store.resolve().is_relative_to(root.resolve())
        or job.get("target") != "NCEI-native-duration"
        or job.get("kind") != "mean-curvature"
        or job.get("prior") != "base"
        or any(type(job[k]) is not int or not 1000 <= job[k] <= 4000 for k in ["draws", "tune"])
        or type(job.get("cores")) is not int
        or not 1 <= job["cores"] <= 2
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 20
    ):
        raise ValueError("new paths and bounded base-prior primary-source candidate job required")
    pins = verify_fit_gate(root, job, output, store)
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    ids = np.flatnonzero(lane.included)
    model = build_curvature_model(lane, read_curvature_prior(root, "base"), indices=ids)
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "source_files": frozen,
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
    if "nutpie" not in str(posterior.attrs).lower():
        raise ValueError("unexplained candidate sampling backend change")
    first_diagnostics, first_table = sampling_diagnostics(tree)
    first_table.to_csv(output / "sampled-hyperparameter-diagnostics.csv", na_rep="unknown")
    if not first_diagnostics["screen_passed"]:
        write_json(
            output / "result.json",
            {
                "job": job,
                "diagnostics": first_diagnostics,
                "posterior": str(store.relative_to(root)),
                "posterior_sha256": sha256(store),
                "code_and_config": pins,
                "status": "diagnostic_failure",
                "reserved_outcomes": "sealed",
            },
        )
        return
    hyper = {
        p: posterior[p].values for p in ["alpha", "beta", "gamma", "tau_event", "sigma_anchor"]
    }
    u, events = conditional_curvature_effects(lane, hyper, seed=job["seed"] + 1, indices=ids)
    posterior["event_effect"] = xr.DataArray(
        u, dims=("chain", "draw", "event"), coords={"event": events}
    )
    posterior["residual_sd_1000km"] = xr.DataArray(
        hyper["sigma_anchor"][..., :2].mean(axis=-1), dims=("chain", "draw")
    )
    posterior["log_far_near_sd_ratio"] = xr.DataArray(
        np.log(hyper["sigma_anchor"][..., 2]) - np.log(hyper["sigma_anchor"][..., 0]),
        dims=("chain", "draw"),
    )
    tree["observed_data"] = xr.DataTree(
        xr.Dataset(
            {
                "response": (("record",), lane.response[ids]),
                "native_minutes": (("record",), lane.y[ids]),
            },
            coords={"record": [lane.record_ids[int(i)] for i in ids]},
        )
    )
    augmented = store.with_name(store.stem + "-augmented.nc")
    with augmented.open("xb"):
        pass
    tree.to_netcdf(augmented)
    os.replace(augmented, store)
    diagnostics, table = sampling_diagnostics(tree)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    write_json(output / "diagnostics.json", diagnostics)
    result = {
        "job": job,
        "diagnostics": diagnostics,
        "posterior": str(store.relative_to(root)),
        "posterior_sha256": sha256(store),
        "records": len(ids),
        "events": len(events),
        "reserved_outcomes": "sealed",
        "code_and_config": pins,
    }
    if not diagnostics["screen_passed"]:
        write_json(output / "result.json", {**result, "status": "diagnostic_failure"})
        return
    n = job["draws"] * 4
    take = np.linspace(0, n - 1, 800, dtype=int)
    flat = {
        p: hyper[p].reshape((n, 3) if p == "sigma_anchor" else (n,))[take]
        for p in ["alpha", "beta", "gamma", "sigma_anchor"]
    }
    event_index = np.array([events.index(lane.event_ids[int(i)]) for i in ids])
    response, native = conditional_curvature_replicates(
        flat,
        u.reshape(n, len(events))[take],
        event_index,
        lane.distance_km[ids],
        lane.reference_minutes[ids],
        seed=job["seed"] + 2,
    )
    distance = lane.distance_km[ids]
    checks = []
    for label, mask in [
        ("all", np.ones(len(ids), dtype=bool)),
        ("under-500km", distance < 500),
        ("500-to-2000km", (distance >= 500) & (distance < 2000)),
        ("2000-to-5000km", (distance >= 2000) & (distance < 5000)),
        ("5000km-and-above", distance >= 5000),
    ]:
        if not mask.any():
            continue
        for scale, obs, rep in [
            ("modeled-response", lane.response[ids], response),
            ("native-minutes", lane.y[ids], native),
        ]:
            for q in [0.05, 0.5, 0.95]:
                low, med, high = np.quantile(
                    np.quantile(rep[:, mask], q, axis=1), [0.05, 0.5, 0.95]
                )
                checks.append(
                    {
                        "stratum": label,
                        "scale": scale,
                        "quantile": q,
                        "records": int(mask.sum()),
                        "observed": float(np.quantile(obs[mask], q)),
                        "replicated_q05": float(low),
                        "replicated_q50": float(med),
                        "replicated_q95": float(high),
                    }
                )
    write_table(output / "conditional-predictive-quantiles-by-distance.csv", checks)
    q = np.quantile(native, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    write_table(
        output / "in-sample-record-predictions.csv",
        [
            {
                "record_id": lane.record_ids[int(i)],
                "event_id": lane.event_ids[int(i)],
                "observed_minutes": float(lane.y[i]),
                **{
                    f"q{level:02d}_minutes": float(q[k, j])
                    for k, level in enumerate([5, 25, 50, 75, 95])
                },
            }
            for j, i in enumerate(ids)
        ],
    )
    quantities = {
        p: posterior[p].values
        for p in [
            "alpha",
            "beta",
            "gamma",
            "tau_event",
            "residual_sd_1000km",
            "log_far_near_sd_ratio",
        ]
    }
    quantities.update(
        {f"sigma_{d}km": hyper["sigma_anchor"][..., j] for j, d in enumerate([500, 2000, 5000])}
    )
    quantities.update(
        {
            "median_reference_ratio_1000km": np.exp(hyper["alpha"]),
            "median_reference_ratio_100km": np.exp(
                hyper["alpha"] + hyper["beta"] * np.log(0.1) + hyper["gamma"] * np.log(4)
            ),
            "median_elasticity_1000km": 1 + hyper["beta"] - hyper["gamma"] / 3,
        }
    )
    write_table(
        output / "population-parameter-quantiles.csv",
        [
            {
                "parameter": p,
                "q05": float(np.quantile(v, 0.05)),
                "q50": float(np.quantile(v, 0.5)),
                "q95": float(np.quantile(v, 0.95)),
            }
            for p, v in quantities.items()
        ],
    )
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("candidatefit sources changed")
    write_json(
        output / "result.json",
        {**result, "status": "computed_pending_scientific_review", "conditional_ppc_draws": 800},
    )
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
