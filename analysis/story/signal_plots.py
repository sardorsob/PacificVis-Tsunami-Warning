"""Plot frozen evidence without joining unlike fields or validating an onset."""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.transforms import Bbox

from analysis.story.followup_plots import save_figure
from analysis.story.followups import FollowupInputs


def control_crossing_hours(
    inputs: FollowupInputs, tables: dict[str, list[dict[str, Any]]], sid: str
) -> list[float]:
    """Shared control elapsed seconds use its search start, not earthquake origin."""
    return sorted(
        {
            (
                datetime.fromisoformat(p["candidate_utc"].replace("Z", "+00:00"))
                - inputs.atlas.event.origin_time_utc
            ).total_seconds()
            / 3600
            for p in tables["setting-reference"]
            if p["station_id"] == sid and p["window"] == "control" and p["status"] == "candidate"
        }
    )


def _finish(fig: Figure, output: Path, stem: str) -> None:
    fig.text(
        0.025,
        0.025,
        "Tōhoku 2011 · origin 2011-03-11 05:46:24.120 UTC · accepted audit 2026-10-05\n"
        "Sources: NOAA/NCEI DART residuals, NOAA CO-OPS raw levels, "
        "IOC source-QC flags; NCTR account.\n"
        "No projection; source datums retained. No interpolation, tide removal, "
        "new detector or physical arrival assignment.",
        fontsize=11,
    )
    save_figure(fig, output, stem)


def _samples(ax: Axes, rows: list[dict[str, Any]], unit: str, divisor: float) -> None:
    valid = [r for r in rows if r["value"] != "unknown"]
    ax.scatter(
        [r["elapsed_seconds"] / divisor for r in valid],
        [float(r["value"]) for r in valid],
        s=9,
        color="#59656c",
        label="Original sample",
    )
    flagged = [r for r in valid if r["qc_flagged"]]
    if flagged:
        ax.scatter(
            [r["elapsed_seconds"] / divisor for r in flagged],
            [float(r["value"]) for r in flagged],
            s=25,
            marker="x",
            color="#a13c36",
            label="Source-QC flagged (retained)",
        )
    ax.set_ylabel(unit, fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=11)


def plot_signal_diagnostics(
    inputs: FollowupInputs, tables: dict[str, list[dict[str, Any]]], output: Path
) -> None:
    """Three separate questions: support, independent contradiction, controls/QC."""
    support = tables["signal-support"]
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.19, top=0.76)
    ax.axis("off")
    body = [
        [
            f"{r['name']} [{r['station_id']}]",
            r["field"],
            f"{r['detected_settings']}/{r['total_settings']}",
            str(r["control_crossings"]),
            str(r["control_unevaluable"]),
            "pass" if r["mechanical_screen_pass"] else "fail",
            "conflicts" if "conflicts" in r["external_validation"] else "not validated",
            str(r["source_qc_count"]),
        ]
        for r in support
    ]
    table = ax.table(
        cellText=body,
        colLabels=[
            "Station",
            "Field",
            "Event\ncrossings",
            "Control\ncrossings",
            "Control\nunevaluable",
            "Mechanical\nscreen",
            "External\nvalidation",
            "Source QC\nflagged n",
        ],
        colWidths=[0.25, 0.09, 0.10, 0.10, 0.12, 0.10, 0.15, 0.09],
        bbox=Bbox.from_bounds(0, 0, 1, 1),
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#dddddd")
        cell.set_facecolor("#e9edef" if row == 0 else "white")
    fig.suptitle("A mechanical screen does not validate tsunami timing", fontsize=20, y=0.96)
    fig.text(
        0.025,
        0.85,
        "Ten stations · 80 frozen event settings and 80 pre-origin controls; "
        "failed settings retained.\n"
        "DART uses publisher residuals (retrospective fit window unknown); "
        "coastal records are raw tidal levels.\n"
        "No station has a validated physical onset or available modeled "
        "station arrival in this release.",
        fontsize=12,
    )
    _finish(fig, output, "05_signal_support_matrix")

    fig, ax = plt.subplots(figsize=(13, 6))
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.24, top=0.73)
    dart = [r for r in tables["signal-windows"] if r["station_id"] == "21418"]
    _samples(ax, dart, "Publisher residual (m water column)\nVertical datum unknown", 60)
    candidates = sorted(
        {
            p["candidate_elapsed_seconds"] / 60
            for p in tables["setting-reference"]
            if p["station_id"] == "21418" and p["window"] == "event" and p["status"] == "candidate"
        }
    )
    for n, minute in enumerate(candidates):
        ax.axvline(
            minute,
            color="#985512",
            linestyle="--",
            linewidth=1.2,
            label="Frozen threshold candidates" if n == 0 else None,
        )
    # A point and approximate label, not an invented exact time line or uncertainty interval.
    ax.annotate(
        "NOAA account: approximately 25 min\n(not an exact pick)",
        xy=(25, 0.95),
        xycoords=("data", "axes fraction"),
        ha="center",
        fontsize=12,
    )
    ax.set_xlim(-5, 60)
    ax.set_xlabel("Minutes after USGS origin (UTC) · [-5, +60)", fontsize=12)
    ax.legend(loc="lower right", fontsize=10, frameon=False)
    fig.suptitle(
        "DART 21418: an early crossing conflicts with the source account", fontsize=18, y=0.96
    )
    fig.text(
        0.09,
        0.82,
        f"Frozen candidates: {min(candidates):.3f}–{max(candidates):.3f} min. "
        "Early signal mechanism is unclassified; this is not a tsunami arrival.",
        fontsize=12,
    )
    _finish(fig, output, "06_early_crossing_context")

    fig, axes = plt.subplots(2, 1, figsize=(13, 9))
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.2, top=0.80, hspace=0.75)
    for ax, sid, title, unit in (
        (
            axes[0],
            "9461380",
            "Adak [9461380] · raw tidal levels; 4/8 pre-origin controls cross",
            "Raw water level (m) · STND",
        ),
        (
            axes[1],
            "valp",
            "Valparaíso [valp] · source-QC flags retained, including a raw zero",
            "Raw water level (m)\nVertical datum unknown",
        ),
    ):
        rows = [r for r in tables["signal-windows"] if r["station_id"] == sid]
        _samples(ax, rows, unit, 3600)
        ax.set_title(title, loc="left", fontsize=12, pad=12)
        ax.set_xlabel("Hours relative to USGS origin (UTC)", fontsize=12)
        if sid == "9461380":
            ax.set_xlim(-5, 0)
            for n, hour in enumerate(control_crossing_hours(inputs, tables, sid)):
                ax.axvline(
                    hour,
                    color="#985512",
                    linestyle="--",
                    linewidth=1,
                    label="Frozen pre-origin crossings" if n == 0 else None,
                )
        ax.legend(loc="upper left", fontsize=10, frameon=False)
    fig.suptitle("Complete observations can still be unsuitable for timing", fontsize=19, y=0.96)
    fig.text(
        0.09,
        0.875,
        "Separate axes and datums · points only, no lines across missing support.\n"
        "Coastal raw levels retain tides; source flags describe quality, "
        "not missingness mechanism.",
        fontsize=12,
    )
    _finish(fig, output, "07_control_and_qc_context")
