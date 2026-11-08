"""Check one mean-curvature prior hypothesis and two distinct wider variants."""

# pyright: basic
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import norm  # noqa: E402

from analysis.arrival.evidence import read_rows, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_prior import (
    VARIANTS,
    read_curvature_prior,
    run_curvature_prior,
)  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size  # noqa: E402

LABELS = {
    "base": "Base: gamma SD 0.5\nOther priors unchanged",
    "gamma_wider_only": "Wider gamma only: SD 0.8\nOther priors unchanged",
    "joint_wider": "Wider gamma and\ninherited priors",
}


def figures(rows, output):
    plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(3, 1, figsize=(8, 13), layout="constrained")
    for ax, variant in zip(axes, VARIANTS, strict=True):
        p = [r for r in rows if r["variant"] == variant and r["quantity"] == "new_event"]
        m = [r for r in rows if r["variant"] == variant and r["quantity"] == "conditional_median"]
        d = np.array([float(r["distance_km"]) for r in p])
        q = np.array(
            [[float(r[k]) for r in p] for k in ["q05_minutes", "q50_minutes", "q95_minutes"]]
        )
        med = np.array(
            [[float(r[k]) for r in m] for k in ["q05_minutes", "q50_minutes", "q95_minutes"]]
        )
        ax.fill_between(
            d,
            q[0],
            q[2],
            color="#286B55",
            alpha=0.12,
            edgecolor="#286B55",
            linewidth=0.8,
            label="New event: 90% prior range",
        )
        ax.plot(d, q[1], color="#286B55", linewidth=1.8, label="New event: prior median")
        ax.plot(
            d,
            med[0],
            color="#777777",
            linestyle="--",
            linewidth=1.2,
            label="Conditional median: 90% prior range",
        )
        ax.plot(d, med[2], color="#777777", linestyle="--", linewidth=1.2)
        ax.set(
            xscale="log",
            yscale="log",
            xlabel="Distance (km; log scale)",
            ylabel="Native reported minutes (log scale)",
            title=LABELS[variant],
        )
        ax.grid(axis="y", alpha=0.15)
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=12, frameon=False)
    fig.suptitle("Curvature allows broad prior timing curves", fontsize=18)
    fig.supxlabel(
        "Analyst hypotheses after EDA; 2,000 ancestral draws per variant.\n"
        "New-event ranges include one shared event effect and record variation.\n"
        "Conditional-median ranges describe uncertain location curves.\n"
        "Source: fixed NCEI exploration distance design; no posterior fit.",
        fontsize=12,
    )
    for suffix in ["png", "svg"]:
        fig.savefig(output / f"curvature-prior-timing-curves.{suffix}", dpi=160)
    plt.close(fig)


def report(root, output):
    rows = read_rows(output / "new-event-duration-prior-quantiles.csv")
    figures(rows, output)
    lines = [
        "# Smooth mean-curvature prior checks",
        "",
        "This is one exploration candidate for source-defined NCEI durations. "
        "The log response adds gamma times b(d) = log1p(500/d) − log1p(0.5) to the "
        "existing distance/event model, retaining its three distance-dependent SD anchors. "
        "The fixed basis is centered at 1,000 km. Gamma = 0 nests the preceding likelihood. "
        "Gamma describes reported-timing curvature; it is not a physical delay.",
        "",
        "Three hypotheses separate widening gamma alone from widening all inherited priors. "
        "They use the same standard Normal draws for easier comparison, rather than "
        "independent Monte Carlo samples. These priors were specified after descriptive EDA.",
        "",
        "| Hypothesis | Gamma SD | Gamma-only 95% median multiplier at 100 km | "
        "Limiting near-distance probability of negative median elasticity |",
        "| --- | ---: | ---: | ---: |",
    ]
    for variant in VARIANTS:
        p = read_curvature_prior(root, variant)
        factor = np.exp(norm.ppf([0.025, 0.975]) * p["gamma_sd"] * np.log(4))
        negative = norm.cdf(-1 / np.sqrt(p["beta_sd"] ** 2 + p["gamma_sd"] ** 2))
        lines.append(
            f"| {variant} | {p['gamma_sd']} | [{factor[0]:.3f}, {factor[1]:.3f}] | {negative:.1%} |"
        )
    lines += [
        "",
        "The local elasticity of the conditional median curve is "
        "1 + beta − gamma × 500/(d + 500). At 1,000 km it is 1 + beta − gamma/3; "
        "beta and gamma can therefore trade off. The limiting negative-elasticity "
        "probability is a prior implication, not a claim about physical propagation. "
        "The basis also changes the far-distance intercept and is not a near-only adjustment.",
        "",
        "At fixed hyperparameters, a new event has median duration t0(d) exp(m(d)) "
        "and mean duration t0(d) exp(m(d) + (sigma(d)^2 + tau^2)/2). The native "
        "mean elasticity additionally contains sigma(d) d sigma(d)/d log(d), away "
        "from the fixed SD anchors. The conditional-median range shown below mixes "
        "over coefficient uncertainty; the new-event range also includes event and "
        "record variation. An arithmetic mean across prior draws is not plotted.",
        "",
        "The joint-wider hypothesis inherits an infinite native second moment from "
        "the wider event-SD prior. Finite Monte Carlo draws do not remove this fact. "
        "Quantiles are reported throughout. The soft ratio yardstick (below 0.05 or "
        "above 20 times the fixed reference) is descriptive and is not an automatic "
        "rejection threshold. Impossible or nonfinite generated values halt the run; "
        "no clipping or redraw is used.",
        "",
        "![Prior durations for new events and uncertainty in conditional medians]"
        "(curvature-prior-timing-curves.png)",
        "",
        "Every original primary record remains eligible, including source-component "
        "flags. These checks authorize no repair or exclusion. The 19 previously "
        "inspected confirmation outcomes have not been reopened during implementation; "
        "the 18 reserved outcomes remain sealed. No candidate posterior has been fitted.",
        "",
        "Recovery and SBC remain required before an actual candidate fit. Numerical "
        "success, plausible prior ranges and a flexible curve establish neither "
        "physical truth nor predictive superiority.",
        "",
        "Tables: [parameter priors](parameter-prior-dictionary.csv), "
        "[native prior quantiles](new-event-duration-prior-quantiles.csv), "
        "[curve implications](mean-curve-prior-quantiles.csv), "
        "[design diagnostics](prior-diagnostics.csv).",
        "",
        "Reproduce: `uv run --locked --offline python scripts/check_arrival_curvature_prior.py "
        "--output <new-project-path> --store <new-project-store>`. The input manifest "
        "and saved-draw hashes identify the exact source and arrays.",
    ]
    (output / "findings.md").write_text("\n".join(lines) + "\n")
    write_json(
        output / "output-checksums.json", {p.name: sha256(p) for p in sorted(output.iterdir())}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / args.output).resolve()
    limit_worker_file_size(64 * 1024**2)
    run_curvature_prior(project, output, (project / args.store).resolve())
    report(project, output)
