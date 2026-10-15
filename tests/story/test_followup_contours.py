"""Contour envelopes describe original stored vertices, not station arrival."""

import math
from pathlib import Path

from analysis.story.contour_followups import contour_references, plot_contour_geometry
from analysis.story.followups import FollowupInputs


def test_contour_references_preserve_parts_hours_and_vertex_extrema(inputs: FollowupInputs) -> None:
    tables = contour_references(inputs)
    originals = {
        c.contour_id: c
        for c in inputs.atlas.contours
        if c.hours in inputs.settings["contour_hours"]
    }
    rows = tables["contour-parts"]
    assert [r["contour_id"] for r in rows] == sorted(originals)
    assert sum(r["vertex_n"] for r in rows) == sum(len(c.coordinates) for c in originals.values())
    for row in rows:
        source = originals[row["contour_id"]]
        assert row["published_hours"] == source.hours
        assert row["vertex_n"] == len(source.coordinates)
        assert row["crs"] == "EPSG:4326"
        assert row["min_longitude"] == min(x for x, _ in source.coordinates)
        assert math.isfinite(row["max_distance_km"])
        assert 0 <= row["min_distance_km"] <= row["max_distance_km"]
        assert "station_id" not in row
    grouped = tables["contour-distance-envelopes"]
    assert [r["published_hours"] for r in grouped] == inputs.settings["contour_hours"]
    assert sum(r["part_n"] for r in grouped) == len(rows)
    assert sum(r["vertex_n"] for r in grouped) == sum(r["vertex_n"] for r in rows)


def test_contour_figure_exports_with_vertex_not_probability_semantics(
    inputs: FollowupInputs, tmp_path: Path
) -> None:
    tables = contour_references(inputs)
    plot_contour_geometry(inputs, tables, tmp_path)
    svg = (tmp_path / "08_contour_geometry.svg").read_text()
    assert "stored vertices" in svg
    assert "not confidence intervals" in svg
    assert (tmp_path / "08_contour_geometry.png").stat().st_size > 1000
