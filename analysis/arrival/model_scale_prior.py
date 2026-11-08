"""Ancestral checks and design support for the fixed-anchor residual SD candidate."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_scale import (
    ANCHORS_KM,
    new_scale_event_predictions,
    scale_prior_moments,
    scale_weights,
)
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import PRIORS, read_prior


def run_scale_prior(
    root: Path, output: Path, store: Path, *, draws: int = 4000, seed: int = 79261107
) -> None:
    if (
        output.exists()
        or store.exists()
        or not store.resolve().is_relative_to(root.resolve())
        or type(draws) is not int
        or not 1000 <= draws <= 10000
    ):
        raise ValueError("new output/project store and1000..10000ancestral draws required")
    lanes, contract = load_lanes(root)
    consumed = [
        "analysis/arrival/model_scale_prior.py",
        "analysis/arrival/model_scale.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/models.py",
        "analysis/arrival/model_validation_report.py",
        "analysis/arrival/evidence.py",
        "scripts/check_arrival_scale_prior.py",
        PRIORS,
        "config/arrival-model-contract-v1.toml",
        "pyproject.toml",
        "uv.lock",
    ]
    pins = {p: sha256(root / p) for p in [*contract["inputs"], *consumed]}
    approved = json.loads(
        (root / "artifacts/models/arrival-timing/prior-checks-v1/inputs.json").read_text()
    )
    if pins[PRIORS] != approved["files"][PRIORS]:
        raise ValueError("base prior specification differs from approved MS-1")
    lane = lanes["NCEI-native-duration"]
    selected = np.flatnonzero(lane.included)
    prior = read_prior(root, lane.target, "base")
    rng = np.random.default_rng(seed)
    hyper = {
        "alpha": rng.normal(size=draws) * prior["alpha_sd"],
        "beta": rng.normal(size=draws) * prior["beta_sd"],
        "tau_event": np.abs(rng.normal(size=draws)) * prior["tau_sd"],
        "sigma_anchor": np.abs(rng.normal(size=(draws, 3))) * prior["sigma_sd"],
    }
    grid = np.unique(np.r_[np.geomspace(50, 20000, 60), ANCHORS_KM, 1000.0])
    predicted = new_scale_event_predictions(hyper, grid, seed=seed + 1)
    constant = new_scale_event_predictions(
        {**hyper, "sigma_anchor": np.repeat(hyper["sigma_anchor"][:, 0, None], 3, axis=1)},
        grid,
        seed=seed + 1,
    )
    events = sorted({lane.event_ids[int(i)] for i in selected})
    event_index = np.array([events.index(lane.event_ids[int(i)]) for i in selected])
    effects = rng.normal(size=(draws, len(events))) * hyper["tau_event"][:, None]
    weights = scale_weights(lane.distance_km[selected])
    response = (
        hyper["alpha"][:, None]
        + hyper["beta"][:, None] * lane.x[selected]
        + effects[:, event_index]
        + (hyper["sigma_anchor"] @ weights.T) * rng.normal(size=(draws, len(selected)))
    )
    if not np.isfinite(response).all():
        raise ValueError("unrepresentable full-design prior responses")
    native = np.exp(response) * lane.reference_minutes[selected]
    if not np.isfinite(native).all() or (native <= 0).any():
        raise ValueError("invalid native prior support")
    output.mkdir(parents=True)
    store.mkdir(parents=True)
    tree = xr.DataTree.from_dict(
        {
            "prior": xr.Dataset(
                {
                    **{
                        p: (("chain", "draw"), v[None, :])
                        for p, v in hyper.items()
                        if p != "sigma_anchor"
                    },
                    "sigma_anchor": (
                        ("chain", "draw", "scale_anchor_km"),
                        hyper["sigma_anchor"][None, ...],
                    ),
                },
                coords={"scale_anchor_km": list(ANCHORS_KM)},
            ),
            "prior_predictive": xr.Dataset(
                {"response": (("chain", "draw", "record"), response[None, ...])},
                coords={"record": [lane.record_ids[int(i)] for i in selected]},
            ),
            "new_event_grid": xr.Dataset(
                {
                    "native_minutes": (("chain", "draw", "distance_km"), predicted[None, ...]),
                    "constant_scale_native_minutes": (
                        ("chain", "draw", "distance_km"),
                        constant[None, ...],
                    ),
                },
                coords={"distance_km": grid},
            ),
        }
    )
    path = store / "ancestral-draws.nc"
    tree.to_netcdf(path)
    rows = []
    for label, values in [("distance-profile", predicted), ("constant-scale-reference", constant)]:
        q = np.quantile(values, [0.05, 0.5, 0.95], axis=0)
        for j, distance in enumerate(grid):
            rows.append(
                {
                    "prior": label,
                    "distance_km": float(distance),
                    "q05_minutes": float(q[0, j]),
                    "q50_minutes": float(q[1, j]),
                    "q95_minutes": float(q[2, j]),
                }
            )
    write_table(output / "new-event-duration-prior-quantiles.csv", rows)
    w = scale_weights(grid)
    mean, second = scale_prior_moments(w, prior["sigma_sd"])
    scales = hyper["sigma_anchor"] @ w.T
    q = np.quantile(scales, [0.05, 0.5, 0.95], axis=0)
    scale_rows = [
        {
            "distance_km": float(d),
            "prior_mean_sd": float(mean[i]),
            "prior_mean_residual_variance": float(second[i]),
            "constant_reference_mean_variance": prior["sigma_sd"] ** 2,
            "sd_q05": float(q[0, i]),
            "sd_q50": float(q[1, i]),
            "sd_q95": float(q[2, i]),
        }
        for i, d in enumerate(grid)
    ]
    write_table(output / "residual-scale-prior-and-interpolation-moments.csv", scale_rows)
    support = []
    for j, anchor in enumerate(ANCHORS_KM):
        train_counts = []
        event_counts = []
        for fold in sequence_folds(lane):
            wf = scale_weights(lane.distance_km[fold.train])[:, j]
            train_counts.append(int((wf > 0).sum()))
            event_counts.append(
                len(
                    {
                        lane.event_ids[int(i)]
                        for i, weight in zip(fold.train, wf, strict=True)
                        if weight > 0
                    }
                )
            )
        active = weights[:, j] > 0
        support.append(
            {
                "anchor_km": anchor,
                "rows_positive_weight": int(active.sum()),
                "events_positive_weight": len(
                    {lane.event_ids[int(i)] for i, on in zip(selected, active, strict=True) if on}
                ),
                "weight_mass": float(weights[:, j].sum()),
                "min_fold_training_rows": min(train_counts),
                "min_fold_training_events": min(event_counts),
                "scope": (
                    "overlapping_support_counts_not_independent_information_or_effective_sample_size"
                ),
            }
        )
    write_table(output / "anchor-support-and-sequence-fold-gaps.csv", support)
    dictionary = [
        {
            "parameter": p,
            "distribution": "Normal" if p in ["alpha", "beta"] else "HalfNormal",
            "scale": prior[key],
            "units": "log_reference_ratio_per_ln_distance"
            if p == "beta"
            else "log_reference_ratio",
            "role": "record_SD_at_anchor"
            if p.startswith("sigma_")
            else {
                "alpha": "population_log_median_ratio_at1000km",
                "beta": "distance_adjustment",
                "tau_event": "between_event_SD",
            }[p],
            "source": "analyst_hypothesis_after_exploration_not_expert_elicitation",
        }
        for p, key in [
            ("alpha", "alpha_sd"),
            ("beta", "beta_sd"),
            ("tau_event", "tau_sd"),
            ("sigma_500km", "sigma_sd"),
            ("sigma_2000km", "sigma_sd"),
            ("sigma_5000km", "sigma_sd"),
        ]
    ]
    write_table(output / "parameter-prior-dictionary.csv", dictionary)
    metrics = {
        "draws": draws,
        "seed": seed,
        "primary_records": len(selected),
        "events": len(events),
        "finite_positive_prior_predictions": True,
        "prior_first_second_native_moments_finite_at_fixed_distance": True,
        "moment_reason": "convex_scale_Jensen_bound_and_HalfNormal_sd_point4_not_support_bound",
        "soft_ratio_extreme_fraction": float(
            np.mean((np.exp(response) < 0.05) | (np.exp(response) > 20))
        ),
        "soft_scope": "diagnostic_yardstick_not_impossible_values_or_acceptance_cutoff",
        "posterior_fitted": False,
        "anchors_km": ANCHORS_KM,
    }
    write_json(output / "metrics.json", metrics)
    write_json(
        output / "saved-draws.json", {"path": str(path.relative_to(root)), "sha256": sha256(path)}
    )
    (output / "prior-assumptions.md").write_text(
        "# Distance-dependent reported-record spread\n\n"
        "This candidate interpolates positive residual SDs linearly in log distance at500,2000 "
        "and5000km, with constant endpoint extrapolation. The curve is continuous with corners, "
        "not differentiably smooth. This definition does not validate distance/support transport. "
        "No monotonicity is imposed. Anchors reuse existing exploration distance thresholds.\n\n"
        "Independent HalfNormal(.4) SD anchors are composite reported-log-ratio variation, "
        "not measurement accuracy or physical noise. Alpha,beta and event-SD priors remain "
        "the base analyst hypotheses. Equal anchors reproduce the baseline likelihood; "
        "they do not define a prior-equivalent equality submodel. The constant reference "
        "draws one shared HalfNormal SD. Paired draws reduce Monte Carlo comparison noise.\n\n"
        "Prior E[sigma(d)] is constant, but E[sigma(d)^2] falls between anchors: "
        ".16 at an anchor versus approximately.131 halfway between two on the log axis. "
        "Independence supplies no hierarchy shrinking anchors toward a common value.\n\n"
        "At every fixed finite distance, base first and second native-duration moments exist: "
        "convexity gives sigma(d)^2<=sum(w_j*s_j^2), and the t=2 HalfNormal MGF bound "
        "has 1-4*.4^2*w_j>0. The independent event-scale bound also passes. These are "
        "prior scale conditions, not upper bounds on sampled SD values. Wider.6 hypotheses "
        "do not retain the second-moment claim. Finite draws alone prove no moment claim.\n\n"
        "Support rows/events overlap across anchors; weight mass is not an ESS. Prior predictions "
        "condition on the archived exploration design and simulate a new event/record. "
        "No actual posterior, source repair, confirmation outcome or reserved outcome is used.\n"
    )
    plot_scale_prior(output, rows, scale_rows)
    if any(sha256(root / p) != digest for p, digest in pins.items()):
        raise ValueError("prior-check inputs changed during generation")
    write_json(output / "inputs.json", pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def plot_scale_prior(
    output: Path, rows: list[dict[str, Any]], scales: list[dict[str, Any]]
) -> None:
    """Takeaway: interpolation changes prior dispersion, not the prior mean SD | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with plt.rc_context({"font.size": 11}):
        fig, axes = plt.subplots(2, 1, figsize=(7, 8), layout="constrained")
        for label, color in [
            ("constant-scale-reference", "#777777"),
            ("distance-profile", "#146782"),
        ]:
            data = [r for r in rows if r["prior"] == label]
            d = [r["distance_km"] for r in data]
            axes[0].fill_between(
                d,
                [r["q05_minutes"] for r in data],
                [r["q95_minutes"] for r in data],
                color=color,
                alpha=0.2,
                label=label.replace("-", " "),
            )
            axes[0].plot(d, [r["q50_minutes"] for r in data], color=color)
        axes[0].set(
            xscale="log",
            yscale="log",
            ylabel="New report duration (minutes, log)",
            xlabel="Distance (km, log scale)",
        )
        axes[0].legend(frameon=False, fontsize=10.5)
        axes[0].set_title("Broad prior predictions for a new event and report", loc="left")
        d = [r["distance_km"] for r in scales]
        axes[1].plot(d, [r["prior_mean_residual_variance"] for r in scales], color="#146782")
        axes[1].axhline(0.16, color="#777777", ls="--", label="constant reference")
        axes[1].set(
            xscale="log",
            xlabel="Distance (km, log scale)",
            ylabel="Prior mean residual variance\n(log-ratio²)",
        )
        axes[1].set_title("Expected variance falls between anchors", loc="left")
        for ax in axes:
            ax.spines[["right", "top"]].set_visible(False)
        fig.suptitle("A scale curve adds explicit prior assumptions", fontsize=14)
        fig.supxlabel(
            "Upper: central 90% bands and medians. Lower: analytic prior mean variance.\n"
            "Source: analyst priors and fixed NCEI exploration distance design.",
            fontsize=10.5,
        )
        fig.savefig(output / "distance-scale-prior-predictions.png", dpi=180)
        fig.savefig(output / "distance-scale-prior-predictions.svg")
        plt.close(fig)
