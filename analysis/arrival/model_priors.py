"""Ancestral prior checks in reported units, with explicit analyst-scale hypotheses."""

# pyright: basic
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from statistics import NormalDist
from typing import Any, cast

import matplotlib
import numpy as np
import pymc as pm

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from analysis.arrival.evidence import read_rows, sha256, write_json, write_rows  # noqa: E402
from analysis.arrival.model_data import CONTRACT, VREF_KM_MIN, load_lanes  # noqa: E402
from analysis.arrival.models import PRIORS, build_model, read_prior  # noqa: E402


def new_event_predictions(
    hyper: dict[str, np.ndarray], distance: np.ndarray, target: str, seed: int
) -> np.ndarray:
    """Forward-simulate one new event and independent records per hyperparameter draw."""
    rng = np.random.default_rng(seed)
    draws = len(hyper["alpha"])
    values = (
        hyper["alpha"][:, None]
        + hyper["beta"][:, None] * np.log(distance / 1000)
        + hyper["tau_event"][:, None] * rng.normal(size=(draws, 1))
        + hyper["sigma"][:, None] * rng.normal(size=(draws, len(distance)))
    )
    return values if target == "T-CAL" else np.exp(values + np.log(distance / VREF_KM_MIN))


def plot_prior_checks(output: Path) -> None:
    """Show marginal new-event predictions; uncertainty bands are prior, not fitted."""
    rows = read_rows(output / "new-event-prior-quantiles.csv")
    with plt.rc_context({"font.size": 11, "axes.titlesize": 12, "axes.labelsize": 11}):
        fig, axes = plt.subplots(3, 1, figsize=(7, 9), layout="constrained")
        for ax, target, label in zip(
            axes,
            ["NCEI-native-duration", "T-OBS", "T-CAL"],
            ["NCEI reported duration", "NTWC reported duration", "NTWC estimate − observation"],
            strict=True,
        ):
            for variant, color, alpha, text in [
                ("wider", "#777777", 0.18, "Wider sensitivity"),
                ("base", "#146782", 0.35, "Base prior"),
            ]:
                selected = sorted(
                    [r for r in rows if r["target"] == target and r["variant"] == variant],
                    key=lambda r: float(r["distance_km"]),
                )
                x = [float(r["distance_km"]) for r in selected]
                ax.fill_between(
                    x,
                    [float(r["q05_minutes"]) for r in selected],
                    [float(r["q95_minutes"]) for r in selected],
                    color=color,
                    alpha=alpha,
                    label=text,
                )
                ax.plot(x, [float(r["q50_minutes"]) for r in selected], color=color, lw=1.5)
            ax.set_xscale("log")
            ax.set_title(label, loc="left")
            ax.set_xlabel("Source–station distance (km, log scale)")
            ax.set_ylabel("Reported minutes" if target == "T-CAL" else "Minutes (log scale)")
            if target != "T-CAL":
                ax.set_yscale("log")
            else:
                ax.axhline(0, color="#333333", linewidth=0.8)
            ax.spines[["right", "top"]].set_visible(False)
            ax.grid(axis="y", alpha=0.2)
        axes[0].legend(loc="upper left", frameon=False, fontsize=11)
        fig.suptitle("Prior hypotheses allow substantial timing variation", fontsize=14)
        fig.supxlabel(
            "Central 90% prior predictions for a new event and record.\n"
            "Source: analyst priors; fixed 4 km depth reference.",
            fontsize=11,
        )
        fig.savefig(output / "new-event-prior-predictions.png", dpi=180)
        fig.savefig(output / "new-event-prior-predictions.svg")
        plt.close(fig)


def run_prior_checks(
    root: Path, output: Path, store: Path, *, draws: int = 2000, seed: int = 20261107
) -> None:
    """Check six declared hypotheses; do not condition prior draws on outcomes."""
    if output.exists() or store.exists() or draws < 500:
        raise ValueError("require new output/store and at least 500 ancestral draws")
    lanes, _ = load_lanes(root)
    output.mkdir(parents=True)
    store.mkdir(parents=True)
    grid = np.geomspace(50, 20000, 60)
    quantiles: list[dict[str, str]] = []
    dictionary: list[dict[str, str]] = []
    metrics: dict[str, dict[str, Any]] = {}
    trees: dict[str, dict[str, str]] = {}
    started = time.monotonic()
    for number, (target, variant) in enumerate((t, v) for t in lanes for v in ["base", "wider"]):
        prior = read_prior(root, target, variant)
        model = build_model(lanes[target], prior)
        with model:
            simulated = pm.sample_prior_predictive(draws=draws, random_seed=seed + number)
        key = target + "-" + variant
        path = store / (key + ".nc")
        simulated.to_netcdf(path)
        trees[key] = {"path": str(path.relative_to(root)), "sha256": sha256(path)}
        hyper = cast(Any, simulated["prior"])
        alpha = hyper["alpha"].values.reshape(-1)
        beta = hyper["beta"].values.reshape(-1)
        tau = hyper["tau_event"].values.reshape(-1)
        sigma = hyper["sigma"].values.reshape(-1)
        values = new_event_predictions(
            {"alpha": alpha, "beta": beta, "tau_event": tau, "sigma": sigma},
            grid,
            target,
            seed + 100 + number,
        )
        if not np.isfinite(values).all() or (target != "T-CAL" and (values <= 0).any()):
            raise ValueError(f"invalid prior support: {key}")
        summary = np.quantile(values, [0.01, 0.05, 0.5, 0.95, 0.99], axis=0)
        for i, distance in enumerate(grid):
            quantiles.append(
                {
                    "target": target,
                    "variant": variant,
                    "distance_km": str(distance),
                    **{
                        q + "_minutes": str(summary[j, i])
                        for j, q in enumerate(["q01", "q05", "q50", "q95", "q99"])
                    },
                }
            )
        design = cast(Any, simulated["prior_predictive"])["response"].values
        selected = np.flatnonzero(lanes[target].included)
        native = (
            design
            if target == "T-CAL"
            else np.exp(design + np.log(lanes[target].reference_minutes[selected]))
        )
        if not np.isfinite(native).all() or (target != "T-CAL" and (native <= 0).any()):
            raise ValueError(f"invalid full-design prior predictions: {key}")
        metrics[key] = {
            "draws": draws,
            "records": len(selected),
            "seed": seed + number,
            "finite_positive_duration_or_signed_minutes": True,
            "native_q01": float(np.quantile(native, 0.01)),
            "native_q50": float(np.quantile(native, 0.5)),
            "native_q99": float(np.quantile(native, 0.99)),
            "soft_extreme_fraction": float(np.mean(np.abs(native) > 180))
            if target == "T-CAL"
            else float(np.mean((np.exp(design) < 0.05) | (np.exp(design) > 20))),
            "soft_extreme_definition": "abs(discrepancy)>180min diagnostic only"
            if target == "T-CAL"
            else "ratio<0.05 or >20 diagnostic only",
            "duration_prior_second_moment_finite": None
            if target == "T-CAL"
            else 2 * max(prior["sigma_sd"], prior["tau_sd"]) < 1,
        }
        for parameter, scale in prior.items():
            half = parameter in {"tau_sd", "sigma_sd"}
            dictionary.append(
                {
                    "target": target,
                    "variant": variant,
                    "parameter": "tau_event"
                    if parameter == "tau_sd"
                    else parameter.removesuffix("_sd"),
                    "distribution": "HalfNormal" if half else "Normal",
                    "scale": str(scale),
                    "units": ("minutes" if target == "T-CAL" else "log_reference_ratio")
                    + ("_per_unit_ln_distance" if parameter == "beta_sd" else ""),
                    "support": "positive" if half else "real",
                    "q025": str(
                        NormalDist().inv_cdf(0.5125) * scale
                        if half
                        else NormalDist().inv_cdf(0.025) * scale
                    ),
                    "q975": str(NormalDist().inv_cdf(0.9875 if half else 0.975) * scale),
                    "rationale": "analyst scale hypothesis after EDA; not expert elicitation",
                }
            )
    write_rows(output / "new-event-prior-quantiles.csv", quantiles)
    write_rows(output / "parameter-prior-dictionary.csv", dictionary)
    write_json(output / "metrics.json", metrics)
    write_json(output / "saved-prior-draws.json", trees)
    (output / "prior-assumptions.md").write_text(
        "# Reported-timing prior hypotheses\n\n"
        "These are analyst scale choices made after descriptive EDA, not expert elicitation "
        "or measured physical constraints. The three source/target lanes remain separate.\n\n"
        "For durations, r=ln(y/t0), x=ln(d/1000), r~Normal(alpha+beta*x+tau*z,sigma), "
        "z~Normal(0,1). The fixed t0 uses 4 km depth. Base priors are alpha~Normal(0,0.5), "
        "beta~Normal(0,0.25), tau,sigma~HalfNormal(0.4). At 1,000 km and zero event effect, "
        "the central 95% interval for the conditional median/reference ratio is "
        "[0.375,2.664]; the linear total distance exponent 1+beta has interval [0.510,1.490]. "
        "These broad ranges express uncertainty in reported values, not wave-speed limits.\n\n"
        "T-CAL uses signed minutes directly. Base alpha~Normal(0,30), beta~Normal(0,15) "
        "minutes per unit log-distance; tau,sigma~HalfNormal(30). Centering alpha at zero "
        "is a modeling hypothesis, not evidence that historical forecasts were unbiased.\n\n"
        "Wider duration scales are 0.8/0.4/0.6/0.6; wider T-CAL scales are 60/30/60/60. "
        "Duration base priors have finite predictive first and second moments at fixed distance. "
        "The wider joint duration prior has a finite mean but infinite second moment: "
        "for a HalfNormal scale s times independent standard Normal, its MGF exists only "
        "for |t|s<1; 2*0.6>1. Quantiles, not a predictive SD, summarize this sensitivity.\n\n"
        "The likelihood is a working continuous density for native reported point values. "
        "Display precision is retained without asserting accuracy or a rounding rule. "
        "Event variation includes unresolved clock/source/path effects; origin error is not "
        "separately identified. Sigma is composite reported-record spread. Missingness and "
        "archive selection are conditioned on, not corrected as MCAR/MAR/MNAR. "
        "Observation/coarsening and conflict-record sensitivities precede selection.\n\n"
        "The dictionary contains 2.5% and 97.5% parameter quantiles. Non-centered z_event "
        "has a standard Normal prior; event_effect=tau_event*z_event. Alpha and beta are "
        "locations/slopes, while tau_event and sigma are SDs on the modeled response scale.\n\n"
        f"All six {draws:,}-draw ancestral checks produced finite predictions, with positive "
        "durations. Soft flags (ratio below 0.05/above 20, or absolute T-CAL above 180 minutes) "
        "are diagnostic yardsticks, not impossible outcomes or automatic acceptance cutoffs. "
        "Pooled-design quantiles reflect the archived distance composition. The plotted bands "
        "instead condition on distance and simulate a new event and record.\n\n"
        "Recommendation: take the base hypotheses into simulation/recovery; retain the wider "
        "hypotheses for sensitivity. This check does not establish physical validity, "
        "identifiability, posterior convergence or predictive performance. No scientific "
        "posterior was fitted. Reproduce with the recorded inputs, seeds and CLI.\n",
        encoding="utf-8",
    )
    consumed = [
        PRIORS,
        CONTRACT,
        "analysis/arrival/models.py",
        "analysis/arrival/model_priors.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/evidence.py",
        "scripts/arrival_model.py",
        "pyproject.toml",
        "uv.lock",
    ]
    write_json(
        output / "inputs.json",
        {
            "files": {p: sha256(root / p) for p in consumed},
            "data_inputs": json.loads(
                (
                    root / "artifacts/models/arrival-timing/exploration-contract-v1/inputs.json"
                ).read_text()
            )["files"],
            "draws": draws,
            "seed": seed,
        },
    )
    write_json(
        output / "run-metadata.json",
        {
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "dirty_paths": subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True
            ).splitlines(),
            "elapsed_seconds": time.monotonic() - started,
            "scientific_posterior_fitted": False,
            "method": "pm.sample_prior_predictive; new-group predictions from hyperdraws",
        },
    )
    plot_prior_checks(output)
    write_json(
        output / "output-checksums.json", {p.name: sha256(p) for p in sorted(output.iterdir())}
    )
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    import mlflow

    mlflow.set_tracking_uri((root / ".mlflow/mlruns").as_uri())
    cast(Any, mlflow).set_experiment("arrival-model")
    with mlflow.start_run(run_name="MS-1-source-specific-prior-checks") as run:
        mlflow.log_params(
            {"stage": "MS-1", "draws": draws, "seed": seed, "scientific_posterior_fit": False}
        )
        for key, values in metrics.items():
            mlflow.log_metric(key + ".soft_extreme_fraction", values["soft_extreme_fraction"])
        for p in output.iterdir():
            mlflow.log_artifact(str(p))
        mlflow.set_tags(
            {
                "decision": "prior_hypotheses_pending_review",
                "git_sha": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=root, text=True
                ).strip(),
            }
        )
        run_id = run.info.run_id
    write_json(output / "mlflow-receipt.json", {"run_id": run_id})
