"""Compact paper figures from frozen summary tables; no model or prediction calls."""

# pyright: basic
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
from matplotlib.typing import RcKeyType

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/models/arrival-timing"
SOURCES = {
    "spread": ART / "distance-scale-fit-report-v1/population-mean-and-residual-spread-curves.csv",
    "event": ART / "distance-scale-fit-report-v1/between-event-spread-by-model.csv",
    "scores": ART / "curvature-sequence-predictive-comparison-v1/paired-score-differences.csv",
    "pit": ART / "curvature-sequence-predictive-comparison-v1/event-weighted-pit.csv",
    "arrival": ART / "full-development-figures-v1/plotted-quantiles.csv",
    "summary": ART / "full-development-analysis-v1/summary.json",
}
TEAL = "#176B82"
INK = "#23333B"
GRAY = "#70777C"
LIGHT = "#A3ADB2"
STYLE: dict[RcKeyType, str | int | float | bool] = {
    "font.family": "DejaVu Sans",
    "font.size": 10.5,
    "axes.labelsize": 10.5,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#B4BDC1",
    "axes.linewidth": 0.65,
    "grid.color": "#E3E8EB",
    "grid.linewidth": 0.5,
    "legend.frameon": False,
    "legend.fontsize": 10.5,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
    "svg.hashsalt": "tsunami-paper-figures-v1",
    "axes.unicode_minus": True,
}


def read_rows(name: str) -> list[dict[str, str]]:
    with SOURCES[name].open(newline="") as stream:
        return list(csv.DictReader(stream))


def numbers(rows: list[dict[str, str]], key: str) -> np.ndarray:
    values = np.array([float(row[key]) for row in rows])
    if not np.isfinite(values).all():
        raise ValueError(f"Nonfinite plotted value: {key}")
    return values


def ordered(rows: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    result = sorted(rows, key=lambda row: float(row[key]))
    if len(set(numbers(result, key))) != len(result):
        raise ValueError(f"Duplicate plotted coordinates: {key}")
    return result


def interval(rows: list[dict[str, str]], keys: tuple[str, ...]) -> list[np.ndarray]:
    low, mid, high = [numbers(rows, key) for key in keys]
    if not ((low <= mid) & (mid <= high)).all():
        raise ValueError("Unordered uncertainty interval")
    return [low, mid, high]


def tidy(ax: Axes, *, log_x: bool = False) -> None:
    ax.set_axisbelow(True)
    ax.grid(axis="y")
    ax.tick_params(length=3, width=0.6, pad=3)
    if log_x:
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(FixedLocator([100, 1000, 10000]))
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda value, _: f"{value / 1000:g}k" if value >= 1000 else f"{value:g}")
        )
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xlabel("Distance (km, log)", labelpad=5)


def heading(fig: Figure, title: str, source: str) -> None:
    fig.text(0.02, 0.975, title, va="top", fontsize=13, fontweight="bold")
    fig.text(0.02, 0.015, source, va="bottom", fontsize=10.5, color=GRAY)


def spread_figure() -> tuple[Figure, dict[str, list[dict[str, str]]]]:
    curves, event = read_rows("spread"), read_rows("event")
    assert len(curves) == 248 and len(event) == 2
    fig, axes = plt.subplots(1, 3, figsize=(7, 2.9))
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.24, top=0.70, wspace=0.70)
    heading(
        fig,
        "Event variation depends on residual spread",
        "Source: NOAA NCEI · 90% posterior intervals",
    )
    models = [
        ("constant", "Constant spread", GRAY, "--"),
        ("distance-scale", "Varying spread", TEAL, "-"),
    ]
    for model, label, color, dash in models:
        rows = ordered([row for row in curves if row["model"] == model], "distance_km")
        assert len(rows) == 124
        x = numbers(rows, "distance_km")
        for ax, prefix in zip(axes[:2], ["population_log_ratio", "residual_sd"], strict=True):
            low, mid, high = interval(rows, tuple(f"{prefix}_q{q}" for q in ["05", "50", "95"]))
            ax.fill_between(x, low, high, color=color, alpha=0.14, linewidth=0)
            ax.plot(x, mid, color=color, ls=dash, lw=1.5, label=label)
            ax.set_xlim(50, 20000)
            tidy(ax, log_x=True)
    axes[0].set_title("A  Median", loc="left", pad=9)
    axes[0].set_ylabel("Log duration ratio")
    axes[0].set_yticks([0, 0.4, 0.8])
    axes[1].set_title("B  Residual SD", loc="left", pad=9)
    axes[1].set_ylabel("SD (log ratio)")
    axes[1].set_ylim(0, 0.85)
    axes[1].set_yticks([0, 0.4, 0.8])
    for position, (model, _, color, _) in zip([1, 0], models, strict=True):
        row = next(row for row in event if row["model"] == model)
        low, mid, high = interval([row], ("q05", "q50", "q95"))
        axes[2].errorbar(
            mid,
            [position],
            xerr=[mid - low, high - mid],
            fmt="o",
            color=color,
            capsize=3,
            markersize=4.5,
            elinewidth=1.3,
        )
    axes[2].set_title("C  Event SD", loc="left", pad=9)
    axes[2].set_yticks([1, 0], ["Constant", "Varying"])
    axes[2].set_ylim(-0.6, 1.6)
    axes[2].set_xlim(0, 0.55)
    axes[2].set_xticks([0, 0.25, 0.5], ["0", "0.25", "0.50"])
    axes[2].set_xlabel("Event SD (log ratio)", labelpad=5)
    tidy(axes[2])
    axes[2].grid(False)
    handles = [Line2D([], [], color=c, ls=d, lw=1.5, label=label) for _, label, c, d in models]
    fig.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.08, 0.91),
        ncol=2,
        handlelength=2.3,
        columnspacing=2.0,
    )
    return fig, {"spread-curves.csv": curves, "event-spread.csv": event}


def comparison_figure() -> tuple[Figure, dict[str, list[dict[str, str]]]]:
    score_rows = [row for row in read_rows("scores") if row["first_model"] == "mean-curvature"]
    pit = [row for row in read_rows("pit") if row["stratum"] == "all"]
    assert len(score_rows) == 2 and len(pit) == 303
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.9), gridspec_kw={"width_ratios": [1.2, 1]})
    fig.subplots_adjust(left=0.22, right=0.98, bottom=0.24, top=0.74, wspace=0.65)
    heading(
        fig,
        "Curvature gains remain uncertain",
        "Source: NOAA NCEI · 95% descriptive sequence intervals",
    )
    ax = axes[0]
    for position, baseline in zip([1, 0], ["event", "distance-scale"], strict=True):
        row = next(row for row in score_rows if row["second_model"] == baseline)
        low, mid, high = interval(
            [row],
            (
                "sequence_cluster_ci95_lower",
                "paired_mean_difference",
                "sequence_cluster_ci95_upper",
            ),
        )
        assert low[0] < 0 < high[0]
        ax.errorbar(
            mid,
            [position],
            xerr=[mid - low, high - mid],
            fmt="o",
            color=TEAL,
            capsize=3,
            markersize=4.8,
            elinewidth=1.4,
        )
    ax.axvline(0, color=GRAY, lw=0.8, ls="--", zorder=0)
    ax.set_xlim(-0.2, 1.15)
    ax.set_xticks([0, 0.5, 1])
    ax.set_ylim(-0.65, 1.65)
    ax.set_yticks([1, 0], ["Linear mean,\nconstant spread", "Linear mean,\nvarying spread"])
    ax.set_xlabel("Score difference (nats/report)", labelpad=5)
    ax.set_title("A  Curved minus linear", loc="left", pad=9)
    tidy(ax)
    ax.grid(False)
    ax = axes[1]
    ax.plot([0, 1], [0, 1], color="#BEC6CA", lw=0.9, zorder=0)
    bands = []
    for model, color, dash, label in [
        ("event", "#626B70", (0, (1, 2)), "Linear · constant"),
        ("distance-scale", "#555E63", (0, (5, 3)), "Linear · varying"),
        ("mean-curvature", TEAL, "-", "Curved · varying"),
    ]:
        rows = ordered([row for row in pit if row["model"] == model], "pit_probability")
        assert len(rows) == 101
        x, y = numbers(rows, "pit_probability"), numbers(rows, "equal_event_cdf")
        assert (np.diff(y) >= 0).all() and ((0 <= y) & (y <= 1)).all()
        if model == "mean-curvature":
            radius = numbers(rows, "bootstrap_supnorm_radius95")
            assert len(set(radius)) == 1
            low, high = np.clip(y - radius, 0, 1), np.clip(y + radius, 0, 1)
            ax.fill_between(
                x,
                low,
                high,
                facecolor=to_rgba(TEAL, 0.12),
                edgecolor="none",
                linewidth=0,
            )
            bands = [
                {
                    "pit_probability": str(a),
                    "cdf": str(b),
                    "band_low": str(c),
                    "band_high": str(d),
                    "supnorm_radius95": str(e),
                }
                for a, b, c, d, e in zip(x, y, low, high, radius, strict=True)
            ]
        ax.plot(
            x,
            y,
            color=color,
            ls=dash,
            lw=1.7 if model == "mean-curvature" else 1.3,
            marker="s" if model == "event" else "D" if model == "distance-scale" else None,
            markevery=20 if model == "event" else (10, 20),
            ms=3.2,
            markerfacecolor="white",
            markeredgewidth=0.8,
            label=label,
        )
    ax.set_title("B  Predictive CDF", loc="left", pad=9)
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Predicted probability", ylabel="Event-weighted CDF")
    ax.set_xticks([0, 0.5, 1])
    ax.set_yticks([0, 0.5, 1])
    ax.set_aspect("equal", adjustable="box")
    tidy(ax)
    fig.legend(
        *ax.get_legend_handles_labels(),
        loc="upper left",
        bbox_to_anchor=(0.08, 0.93),
        ncol=3,
        handlelength=2.1,
        columnspacing=1.2,
    )
    return fig, {"paired-scores.csv": score_rows, "pit-curves.csv": pit, "pit-band.csv": bands}


def arrival_figure() -> tuple[Figure, dict[str, list[dict[str, str]]]]:
    rows = read_rows("arrival")
    summary = json.loads(SOURCES["summary"].read_text())
    assert len(rows) == 54
    fig, axes = plt.subplots(1, 3, figsize=(7, 3.0))
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.24, top=0.70, wspace=0.52)
    heading(
        fig,
        "New-report intervals are wider",
        "Source: NOAA NCEI / NTWC · central 90% pointwise intervals",
    )
    targets = [
        ("NCEI-native-duration", "A  NCEI duration"),
        ("T-OBS", "B  NTWC duration"),
        ("T-CAL", "C  Difference"),
    ]
    for ax, (target, title), lane in zip(axes, targets, summary["lanes"], strict=True):
        median = ordered(
            [
                row
                for row in rows
                if row["target"] == target and row["curve"] == "population_median"
            ],
            "distance_km",
        )
        prediction = ordered(
            [row for row in rows if row["target"] == target and row["curve"] == "new_event"],
            "distance_km",
        )
        assert len(median) == len(prediction) == 9
        x = numbers(median, "distance_km")
        assert np.array_equal(x, numbers(prediction, "distance_km"))
        low, mid, high = interval(median, ("q05", "q50", "q95"))
        plow, _, phigh = interval(prediction, ("q05", "q50", "q95"))
        if target != "T-CAL":
            assert (low > 0).all() and (plow > 0).all()
            ax.set_yscale("log")
            ax.set_ylim(0.5, 5000)
            ax.yaxis.set_major_locator(FixedLocator([1, 10, 100, 1000]))
            ax.yaxis.set_major_formatter(
                FuncFormatter(
                    lambda value, _: f"{value / 1000:g}k" if value >= 1000 else f"{value:g}"
                )
            )
            ax.yaxis.set_minor_locator(NullLocator())
            ax.set_ylabel("Minutes (log)")
        else:
            ax.set_ylim(-90, 100)
            ax.set_yticks([-50, 0, 50])
            ax.axhline(0, color=GRAY, lw=0.75, ls="--")
            ax.set_ylabel("Estimate − obs. (min)")
        assert ax.get_ylim()[0] <= min(low.min(), plow.min())
        assert ax.get_ylim()[1] >= max(high.max(), phigh.max())
        ax.fill_between(x, plow, phigh, facecolor=LIGHT, alpha=0.24, linewidth=0)
        ax.plot(x, plow, color=GRAY, lw=0.7, ls=":")
        ax.plot(x, phigh, color=GRAY, lw=0.7, ls=":")
        ax.fill_between(x, low, high, color=TEAL, alpha=0.45, linewidth=0)
        ax.plot(x, mid, color=TEAL, lw=1.45, marker="o", ms=2.4)
        support = lane["support"]
        for lo, hi in [(20, support["distance_km_min"]), (support["distance_km_max"], 20000)]:
            ax.axvspan(
                lo, hi, facecolor="none", edgecolor="#A8B0B4", hatch="////", linewidth=0, zorder=0
            )
        ax.set_xlim(20, 20000)
        ax.set_title(title, loc="left", pad=9)
        tidy(ax, log_x=True)
    handles = [
        Line2D([], [], color=TEAL, lw=1.4, marker="o", ms=3, label="Median"),
        Patch(facecolor=TEAL, alpha=0.45, label="Median interval"),
        Patch(facecolor=LIGHT, alpha=0.3, label="Report interval"),
        Patch(facecolor="none", edgecolor=GRAY, hatch="////", label="Extrapolation"),
    ]
    fig.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.055, 0.91),
        ncol=4,
        columnspacing=1.1,
        handlelength=1.6,
    )
    return fig, {"arrival-quantiles.csv": rows}


def make_figures() -> list[tuple[str, Figure, dict[str, list[dict[str, str]]]]]:
    with plt.rc_context():
        plt.rcParams.update(STYLE)
        return [
            ("residual-spread-and-event-variation", *spread_figure()),
            ("sequence-prediction-and-probability-check", *comparison_figure()),
            ("median-and-new-report-intervals", *arrival_figure()),
        ]


def render(output: Path) -> None:
    # Keep text metrics stable while rendering every format, including small previews.
    with plt.rc_context():
        plt.rcParams.update(STYLE)
        output.mkdir(parents=True, exist_ok=False)
        inputs = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in SOURCES.values()
        }
        inputs[str(Path(__file__).resolve().relative_to(ROOT))] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        for name, fig, tables in make_figures():
            fig.savefig(output / f"{name}-preview.png", dpi=600 / 7)
            for extension in ["png", "pdf", "svg"]:
                metadata = {"CreationDate": None, "ModDate": None} if extension == "pdf" else None
                if extension == "svg":
                    metadata = {"Date": None}
                fig.savefig(output / f"{name}.{extension}", dpi=300, metadata=metadata)
            for filename, table in tables.items():
                with (output / filename).open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(table[0]))
                    writer.writeheader()
                    writer.writerows(table)
            plt.close(fig)
        source_after = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in SOURCES.values()
        }
        source_after[str(Path(__file__).resolve().relative_to(ROOT))] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        assert inputs == source_after
        (output / "inputs.json").write_text(json.dumps(inputs, indent=2, sort_keys=True) + "\n")
        outputs = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.iterdir())
        }
        (output / "output-checksums.json").write_text(
            json.dumps(outputs, indent=2, sort_keys=True) + "\n"
        )
        print(f"Rendered three compact figures and exact plotted data to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True, type=Path)
    render(parser.parse_args().output_directory.resolve())
