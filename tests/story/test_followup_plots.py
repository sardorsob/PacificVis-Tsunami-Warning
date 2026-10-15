"""Reference tables and display geometry must reconcile with the source."""

import json
from pathlib import Path

from analysis.story.followup_plots import plot_regional_context
from analysis.story.followups import FollowupInputs, regional_reference


def test_regional_reference_preserves_all_station_coordinates(inputs: FollowupInputs) -> None:
    rows = regional_reference(inputs)
    assert len(rows) == 10
    assert len({r["station_id"] for r in rows}) == 10
    near = next(r for r in rows if r["station_id"] == "21418")
    assert near["longitude"] == 148.698 and near["latitude"] == 38.718
    assert near["horizontal_datum"] == "unknown"
    assert near["region"] == "japan"


def test_regional_map_exports_accounted_geometry_and_unclipped_labels(
    inputs: FollowupInputs, tmp_path: Path
) -> None:
    result = plot_regional_context(inputs, tmp_path)
    assert (tmp_path / "01_regional_context.png").is_file()
    assert (tmp_path / "01_regional_context.svg").is_file()
    assert result["source_coastline_parts"] == 134
    assert result["projected_line_jumps_over_2000km"] == 0
    assert len(result["label_audit"]) > 10
    assert not any(r["clipped"] for r in result["label_audit"])
    assert not any(r["overlap_count"] for r in result["label_audit"])
    assert result["title_overlap_count"] == 0
    json.dumps(result, allow_nan=False)
