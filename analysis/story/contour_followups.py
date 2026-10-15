"""Descriptive distance ranges of original published contour vertices."""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from pyproj import Geod

from analysis.story.followup_plots import save_figure
from analysis.story.followups import FollowupInputs
from pipeline.eda_audit import read_table


def contour_references(inputs: FollowupInputs) -> dict[str, list[dict[str, Any]]]:
    """Distances to stored vertices on WGS84; not a continuous front or arrival."""
    path = next(p for p in inputs.atlas.input_paths if p.name == "ttt_contour.csv")
    metadata = {r["contour_id"]: r for r in read_table(path)}
    geod = Geod(ellps="WGS84")
    event = inputs.atlas.event
    parts: list[dict[str, Any]] = []
    groups: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for line in sorted(inputs.atlas.contours, key=lambda c: c.contour_id):
        if line.hours not in inputs.settings["contour_hours"]:
            continue
        distances = [
            geod.inv(event.longitude, event.latitude, lon, lat)[2] / 1000
            for lon, lat in line.coordinates
        ]
        row = dict(
            contour_id=line.contour_id,
            source_object_id=metadata[line.contour_id]["source_object_id"],
            published_hours=line.hours,
            vertex_n=len(line.coordinates),
            crs=line.crs,
            coordinate_order=line.coordinate_order,
            min_longitude=min(x for x, _ in line.coordinates),
            max_longitude=max(x for x, _ in line.coordinates),
            min_latitude=min(y for _, y in line.coordinates),
            max_latitude=max(y for _, y in line.coordinates),
            longitude_boundary_precision=line.longitude_boundary_precision,
            crosses_antimeridian=line.crosses_antimeridian,
            min_distance_km=min(distances),
            max_distance_km=max(distances),
            distance_reference="USGS origin; WGS84 ellipsoid assumption",
            semantics="stored source vertices only; not a station arrival or confidence interval",
        )
        parts.append(row)
        groups[line.hours].append(row)
    envelopes = [
        dict(
            published_hours=hour,
            part_n=len(rows),
            vertex_n=sum(r["vertex_n"] for r in rows),
            min_distance_km=min(r["min_distance_km"] for r in rows),
            max_distance_km=max(r["max_distance_km"] for r in rows),
            semantics="extrema across stored vertices; not confidence intervals or probabilities",
        )
        for hour, rows in sorted(groups.items())
    ]
    return {"contour-parts": parts, "contour-distance-envelopes": envelopes}


def plot_contour_geometry(
    inputs: FollowupInputs, tables: dict[str, list[dict[str, Any]]], output: Path
) -> None:
    rows = tables["contour-distance-envelopes"]
    fig, ax = plt.subplots(figsize=(13, 7))
    fig.subplots_adjust(left=0.10, right=0.91, top=0.75, bottom=0.24)
    for y, row in enumerate(rows):
        lo, hi = row["min_distance_km"], row["max_distance_km"]
        ax.hlines(y, lo, hi, color="#59656c", linewidth=3)
        ax.scatter([lo, hi], [y, y], color="#59656c", s=25)
        ax.text(
            1.015,
            y,
            f"{row['part_n']} parts",
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=11,
        )
    ax.set_yticks(range(len(rows)), [f"{r['published_hours']:g} h" for r in rows])
    ax.set_ylabel("Published contour hour label", fontsize=12)
    ax.set_xlabel("Geodesic distance from USGS origin to stored vertices (km)", fontsize=12)
    ax.set_xlim(left=0)
    ax.tick_params(labelsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Published hour contours span a range of source distances", fontsize=19, y=0.96)
    fig.text(
        0.10,
        0.84,
        "Nine existing hour classes · line endpoints are extrema of stored vertices, "
        "not confidence intervals.\nNo resampling, speed estimate, station arrival assignment "
        "or inference about bathymetric causes.",
        fontsize=12,
    )
    fig.text(
        0.025,
        0.025,
        "Tōhoku 2011 · USGS origin 2011-03-11 05:46:24.120 UTC\n"
        "Source: NOAA/NCEI published EPSG:4326 contours; accepted cache 2026-10-05. "
        "Source order: longitude, latitude.\n"
        "Distances use WGS84 ellipsoid; no map projection. Tiny boundary roundoff "
        "is retained in source coordinates. Not a continuous-front envelope.",
        fontsize=11,
    )
    save_figure(fig, output, "08_contour_geometry")
