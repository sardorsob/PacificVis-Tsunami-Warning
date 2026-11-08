"""Finite known-Gaussian normalizer-path and covariance calibration; no actual fitting."""

# pyright: basic
from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
from scipy.signal import lfilter
from scipy.stats import multivariate_normal, norm

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_bridge_path import path_score
from analysis.arrival.model_validation_report import write_table

CONSUMED = [
    "analysis/arrival/model_bridge_path.py",
    "analysis/arrival/model_bridge_path_validation.py",
    "analysis/arrival/model_bridge.py",
    "analysis/arrival/model_scoring.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/model_prediction.py",
    "analysis/arrival/model_evaluation.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/models.py",
    "analysis/arrival/evidence.py",
    "analysis/arrival/model_validation_report.py",
    "scripts/validate_arrival_bridge_path.py",
    "pyproject.toml",
    "uv.lock",
]


def known_geometry():
    mean0 = np.array([0.0, 0.2, -0.1, 0.0, 0.0, 0.1])
    mean1 = mean0 + np.array([0.6, -0.4, 0.2, 0.8, -0.3, 0.5])
    cov0 = np.diag([1, 0.8, 1.4, 1.2, 0.7, 0.9]) + 0.2 * np.ones((6, 6))
    cov1 = np.diag([0.6, 1.2, 0.9, 0.7, 1.5, 1]) + 0.15 * np.ones((6, 6))
    return mean0, mean1, cov0, cov1


def normal_path(mean0, mean1, cov0, cov1, times, constant):
    """Independent natural-parameter Gaussian normalizers, including all determinants."""
    p0, p1 = np.linalg.solve(cov0, np.eye(len(mean0))), np.linalg.solve(cov1, np.eye(len(mean0)))
    states = []
    for t in times:
        precision = (1 - t) * p0 + t * p1
        linear = (1 - t) * (p0 @ mean0) + t * (p1 @ mean1)
        covariance = np.linalg.solve(precision, np.eye(len(mean0)))
        mean = np.linalg.solve(precision, linear)
        remainder = (1 - t) * mean0 @ p0 @ mean0 + t * mean1 @ p1 @ mean1 - linear @ mean
        logdet = (1 - t) * np.linalg.slogdet(cov0)[1] + t * np.linalg.slogdet(cov1)[1]
        logdet += np.linalg.slogdet(precision)[1]
        normalizer = t * constant - 0.5 * (logdet + remainder)
        states.append((mean, covariance, float(normalizer)))
    return states


def calibrate_paths(root: Path, output: Path):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local calibration output required")
    pins = {p: sha256(root / p) for p in CONSUMED}
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "purpose": "known_Normal_path_MCSE_not_model_SBC_or_physical_validation",
            "actual_pm_sample_calls": 0,
            "replicates": 60,
            "chains": 4,
            "draws_per_stage": 8000,
        },
    )
    for p in CONSUMED:
        dest = output / "source-snapshot" / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((root / p).read_bytes())
    geometry = known_geometry()
    m0, m1, c0, c1 = geometry
    times = np.linspace(0, 1, 9)
    constant = -1700.0
    states = normal_path(*geometry, times, constant)
    write_json(
        output / "known-targets.json",
        {
            "times": times.tolist(),
            "constant": constant,
            "mean0": m0.tolist(),
            "mean1": m1.tolist(),
            "cov0": c0.tolist(),
            "cov1": c1.tolist(),
            "log_normalizers": [s[2] for s in states],
            "normalization_records": 100,
        },
    )
    rows = []
    started = time.monotonic()
    try:
        for mode, rho in enumerate([0.0, 0.8]):
            for rep in range(30):
                seed = 1926110800 + mode * 1000 + rep
                rng = np.random.default_rng(seed)
                logs = []
                for mean, covariance, _ in states:
                    eps = rng.normal(size=(4, 8000, 6))
                    previous = rng.normal(size=(4, 1, 6))
                    z = lfilter([math.sqrt(1 - rho**2)], [1, -rho], eps, axis=1, zi=rho * previous)[
                        0
                    ]
                    samples = mean + z @ np.linalg.cholesky(covariance).T
                    logs.append(
                        constant
                        + cast(Any, multivariate_normal).logpdf(samples, m1, c1)
                        - cast(Any, multivariate_normal).logpdf(samples, m0, c0)
                    )
                result, _ = path_score(logs, times, records=100)
                write_json(output / "cases" / f"mode-{mode}-rep-{rep:02d}.json", result)
                err = result["joint_log_predictive"] - constant
                mcse = result["joint_log_mcse_delta"]
                naive = math.sqrt(sum(e["joint_log_mcse_delta"] ** 2 for e in result["edges"]))
                rows.append(
                    {
                        "mode": "iid" if rho == 0 else "AR0.8",
                        "replicate": rep,
                        "seed": seed,
                        "truth": constant,
                        "estimate": result["joint_log_predictive"],
                        "error": err,
                        "mcse": mcse,
                        "naive_independent_edge_mcse": naive,
                        "z_error": err / mcse,
                        "covers_90": abs(err) <= norm.ppf(0.95) * mcse,
                        "precision_passed": result["precision_passed"],
                        "min_edge_overlap": min(e["overlap"] for e in result["edges"]),
                    }
                )
                write_table(output / "known-path-trials.csv", rows)
            print("known path", rho, "completed30", flush=True)
        summary = []
        for mode in ["iid", "AR0.8"]:
            selected = [r for r in rows if r["mode"] == mode]
            err = np.array([r["error"] for r in selected])
            mcse = np.array([r["mcse"] for r in selected])
            summary.append(
                {
                    "mode": mode,
                    "replicates": len(selected),
                    "accepted": sum(r["precision_passed"] for r in selected),
                    "mean_error": float(err.mean()),
                    "empirical_sd": float(err.std(ddof=1)),
                    "rms_mcse": float(np.sqrt(np.mean(mcse**2))),
                    "covers_90": sum(r["covers_90"] for r in selected),
                    "min_edge_overlap": min(r["min_edge_overlap"] for r in selected),
                }
            )
        write_table(output / "known-path-summary.csv", summary)
        write_json(
            output / "result.json",
            {
                "status": "known_path_calibration_pending_review",
                "replicates": len(rows),
                "actual_sampler_calls": 0,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
    except Exception as exc:
        write_json(
            output / "failure.json",
            {
                "error": str(exc),
                "completed_replicates": len(rows),
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("calibration source changed")
