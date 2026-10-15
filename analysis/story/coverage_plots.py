# pyright: reportUnknownMemberType=false
"""Coverage figures drawn from the exported source-position reference tables."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from analysis.story.coverage_followups import coverage_references
from analysis.story.followups import FollowupInputs

COLORS = {"observed": "#237c80", "source_blank": "#d19a26", "absent_timestamp": "#d4d4d4"}
LABELS = {
    "observed": "Exact valid raw sample",
    "source_blank": "Source row, blank raw value",
    "absent_timestamp": "Absent grid timestamp",
}


def _time(value: str) -> float:
    return cast(float, mdates.date2num(datetime.fromisoformat(value.replace("Z", "+00:00"))))


def _finish(figure: Figure, inputs: FollowupInputs, output: Path, stem: str) -> list[Path]:
    from analysis.story.followup_plots import save_figure

    origin = inputs.atlas.event.origin_time_utc.isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    figure.text(
        0.02,
        0.02,
        "Source: NOAA CO-OPS, recovered NOAA Saipan archive, IOC sea-level observations; "
        "accepted local cache (2026-10-05 audit).\n"
        f"Tōhoku 2011 · USGS origin {origin} · descriptive coverage only, not onset. "
        "UTC windows; no map projection.\n"
        "Original source minute grid; no interpolation or timestamp snapping. "
        "Black ticks in time strips: off-grid samples, never gap repair.",
        fontsize=12,
    )
    save_figure(figure, output, stem)
    return [output / f"{stem}.png", output / f"{stem}.svg"]


def _strip(
    axis: Axes, references: dict[str, list[dict[str, Any]]], window_id: str, station_ids: list[str]
) -> None:
    for y, station_id in enumerate(station_ids):
        for span in references["coverage-spans"]:
            if span["window_id"] == window_id and span["station_id"] == station_id:
                start, end = _time(span["start_utc"]), _time(span["end_utc_exclusive"])
                axis.broken_barh(
                    [(start, end - start)],
                    (y - 0.28, 0.56),
                    facecolors=COLORS[span["status"]],
                    edgecolors="none",
                )
        off_grid = [
            r
            for r in references["off-grid"]
            if r["window_id"] == window_id and r["station_id"] == station_id
        ]
        axis.scatter(
            [_time(r["observed_at_utc"]) for r in off_grid],
            [y - 0.34] * len(off_grid),
            marker="|",
            color="#333333",
            s=25,
            linewidths=0.8,
            zorder=4,
        )
    axis.set_ylim(len(station_ids) - 0.5, -0.65)
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axis.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    axis.tick_params(labelsize=12)
    axis.set_xlabel("UTC time (11 March 2011)", fontsize=12)
    for spine in axis.spines.values():
        spine.set_visible(False)


def plot_coverage_common_day(
    inputs: FollowupInputs, output: Path, references: dict[str, list[dict[str, Any]]] | None = None
) -> list[Path]:
    """Compare all coastal gauges over one fixed UTC day with explicit denominators."""
    references = references if references is not None else coverage_references(inputs)
    rows = [r for r in references["coverage-by-window"] if r["window_id"] == "common_day"]
    figure, axis = plt.subplots(figsize=(14, 6.5))
    figure.subplots_adjust(left=0.23, right=0.79, top=0.76, bottom=0.27)
    _strip(axis, references, "common_day", [r["station_id"] for r in rows])
    axis.set_xlim(
        _time(inputs.settings["common_start_utc"]), _time(inputs.settings["common_end_utc"])
    )
    axis.set_yticks(range(len(rows)), [f"{r['name']} [{r['station_id']}]" for r in rows])
    for y, row in enumerate(rows):
        axis.text(
            1.015,
            y,
            f"{row['strict_percent']:.2f}%  ({row['exact_valid_n']:,}/{row['expected_n']:,})",
            transform=axis.get_yaxis_transform(),
            va="center",
            fontsize=12,
        )
    figure.suptitle("One UTC day exposes different observation support", fontsize=19, y=0.96)
    figure.text(
        0.23,
        0.86,
        "11 March 2011, [00:00, 24:00) UTC · 1,440 original minute positions per gauge\n"
        "Right: exact-grid valid raw samples / supported grid positions",
        fontsize=12,
    )
    figure.legend(
        handles=[Patch(color=COLORS[s], label=LABELS[s]) for s in COLORS],
        loc="upper center",
        bbox_to_anchor=(0.53, 0.825),
        ncol=3,
        frameon=False,
        fontsize=10,
    )
    axis.text(
        0,
        -0.26,
        "Black ticks above strips: original off-grid samples (valid or blank)",
        transform=axis.transAxes,
        fontsize=10,
    )
    return _finish(figure, inputs, output, "02_coverage_common_day")


def plot_coverage_mechanisms(
    inputs: FollowupInputs, output: Path, references: dict[str, list[dict[str, Any]]] | None = None
) -> list[Path]:
    """Keep source blanks, absent positions and density's off-grid contribution separate."""
    references = references if references is not None else coverage_references(inputs)
    rows = [r for r in references["coverage-by-window"] if r["window_id"] == "common_day"]
    figure, axes = plt.subplots(1, 2, figsize=(14, 6.8), gridspec_kw={"width_ratios": [1.3, 1]})
    left, right = axes
    figure.subplots_adjust(left=0.23, right=0.98, top=0.77, bottom=0.29, wspace=0.26)
    for y, row in enumerate(rows):
        offset = 0
        for status, field in (
            ("observed", "exact_valid_n"),
            ("source_blank", "source_blank_n"),
            ("absent_timestamp", "absent_n"),
        ):
            value = row[field]
            left.barh(y, value, left=offset, color=COLORS[status], height=0.6)
            offset += value
        right.plot([row["strict_percent"], row["sample_density_percent"]], [y, y], color="#888888")
        right.scatter(row["strict_percent"], y, color=COLORS["observed"], marker="o", s=40)
        right.scatter(
            row["sample_density_percent"],
            y,
            facecolors="white",
            edgecolors="#333333",
            marker="s",
            s=35,
        )
        right.text(102, y, f"off-grid {row['off_grid_n']:,}", va="center", fontsize=10)
    left.set_yticks(range(len(rows)), [f"{r['name']} [{r['station_id']}]" for r in rows])
    right.set_yticks([])
    left.set_xlim(0, 1440)
    right.set_xlim(0, 125)
    right.set_xticks([0, 25, 50, 75, 100])
    left.set_xlabel("Original expected grid positions (n = 1,440)", fontsize=12)
    right.set_xlabel("Coverage (%) · denominator 1,440", fontsize=12)
    left.set_title("Three mutually exclusive grid states", fontsize=13, loc="left")
    right.set_title("● Strict   □ Sample density (capped at 100%)", fontsize=12, loc="left")
    for axis in (left, right):
        axis.set_ylim(len(rows) - 0.5, -0.5)
        axis.tick_params(labelsize=11)
        axis.spines[["top", "right", "left"]].set_visible(False)
    figure.suptitle(
        "Missing grid positions and sample density answer different questions", fontsize=18, y=0.96
    )
    figure.text(
        0.23,
        0.87,
        "11 March 2011 · same UTC day; valid off-grid samples enter density only.\n"
        "Blank raw values are not zero. Missingness status is not a causal explanation.",
        fontsize=12,
    )
    figure.legend(
        handles=[Patch(color=COLORS[s], label=LABELS[s]) for s in COLORS],
        loc="lower center",
        bbox_to_anchor=(0.55, 0.16),
        ncol=3,
        frameon=False,
        fontsize=10,
    )
    return _finish(figure, inputs, output, "03_coverage_mechanisms")


def plot_gap_details(
    inputs: FollowupInputs, output: Path, references: dict[str, list[dict[str, Any]]] | None = None
) -> list[Path]:
    """Show the documented Saipan/Pago Pago internal gaps and missing tails."""
    references = references if references is not None else coverage_references(inputs)
    rows = [
        r
        for r in references["coverage-by-window"]
        if r["window_id"] == "source_full" and r["station_id"] in ("saip", "1770000")
    ]
    figure, axes = plt.subplots(2, 1, figsize=(14, 8))
    figure.subplots_adjust(left=0.07, right=0.96, top=0.77, bottom=0.29, hspace=0.8)
    for axis, row in zip(axes, rows, strict=True):
        _strip(axis, references, "source_full", [row["station_id"]])
        axis.set_xlim(_time(row["start_utc"]), _time(row["end_utc_exclusive"]))
        axis.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%d Mar\n%H:%M"))
        axis.set_yticks([])
        axis.set_xlabel("UTC time · original requested source window", fontsize=11)
        gaps = [
            r
            for r in references["gap-blocks"]
            if r["station_id"] == row["station_id"] and r["window_id"] == "source_full"
        ]
        counts = {
            kind: sum(g["affected_position_n"] for g in gaps if g["classification"] == kind)
            for kind in ("leading", "interior", "trailing")
        }
        axis.set_title(
            f"{row['name']} [{row['station_id']}] · missing grid positions: "
            f"leading {counts['leading']:,}; interior {counts['interior']:,}; "
            f"trailing {counts['trailing']:,}",
            fontsize=12,
            loc="left",
            pad=13,
        )
    figure.suptitle("Inter-observation gaps do not account for missing tails", fontsize=19, y=0.96)
    figure.text(
        0.07,
        0.87,
        "Saipan and Pago Pago selected from the previously documented continuity finding.\n"
        "Full source windows are unequal; use the common-day panel for comparisons. "
        "Endpoints and block counts are separate CSV facts.",
        fontsize=12,
    )
    figure.legend(
        handles=[Patch(color=COLORS[s], label=LABELS[s]) for s in COLORS],
        loc="lower center",
        bbox_to_anchor=(0.53, 0.13),
        ncol=3,
        frameon=False,
        fontsize=10,
    )
    return _finish(figure, inputs, output, "04_gap_details")
