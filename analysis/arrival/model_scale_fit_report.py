"""Model-dependent mean and spread curves, with conditional model criticism."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

from analysis.arrival.evidence import read_rows, sha256, write_json
from analysis.arrival.model_scale import scale_weights
from analysis.arrival.model_validation_report import write_table


def scale_fit_report(root: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("new report path required")
    folders = {
        "constant": root
        / "artifacts/models/arrival-timing/exploration-baselines-v1/NCEI-native-duration/event",
        "distance-scale": root / "artifacts/models/arrival-timing/exploration-distance-scale-v1",
    }
    posterior = {}
    pins = {}
    checks = []
    for name, folder in folders.items():
        result = json.loads((folder / "result.json").read_text())
        if not result["diagnostics"]["screen_passed"]:
            raise ValueError("failed fit cannot be reported")
        path = root / result["posterior"]
        if sha256(path) != result["posterior_sha256"]:
            raise ValueError("posterior changed")
        for file, digest in json.loads((folder / "output-checksums.json").read_text()).items():
            if sha256(folder / file) != digest:
                raise ValueError("fit output changed")
        for file in [
            "result.json",
            "output-checksums.json",
            "conditional-predictive-quantiles-by-distance.csv",
        ]:
            pins[str((folder / file).relative_to(root))] = sha256(folder / file)
        pins[str(path.relative_to(root))] = sha256(path)
        with xr.open_dataset(path, group="posterior", engine="h5netcdf") as ds:
            posterior[name] = {p: ds[p].values.copy() for p in ds.data_vars}
        checks += [
            {
                "model": name,
                **{k: float(v) if k not in ["stratum", "scale"] else v for k, v in row.items()},
            }
            for row in read_rows(folder / "conditional-predictive-quantiles-by-distance.csv")
        ]
    distance = np.unique(np.r_[np.geomspace(50, 20000, 120), 500, 1000, 2000, 5000])
    curves = []
    event_sd = []
    for name, post in posterior.items():
        alpha = post["alpha"].reshape(-1)
        beta = post["beta"].reshape(-1)
        mean = alpha[:, None] + beta[:, None] * np.log(distance / 1000)
        sigma = (
            post["sigma_anchor"].reshape(-1, 3) @ scale_weights(distance).T
            if name == "distance-scale"
            else np.broadcast_to(post["sigma"].reshape(-1, 1), mean.shape)
        )
        qm = np.quantile(mean, [0.05, 0.5, 0.95], axis=0)
        qs = np.quantile(sigma, [0.05, 0.5, 0.95], axis=0)
        curves += [
            {
                "model": name,
                "distance_km": float(d),
                **{
                    f"population_log_ratio_q{q:02d}": float(qm[k, j])
                    for k, q in enumerate([5, 50, 95])
                },
                **{f"residual_sd_q{q:02d}": float(qs[k, j]) for k, q in enumerate([5, 50, 95])},
            }
            for j, d in enumerate(distance)
        ]
        low, med, high = np.quantile(post["tau_event"], [0.05, 0.5, 0.95])
        event_sd.append({"model": name, "q05": float(low), "q50": float(med), "q95": float(high)})
    post = posterior["distance-scale"]
    names = ["alpha", "beta", "tau_event", "sigma_500km", "sigma_2000km", "sigma_5000km"]
    values = [post[p].reshape(-1) for p in names[:3]] + [
        post["sigma_anchor"][..., j].reshape(-1) for j in range(3)
    ]
    correlation = np.corrcoef(values)
    coupling = [
        {
            "parameter_a": a,
            "parameter_b": b,
            "posterior_correlation": float(correlation[i, j]),
            "scope": "linear_posterior_coupling_not_causation_or_identifiability_certificate",
        }
        for i, a in enumerate(names)
        for j, b in enumerate(names)
        if j > i
    ]
    output.mkdir(parents=True)
    write_table(output / "population-mean-and-residual-spread-curves.csv", curves)
    write_table(output / "between-event-spread-by-model.csv", event_sd)
    write_table(output / "posterior-parameter-coupling.csv", coupling)
    write_table(output / "conditional-reported-quantile-checks.csv", checks)
    plot_scale_fits(output, curves, event_sd, checks)
    alpha = np.quantile(post["alpha"], [0.05, 0.5, 0.95])
    exponent = np.quantile(1 + post["beta"], [0.05, 0.5, 0.95])
    sigma = np.median(post["sigma_anchor"].reshape(-1, 3), axis=0)
    tau0, tau1 = event_sd

    def cell(model, stratum, q):
        return next(
            r
            for r in checks
            if r["model"] == model
            and r["stratum"] == stratum
            and r["scale"] == "modeled-response"
            and r["quantile"] == q
        )

    far0 = [cell("constant", "5000km-and-above", q) for q in [0.05, 0.95]]
    far1 = [cell("distance-scale", "5000km-and-above", q) for q in [0.05, 0.95]]
    middle = cell("distance-scale", "2000-to-5000km", 0.5)
    text = (
        "# Distance-dependent report variation\n\n"
        "The new candidate reproduces much more of the tight far-distance scatter, while "
        "conditional discrepancies remain. Both models use the same 1,064 NCEI reports from "
        "33 exploration events; six ambiguous repeated-edge records remain excluded together. "
        "This is a model of native reported positive duration, with composite source, clock, "
        "path and reporting variation.\n\n"
        "The candidate changes residual SD between 500, 2,000 and 5,000 km, holding endpoint "
        f"SDs constant outside those anchors. Its median SDs are approximately {sigma[0]:.3f}, "
        f"{sigma[1]:.3f} and {sigma[2]:.3f} on the log-ratio scale. "
        "The HalfNormal(0.4) prior scale is not an upper "
        "bound on a sampled or fitted SD. The population log-ratio center at 1,000 km is "
        f"{alpha[1]:.3f} [{alpha[0]:.3f}, {alpha[2]:.3f}]; "
        "the conditional-median distance exponent is "
        f"{exponent[1]:.3f} [{exponent[0]:.3f}, {exponent[2]:.3f}], "
        "with central 90% intervals. These are phenomenological "
        "reported-timing parameters, rather than measured wave speed.\n\n"
        f"Between-event SD changes from {tau0['q50']:.3f} [{tau0['q05']:.3f}, {tau0['q95']:.3f}] "
        f"under constant residual spread to {tau1['q50']:.3f} "
        f"[{tau1['q05']:.3f}, {tau1['q95']:.3f}]. "
        "This large change shows model-dependent variance attribution. "
        "The candidate recovery settings used true event SD 0.2; prior-averaged calibration "
        "with 100 datasets does not establish conditional calibration in this lower-SD regime. "
        "Prior, observation and influential-event sensitivities remain necessary.\n\n"
        "At distances of at least 5,000 km, observed log-ratio 5–95% quantiles are "
        f"[{far1[0]['observed']:.3f}, {far1[1]['observed']:.3f}]. Median replicated quantiles "
        f"change from [{far0[0]['replicated_q50']:.3f}, {far0[1]['replicated_q50']:.3f}] "
        f"to [{far1[0]['replicated_q50']:.3f}, {far1[1]['replicated_q50']:.3f}]. "
        f"In the 2,000–5,000 km band the observed median is {middle['observed']:.4f}, "
        f"compared with {middle['replicated_q50']:.4f} for the candidate median replicated "
        "statistic; both tails "
        "also remain too broad there. These fitted-event checks motivate a bounded mean, "
        "scale and tail revisit. Counts of flagged checks are correlated exploratory "
        "descriptions, not a model ranking rule.\n\n"
        "The curve bands describe posterior uncertainty in population parameters. The "
        "predictive-check bars describe central 90% variation in replicated sample quantiles, "
        "conditional on fitted events. They are different uncertainty statements. Posterior "
        "correlations describe linear coupling under this model and do not prove causation "
        "or identifiability. Numerical diagnostics and independent raw-array replay passed; "
        "new-sequence prediction, sensitivity and selection remain incomplete. "
        "The 18 reserved outcomes remain sealed.\n"
    )
    (output / "findings.md").write_text(text)
    for p in [
        "analysis/arrival/model_scale_fit_report.py",
        "analysis/arrival/model_scale.py",
        "analysis/arrival/model_validation_report.py",
        "scripts/summarize_arrival_scale_fit.py",
    ]:
        pins[p] = sha256(root / p)
    write_json(output / "inputs.json", pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def plot_scale_fits(output, curves, event_sd, checks):
    """Takeaway: spread assumptions change event attribution | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"constant": "#777777", "distance-scale": "#146782"}
    labels = {"constant": "Constant spread", "distance-scale": "Spread by distance"}
    with plt.rc_context({"font.size": 11, "axes.titlesize": 12}):
        fig, axes = plt.subplots(
            3, 1, figsize=(7, 9), layout="constrained", height_ratios=[1, 1, 0.65]
        )
        for name in colors:
            rows = sorted(
                [r for r in curves if r["model"] == name], key=lambda r: float(r["distance_km"])
            )
            d = [r["distance_km"] for r in rows]
            for ax, prefix in zip(axes[:2], ["population_log_ratio", "residual_sd"], strict=True):
                ax.fill_between(
                    d,
                    [r[prefix + "_q05"] for r in rows],
                    [r[prefix + "_q95"] for r in rows],
                    color=colors[name],
                    alpha=0.18,
                )
                ax.plot(
                    d, [r[prefix + "_q50"] for r in rows], color=colors[name], label=labels[name]
                )
                ax.set(xscale="log", xlabel="Distance (km, log scale)")
        axes[0].set_title("Population centers depend on the spread model", loc="left")
        axes[0].set_ylabel("Population ln(reported / t₀)")
        axes[0].legend(frameon=False, fontsize=10.5)
        axes[1].set_title("Far-distance residual spread becomes much tighter", loc="left")
        axes[1].set_ylabel("Residual SD (log-ratio)")
        axes[1].set_ylim(bottom=0)
        for j, r in enumerate(event_sd):
            axes[2].errorbar(
                r["q50"],
                j,
                xerr=[[r["q50"] - r["q05"]], [r["q95"] - r["q50"]]],
                fmt="o",
                capsize=3,
                color=colors[r["model"]],
            )
        axes[2].set(
            yticks=range(len(event_sd)),
            yticklabels=[labels[r["model"]] for r in event_sd],
            xlabel="Between-event SD (log-ratio)",
            ylim=(-0.7, 1.7),
        )
        axes[2].set_title("Event variation is model-dependent", loc="left")
        for ax in axes:
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle("Changing residual spread changes the hierarchy", fontsize=14)
        fig.supxlabel(
            "Bands and bars: central 90% posterior parameter intervals.\n"
            "t₀ = distance / fixed 4-km-depth reference speed.\n"
            "Source: NCEI exploration, 1,064 reports / 33 events; separate model fits.",
            fontsize=10.5,
        )
        fig.savefig(output / "distance-spread-and-event-attribution.png", dpi=180)
        fig.savefig(output / "distance-spread-and-event-attribution.svg")
        plt.close(fig)
        fig, allaxes = plt.subplots(
            4,
            1,
            figsize=(7, 9.5),
            layout="constrained",
            gridspec_kw={"height_ratios": [0.18, 1, 1, 1]},
        )
        legend, axes = allaxes[0], allaxes[1:]
        legend.set_axis_off()
        strata = ["under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"]
        for ax, q in zip(axes, [0.05, 0.5, 0.95], strict=True):
            for name, offset in [("constant", -0.1), ("distance-scale", 0.1)]:
                rows = [
                    next(
                        r
                        for r in checks
                        if r["model"] == name
                        and r["scale"] == "modeled-response"
                        and r["stratum"] == s
                        and r["quantile"] == q
                    )
                    for s in strata
                ]
                med = np.array([r["replicated_q50"] for r in rows])
                lo = np.array([r["replicated_q05"] for r in rows])
                hi = np.array([r["replicated_q95"] for r in rows])
                ax.errorbar(
                    np.arange(4) + offset,
                    med,
                    yerr=[med - lo, hi - med],
                    fmt="o",
                    capsize=3,
                    color=colors[name],
                    label=labels[name],
                )
            ax.scatter(
                range(4),
                [r["observed"] for r in rows],
                color="#111111",
                marker="D",
                label="Observed",
            )
            ax.set_title(f"Sample {q:.0%} quantile of log(reported/reference duration)", loc="left")
            ax.set_xticks(
                range(4),
                [
                    label + f"\nn={int(rows[j]['records'])}"
                    for j, label in enumerate(
                        ["<500 km", "500–2,000 km", "2,000–5,000 km", "≥5,000 km"]
                    )
                ],
                fontsize=10.5,
            )
            ax.set_ylabel("Log duration ratio")
            ax.spines[["top", "right"]].set_visible(False)
        legend.legend(
            *axes[0].get_legend_handles_labels(), loc="center", frameon=False, ncol=3, fontsize=10.5
        )
        fig.suptitle("Distance-specific discrepancies remain", fontsize=14)
        fig.supxlabel(
            "Dots and bars: median and central 90% replicated sample quantiles.\n"
            "Diamonds: observed statistics. Conditional fitted-event checks.\n"
            "Reference duration uses a fixed 4-km-depth speed.\n"
            "Source: NCEI exploration reports and two Bayesian models.",
            fontsize=10.5,
        )
        fig.savefig(output / "conditional-quantile-discrepancies.png", dpi=180)
        fig.savefig(output / "conditional-quantile-discrepancies.svg")
        plt.close(fig)
