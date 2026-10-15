"""Static diagnostics rendered from explicit reference tables."""
# pyright: reportUnknownMemberType=false
# Matplotlib methods expose untyped keyword arguments in the pinned stubs.

from __future__ import annotations

from math import hypot
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.text import Annotation, Text  # noqa: E402
from pyproj import Transformer  # noqa: E402

from analysis.story.atlas import (  # noqa: E402
    project_line_parts,
    shift_longitude,
    split_at_display_seam,
)
from analysis.story.followups import ROOT, FollowupInputs, regional_reference  # noqa: E402
from analysis.story.plots import (
    _load_coastline_parts,  # noqa: E402 # pyright: ignore[reportPrivateUsage]
)


def save_figure(fig: Any, output: Path, stem: str) -> None:
    """Export stable PNG/SVG without timestamps or random SVG identifiers."""
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output / f"{stem}.png", dpi=160)
    fig.savefig(output / f"{stem}.svg", metadata={"Date": None})
    plt.close(fig)


def plot_regional_context(inputs: FollowupInputs, output: Path) -> dict[str, Any]:
    """Separate basin orientation from local labels using the same projection."""
    crs = inputs.settings["display_crs"]
    coast = _load_coastline_parts(ROOT / inputs.settings["coastline"])
    parts = tuple(piece for part in coast for piece in split_at_display_seam(part))
    projected = project_line_parts(parts, crs)
    contours = tuple(
        piece
        for line in inputs.atlas.contours
        if line.hours in inputs.settings["contour_hours"]
        for piece in split_at_display_seam(line.coordinates)
    )
    contour_xy = project_line_parts(contours, crs)
    transform = Transformer.from_crs("EPSG:4326", crs, always_xy=True, force_over=True)
    rows = regional_reference(inputs)
    audits: list[dict[str, Any]] = []
    with plt.rc_context({"font.size": 12, "svg.hashsalt": "story-followup-v1"}):
        fig = plt.figure(figsize=(12, 10))
        canvas_agg = FigureCanvasAgg(fig)
        fig.subplots_adjust(left=0.04, right=0.97, top=0.88, bottom=0.10)
        grid = fig.add_gridspec(2, 2, height_ratios=[1.5, 1], hspace=0.16, wspace=0.12)
        axes = [
            fig.add_subplot(grid[0, :]),
            fig.add_subplot(grid[1, 0]),
            fig.add_subplot(grid[1, 1]),
        ]
        heading = fig.suptitle(
            "One Pacific record needs both basin and regional context",
            x=0.04,
            ha="left",
            fontsize=17,
        )
        panel_titles: list[Text] = []
        for panel, ax in zip(["basin", "japan", "california"], axes, strict=True):
            ax.add_collection(LineCollection(projected, colors="#626c70", linewidths=0.7))
            ax.add_collection(LineCollection(contour_xy, colors="#628392", linewidths=0.5))
            ax.autoscale_view()
            ax.set_aspect("equal")
            labels: list[tuple[str, Annotation]] = []
            if panel != "basin":
                west, east, south, north = inputs.settings["regions"][panel]
                xy = [
                    transform.transform(shift_longitude(lon), lat)
                    for lon in (west, east)
                    for lat in (south, north)
                ]
                ax.set_xlim(min(x for x, _ in xy), max(x for x, _ in xy))
                ax.set_ylim(min(y for _, y in xy), max(y for _, y in xy))
            for row in rows:
                if panel != "basin" and row["region"] != panel:
                    continue
                x, y = transform.transform(shift_longitude(row["longitude"]), row["latitude"])
                dart = row["type"] == "dart"
                ax.scatter(
                    [x],
                    [y],
                    marker="^" if dart else "o",
                    s=45 if panel == "basin" else 65,
                    color="#985512" if dart else "#176578",
                    edgecolor="#27343b",
                    zorder=4,
                )
                label = (
                    str(row["reference_number"])
                    if panel == "basin"
                    else f"{row['name']} ({row['station_id']})"
                )
                offset = (8, 8)
                ha = "left"
                if panel == "california" or row["station_id"] == "21413" and panel == "japan":
                    offset = (-8, 8)
                    ha = "right"
                if panel == "basin" and row["station_id"] == "46411":
                    offset = (-12, -18)
                    ha = "right"
                if panel == "basin" and row["station_id"] == "21418":
                    offset = (10, 14)
                if panel == "basin" and row["station_id"] == "21413":
                    offset = (10, -18)
                annotation = ax.annotate(
                    label,
                    (x, y),
                    xytext=offset,
                    textcoords="offset points",
                    ha=ha,
                    fontsize=11 if panel == "basin" else 12,
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.3},
                )
                labels.append((row["station_id"], annotation))
            event = inputs.atlas.event
            if panel in ("basin", "japan"):
                x, y = transform.transform(shift_longitude(event.longitude), event.latitude)
                ax.scatter(
                    [x], [y], marker="*", s=160, color="#92334c", edgecolor="#27343b", zorder=5
                )
                if panel == "japan":
                    labels.append(
                        (
                            "origin",
                            ax.annotate(
                                "USGS origin",
                                (x, y),
                                xytext=(-8, -25),
                                textcoords="offset points",
                                ha="right",
                                fontsize=12,
                                bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.3},
                            ),
                        )
                    )
            panel_titles.append(
                ax.set_title(
                    {
                        "basin": "All ten stations · numbered reference in CSV",
                        "japan": "Japan region · source and nearby DART records",
                        "california": "California region · coastal and DART records",
                    }[panel],
                    loc="left",
                    fontsize=12,
                )
            )
            ax.set_axis_off()
            canvas_agg.draw()
            renderer = canvas_agg.get_renderer()
            boxes = [ann.get_window_extent(renderer) for _, ann in labels]
            canvas = fig.bbox
            for i, (label_id, _) in enumerate(labels):
                box = boxes[i]
                overlaps = [labels[j][0] for j, b in enumerate(boxes) if i != j and box.overlaps(b)]
                audits.append(
                    dict(
                        artifact_id="01_regional_context",
                        panel=panel,
                        label_id=label_id,
                        display_width_px=1000,
                        overlap_count=len(overlaps),
                        overlap_partners=",".join(overlaps) or "none",
                        clipped=not (
                            canvas.contains(box.x0, box.y0) and canvas.contains(box.x1, box.y1)
                        ),
                    )
                )
        fig.text(
            0.04,
            0.02,
            "2011 Tōhoku · origin 2011-03-11 05:46:24.120 UTC · Pacific Equal Earth (160°W)\n"
            "Source: USGS, NOAA/NCEI contours and stations, Natural Earth 1:110m coastline.\n"
            "Triangles: DART; circles: coastal. Horizontal station datums unknown; regional zooms.",
            fontsize=10.5,
        )
        canvas_agg.draw()
        renderer = canvas_agg.get_renderer()
        title_box = heading.get_window_extent(renderer)
        title_overlap_count = int(
            sum(title_box.overlaps(title.get_window_extent(renderer)) for title in panel_titles)
        )
        save_figure(fig, output, "01_regional_context")
    jumps = sum(
        hypot(b[0] - a[0], b[1] - a[1]) > 2_000_000
        for part in (*projected, *contour_xy)
        for a, b in zip(part, part[1:], strict=False)
    )
    return dict(
        source_coastline_parts=len(coast),
        projected_coastline_parts=len(projected),
        source_contour_parts=sum(
            c.hours in inputs.settings["contour_hours"] for c in inputs.atlas.contours
        ),
        projected_contour_parts=len(contour_xy),
        projected_line_jumps_over_2000km=jumps,
        label_audit=audits,
        title_overlap_count=title_overlap_count,
    )
