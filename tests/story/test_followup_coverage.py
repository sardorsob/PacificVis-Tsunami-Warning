"""Coverage contracts: count source positions, never re-anchor to event origin."""

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from analysis.story.coverage_followups import coverage_references
from analysis.story.coverage_plots import (
    plot_coverage_common_day,
    plot_coverage_mechanisms,
    plot_gap_details,
)
from analysis.story.followups import FollowupInputs
from pipeline.missingness import (
    CoastalCoverageTimeline,
    CoveragePosition,
    CoverageStatus,
    OffGridObservation,
)


def test_common_day_counts_reconcile_and_full_windows_match_accepted(
    inputs: FollowupInputs,
) -> None:
    references = coverage_references(inputs)
    common = [r for r in references["coverage-by-window"] if r["window_id"] == "common_day"]
    assert len(common) == 6
    assert {r["expected_n"] for r in common} == {1440}
    for row in references["coverage-by-window"]:
        assert row["exact_valid_n"] + row["source_blank_n"] + row["absent_n"] == row["expected_n"]
        assert row["strict_denominator_n"] == row["expected_n"]
        assert row["sample_density_denominator_n"] == row["expected_n"]
        spans = [
            s
            for s in references["coverage-spans"]
            if (s["station_id"], s["window_id"]) == (row["station_id"], row["window_id"])
        ]
        gaps = [
            s
            for s in references["gap-blocks"]
            if (s["station_id"], s["window_id"]) == (row["station_id"], row["window_id"])
        ]
        assert sum(s["affected_position_n"] for s in spans) == row["expected_n"]
        assert sum(s["absent_n"] + s["source_blank_n"] for s in gaps) == (
            row["absent_n"] + row["source_blank_n"]
        )
    accepted = {
        r["station_id"]: r
        for r in cast(list[dict[str, Any]], inputs.atlas.missingness_summary["coastal_windows"])
    }
    for row in references["coverage-by-window"]:
        if row["window_id"] == "source_full":
            original = accepted[row["station_id"]]
            assert row["expected_n"] == original["expected_positions"]
            assert row["off_grid_n"] == original["off_grid_rows"]
            assert row["strict_percent"] == original["strict_coverage_percent"]
            assert row["sample_density_percent"] == original["sample_density_coverage_percent"]


def test_fractional_origin_windows_slice_existing_minute_grid(inputs: FollowupInputs) -> None:
    rows = coverage_references(inputs)["coverage-by-window"]
    selected = [r for r in rows if r["window_id"] == "event_0_to_6h"]
    assert len(selected) == 6
    assert {r["expected_n"] for r in selected} == {360}
    assert {r["first_grid_utc"] for r in selected} == {"2011-03-11T05:47:00Z"}
    assert {r["last_grid_utc"] for r in selected} == {"2011-03-11T11:46:00Z"}
    assert {r["start_utc"] for r in selected} == {"2011-03-11T05:46:24.120000Z"}
    assert all(r["source_grid_anchor_utc"].endswith("T00:00:00Z") for r in selected)


def test_missing_edges_zero_off_grid_and_half_open_boundaries(inputs: FollowupInputs) -> None:
    station = inputs.timelines[0].station_id
    times = [f"2011-03-11T00:0{i}:00Z" for i in range(6)]
    states: list[CoverageStatus] = [
        "absent_timestamp",
        "observed",
        "source_blank",
        "absent_timestamp",
        "observed",
        "absent_timestamp",
    ]
    timeline = CoastalCoverageTimeline(
        station,
        "Fixture",
        times[0],
        "2011-03-11T00:06:00Z",
        60,
        tuple(CoveragePosition(station, t, s) for t, s in zip(times, states, strict=True)),
        (OffGridObservation(station, "2011-03-11T00:01:30Z", True),),
    )
    metadata = {}
    for index in (1, 2, 4):
        metadata[(station, times[index])] = {
            "observation_id": f"sample-{index}",
            "station_id": station,
            "observed_at_utc": times[index],
            "source_time": f"original-{index}",
            "raw_value": "" if index == 2 else "0",
            "source_id": "fixture-source",
        }
    metadata[(station, "2011-03-11T00:01:30Z")] = {
        "observation_id": "unsnapped",
        "station_id": station,
        "observed_at_utc": "2011-03-11T00:01:30Z",
        "source_time": "unaltered",
        "raw_value": "0",
        "source_id": "fixture-source",
    }
    settings = {**inputs.settings, "common_start_utc": times[1], "common_end_utc": times[4]}
    fixture = replace(inputs, timelines=(timeline,), metadata=metadata, settings=settings)
    references = coverage_references(fixture)
    full, common = references["coverage-by-window"][:2]
    assert (
        full["expected_n"],
        full["exact_valid_n"],
        full["source_blank_n"],
        full["absent_n"],
        full["off_grid_n"],
    ) == (6, 2, 1, 3, 1)
    assert full["sample_density_percent"] == 50
    assert (common["expected_n"], common["exact_valid_n"], common["absent_n"]) == (3, 1, 1)
    gaps = [r for r in references["gap-blocks"] if r["window_id"] == "source_full"]
    assert [r["classification"] for r in gaps] == ["leading", "interior", "trailing"]
    assert [r["affected_position_n"] for r in gaps] == [1, 2, 1]
    assert gaps[0]["left_observed_utc"] == "unknown"
    assert gaps[0]["right_observed_utc"] == times[1]
    assert gaps[-1]["left_observed_utc"] == times[4]
    assert gaps[-1]["right_observed_utc"] == "unknown"
    off_grid = references["off-grid"][0]
    assert (off_grid["observation_id"], off_grid["source_time"], off_grid["raw_value"]) == (
        "unsnapped",
        "unaltered",
        "0",
    )
    assert gaps[1]["within_block_valid_raw_n"] == 0
    no_grid = replace(
        timeline, positions=tuple(replace(p, status="absent_timestamp") for p in timeline.positions)
    )
    no_grid_refs = coverage_references(replace(fixture, timelines=(no_grid,)))
    whole = next(g for g in no_grid_refs["gap-blocks"] if g["window_id"] == "source_full")
    assert whole["classification"] == "entire_window"
    assert whole["within_block_valid_raw_n"] == 1


def test_off_grid_inside_missing_grid_block_is_not_a_grid_repair(inputs: FollowupInputs) -> None:
    references = coverage_references(inputs)
    gaps = [
        g
        for g in references["gap-blocks"]
        if g["station_id"] == "saip"
        and g["window_id"] == "common_day"
        and g["start_utc"] == "2011-03-11T00:53:00Z"
    ]
    assert len(gaps) == 1
    assert gaps[0]["absent_n"] == 15
    assert gaps[0]["within_block_valid_raw_n"] == 14


def test_missing_metadata_is_rejected(inputs: FollowupInputs) -> None:
    metadata = dict(inputs.metadata)
    timeline = next(t for t in inputs.timelines if t.off_grid)
    metadata.pop((timeline.station_id, timeline.off_grid[0].observed_at_utc))
    with pytest.raises(ValueError, match="metadata"):
        coverage_references(replace(inputs, metadata=metadata))


def test_coverage_plots_export_reference_values(inputs: FollowupInputs, tmp_path: Path) -> None:
    references = coverage_references(inputs)
    paths: list[Path] = []
    for plot in (plot_coverage_common_day, plot_coverage_mechanisms, plot_gap_details):
        paths.extend(plot(inputs, tmp_path, references))
    assert len(paths) == 6
    assert all(p.is_file() and p.stat().st_size > 1000 for p in paths)
    common_svg = (tmp_path / "02_coverage_common_day.svg").read_text(encoding="utf-8")
    for row in references["coverage-by-window"]:
        if row["window_id"] == "common_day":
            assert row["station_id"] in common_svg
            assert f"{row['strict_percent']:.2f}%" in common_svg
    assert "05:46:24.120" in common_svg
    assert "UTC" in common_svg
