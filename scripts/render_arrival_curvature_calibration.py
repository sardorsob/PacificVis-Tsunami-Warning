"""Render final discrete SBC rank diagnostics from immutable report tables."""

# pyright: basic
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_curve_checks import (  # noqa: E402
    GRID_KM,
    sbc_rank_ecdf_screen,
)

QUANTITIES = (
    "alpha",
    "beta",
    "gamma",
    "tau_event",
    "sigma_500km",
    "sigma_2000km",
    "sigma_5000km",
    "sigma_1000km",
    "event_effect_first",
    "median_elasticity_1000km",
    "median_ratio_100km",
    "predictive_log_SD_1000km",
    *(f"log_median_ratio_{d:g}km" for d in GRID_KM),
)
REPORT_FILES = {
    "inputs.json",
    "estimates-by-dataset.csv",
    "sampling-and-functional-diagnostics.csv",
    "pointwise-coverage-and-recovery.csv",
    "grid-band-by-dataset.csv",
    "grid-band-coverage.csv",
    "final-discrete-rank-ecdf-screen.csv",
    "metrics.json",
    "findings.md",
}


def rank_lines(rows):
    names = sorted({r["parameter"] for r in rows})
    if set(names) != set(QUANTITIES):
        raise ValueError("the exact twelve scalar and nine grid quantities are required")
    grid = np.arange(101)
    output = []
    for name in names:
        group = [r for r in rows if r["parameter"] == name]
        if len(group) != 100 or {r["case_id"] for r in group} != {
            f"sbc-{j:03d}" for j in range(100)
        }:
            raise ValueError("100 independent dataset identities required for each rank")
        ranks = np.array([int(r["rank"]) for r in group])
        check = sbc_rank_ecdf_screen(ranks)
        output.append(
            {
                "parameter": name,
                "difference": np.mean(ranks[:, None] <= grid, axis=0) - (grid + 1) / 101,
                "maximum": check["max_discrete_ecdf_difference"],
                "halfwidth": check["dkw_union_halfwidth"],
            }
        )
    return grid, output


def render(root, report, output):
    if output.exists() or not report.is_relative_to(root) or not output.is_relative_to(root):
        raise ValueError("existing project report and new project output required")
    checksums = json.loads((report / "output-checksums.json").read_text())
    if set(checksums) != REPORT_FILES or any(Path(n).name != n for n in checksums):
        raise ValueError("complete contained report-science checksum coverage required")
    for name, digest in checksums.items():
        if sha256(report / name) != digest:
            raise ValueError("source report changed")
    inputs = json.loads((report / "inputs.json").read_text())
    if inputs["phase"] != "sbc" or inputs["datasets"] != 100:
        raise ValueError("final100-datasetSBC report required; no interim uniformity screen")
    for name, digest in inputs["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("frozen source report input changed")
    with (report / "estimates-by-dataset.csv").open() as stream:
        grid, lines = rank_lines(list(csv.DictReader(stream)))
    output.mkdir(parents=True)
    plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), sharey=True)
    bound = lines[0]["halfwidth"]
    limit = max(bound * 1.27, max(r["maximum"] for r in lines) * 1.27)
    for ax, curve in zip(axes, [False, True], strict=True):
        group = [r for r in lines if r["parameter"].startswith("log_median_ratio_") == curve]
        worst = max(group, key=lambda r: r["maximum"])
        ax.axhspan(-bound, bound, color="#f2f2f2", zorder=0)
        ax.axhline(0, color="#555555", linewidth=0.8)
        for row in group:
            ax.plot(grid, row["difference"], color="#a4a4a4", alpha=0.75, linewidth=0.9)
        ax.plot(grid, worst["difference"], color="#0072B2", linewidth=2)
        for y in [-bound, bound]:
            ax.axhline(y, color="#777777", linewidth=1, linestyle="--")
        label = worst["parameter"].replace("log_median_ratio_", "curve at ").replace("_", " ")
        ax.text(
            0.02,
            0.96,
            f"Largest deviation: {label}\n{worst['maximum']:.1%}",
            transform=ax.transAxes,
            va="top",
            fontsize=11,
            color="#005581",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.95, "pad": 3},
        )
        ax.set(
            title="Nine population-median curve values" if curve else "Twelve scalar quantities",
            xlabel="Rank among 100 spaced posterior states",
            xlim=(0, 100),
            ylim=(-limit, limit),
        )
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(axis="y", color="#dedede", linewidth=0.5)
    axes[0].set_ylabel("Empirical CDF − discrete uniform CDF")
    fig.suptitle("Simulation ranks: deviations from the discrete reference", fontsize=18, y=0.97)
    fig.text(
        0.08,
        0.89,
        f"100 synthetic datasets · 21 correlated quantities · family DKW bounds ±{bound:.1%}",
        fontsize=12,
    )
    fig.text(
        0.08,
        0.09,
        "Gray lines: individual quantities. Blue: largest deviation in each panel. "
        "Bounds use a 21-quantity union correction.",
        fontsize=11,
    )
    fig.text(
        0.08,
        0.055,
        "Source: NCEI exploration design (1,064 records / 33 events), frozen priors "
        "and 100 simulated datasets.",
        fontsize=10,
    )
    fig.text(
        0.08,
        0.025,
        "Four × 2,000 retained MCMC draws; 100 spaced states per rank approximate "
        "independent draws.",
        fontsize=10,
    )
    fig.subplots_adjust(left=0.08, right=0.98, top=0.78, bottom=0.23, wspace=0.12)
    image = output / "final-discrete-rank-deviations.png"
    fig.savefig(image, dpi=130)
    fig.savefig(output / "final-discrete-rank-deviations.svg")
    plt.close(fig)
    write_json(
        output / "inputs.json",
        {
            "files": {
                **{str((report / n).relative_to(root)): h for n, h in checksums.items()},
                str((report / "output-checksums.json").relative_to(root)): sha256(
                    report / "output-checksums.json"
                ),
                "scripts/render_arrival_curvature_calibration.py": sha256(
                    root / "scripts/render_arrival_curvature_calibration.py"
                ),
                "analysis/arrival/model_curvature_curve_checks.py": sha256(
                    root / "analysis/arrival/model_curvature_curve_checks.py"
                ),
            },
            "brief": "Takeaway: show all final rank deviations and the finite family bound; "
            "Audience: expert; Destination: report",
            "alt_text": "Two panels show empirical rank CDF differences for twelve scalar "
            "quantities and nine on-grid median-curve values, with simultaneous "
            "reference bounds and the largest deviation highlighted.",
        },
    )
    write_json(
        output / "output-checksums.json",
        {str(p.relative_to(output)): sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    render(root, (root / args.report).resolve(), (root / args.output).resolve())
