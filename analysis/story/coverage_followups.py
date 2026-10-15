"""Source-grid coverage references for descriptive story diagnostics."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from datetime import datetime, timedelta
from itertools import groupby
from typing import Any

from analysis.story.followups import FollowupInputs
from pipeline.missingness import CoveragePosition


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def coverage_references(inputs: FollowupInputs) -> dict[str, list[dict[str, Any]]]:
    """Slice original source positions into half-open descriptive windows.

    Sample density caps valid sample count at the grid denominator, matching the
    accepted missingness protocol. Off-grid samples never fill a grid position.
    Span endpoints are nearest valid raw samples within the selected window;
    they may be off-grid, and do not imply interpolation or physical onset.
    """
    tables: dict[str, list[dict[str, Any]]] = {
        key: [] for key in ("coverage-by-window", "coverage-spans", "gap-blocks", "off-grid")
    }
    origin = inputs.atlas.event.origin_time_utc
    relative_windows = inputs.settings["event_windows_hours"]
    common_start = _utc(inputs.settings["common_start_utc"])
    common_end = _utc(inputs.settings["common_end_utc"])
    for timeline in sorted(inputs.timelines, key=lambda item: item.station_id):
        source_start, source_end = _utc(timeline.start_utc), _utc(timeline.end_utc_exclusive)
        windows = [
            ("source_full", source_start, source_end),
            ("common_day", common_start, common_end),
        ]
        for start_hour, end_hour in relative_windows:
            start_label = f"minus{abs(start_hour)}" if start_hour < 0 else str(start_hour)
            windows.append(
                (
                    f"event_{start_label}_to_{end_hour}h",
                    origin + timedelta(hours=start_hour),
                    origin + timedelta(hours=end_hour),
                )
            )
        position_times = [_utc(p.expected_at_utc) for p in timeline.positions]
        if len(position_times) != len(set(position_times)):
            raise ValueError(f"duplicate source grid position for {timeline.station_id}")
        for index, timestamp in enumerate(position_times):
            if (
                timestamp != source_start + timedelta(seconds=index * timeline.cadence_seconds)
                or timeline.positions[index].station_id != timeline.station_id
            ):
                raise ValueError(f"invalid original source grid for {timeline.station_id}")
        source_samples: list[dict[str, str]] = []
        for position in timeline.positions:
            if position.status != "absent_timestamp":
                key = (timeline.station_id, position.expected_at_utc)
                if key not in inputs.metadata:
                    raise ValueError(f"missing exact observation metadata for {key}")
                sample = inputs.metadata[key]
                if bool(sample["raw_value"].strip()) != (position.status == "observed"):
                    raise ValueError(f"metadata and grid status differ for {key}")
                source_samples.append(sample)
        for sample in timeline.off_grid:
            key = (timeline.station_id, sample.observed_at_utc)
            if key not in inputs.metadata:
                raise ValueError(f"missing off-grid observation metadata for {key}")
            source_samples.append(inputs.metadata[key])
        source_samples.sort(key=lambda row: _utc(row["observed_at_utc"]))
        for window_id, requested_start, requested_end in windows:
            start, end = max(source_start, requested_start), min(source_end, requested_end)
            positions = tuple(
                p
                for p, timestamp in zip(timeline.positions, position_times, strict=True)
                if start <= timestamp < end
            )
            selected_samples = [
                s for s in source_samples if start <= _utc(s["observed_at_utc"]) < end
            ]
            valid_times = [
                _utc(s["observed_at_utc"]) for s in selected_samples if s["raw_value"].strip()
            ]
            off_grid = [s for s in timeline.off_grid if start <= _utc(s.observed_at_utc) < end]
            counts = Counter(p.status for p in positions)
            expected = len(positions)
            valid_n = counts["observed"]
            valid_samples = len(valid_times)
            metric: dict[str, Any] = {
                "station_id": timeline.station_id,
                "name": timeline.name,
                "window_id": window_id,
                "start_utc": _stamp(requested_start),
                "end_utc_exclusive": _stamp(requested_end),
                "supported_start_utc": _stamp(start) if start < end else "unknown",
                "supported_end_utc_exclusive": _stamp(end) if start < end else "unknown",
                "source_grid_anchor_utc": timeline.start_utc,
                "cadence_seconds": timeline.cadence_seconds,
                "expected_n": expected,
                "exact_valid_n": valid_n,
                "source_blank_n": counts["source_blank"],
                "absent_n": counts["absent_timestamp"],
                "off_grid_n": len(off_grid),
                "off_grid_valid_n": sum(s.raw_value_available for s in off_grid),
                "accepted_sample_n": len(selected_samples),
                "valid_sample_n": valid_samples,
                "strict_numerator_n": valid_n,
                "strict_denominator_n": expected,
                "sample_density_numerator_n": min(valid_samples, expected),
                "sample_density_denominator_n": expected,
                "strict_percent": round(100 * valid_n / expected, 4) if expected else "unknown",
                "sample_density_percent": (
                    round(100 * min(valid_samples, expected) / expected, 4)
                    if expected
                    else "unknown"
                ),
                "first_grid_utc": positions[0].expected_at_utc if positions else "unknown",
                "last_grid_utc": positions[-1].expected_at_utc if positions else "unknown",
                "first_valid_raw_utc": _stamp(valid_times[0]) if valid_times else "unknown",
                "last_valid_raw_utc": _stamp(valid_times[-1]) if valid_times else "unknown",
            }
            tables["coverage-by-window"].append(metric)
            for sample in off_grid:
                row = inputs.metadata[(timeline.station_id, sample.observed_at_utc)]
                tables["off-grid"].append(
                    {
                        "observation_id": row["observation_id"],
                        "station_id": timeline.station_id,
                        "observed_at_utc": row["observed_at_utc"],
                        "source_time": row["source_time"],
                        "raw_value": row["raw_value"] or "unknown",
                        "source_id": row["source_id"],
                        "window_id": window_id,
                        "raw_value_available": sample.raw_value_available,
                    }
                )
            cadence = timedelta(seconds=timeline.cadence_seconds)
            for status, run in groupby(positions, key=lambda p: p.status):
                block = tuple(run)
                tables["coverage-spans"].append(
                    _span(
                        timeline.station_id,
                        window_id,
                        status,
                        block,
                        positions,
                        valid_times,
                        end,
                        cadence,
                    )
                )
            for missing, run in groupby(positions, key=lambda p: p.status != "observed"):
                block = tuple(run)
                if missing:
                    statuses = {p.status for p in block}
                    status = next(iter(statuses)) if len(statuses) == 1 else "mixed_missing"
                    tables["gap-blocks"].append(
                        _span(
                            timeline.station_id,
                            window_id,
                            status,
                            block,
                            positions,
                            valid_times,
                            end,
                            cadence,
                        )
                    )
    return tables


def _span(
    station_id: str,
    window_id: str,
    status: str,
    positions: tuple[CoveragePosition, ...],
    window_positions: tuple[CoveragePosition, ...],
    valid_times: list[datetime],
    window_end: datetime,
    cadence: timedelta,
) -> dict[str, Any]:
    """Describe a position block without treating endpoint separation as its duration."""
    start = _utc(positions[0].expected_at_utc)
    end = min(_utc(positions[-1].expected_at_utc) + cadence, window_end)
    left = bisect_left(valid_times, start)
    right = bisect_left(valid_times, end)
    classification = "observed"
    if status != "observed":
        observed_grid = [p.expected_at_utc for p in window_positions if p.status == "observed"]
        classification = (
            "entire_window"
            if not observed_grid
            else "leading"
            if positions[-1].expected_at_utc < observed_grid[0]
            else "trailing"
            if positions[0].expected_at_utc > observed_grid[-1]
            else "interior"
        )
    counts = Counter(p.status for p in positions)
    return {
        "station_id": station_id,
        "window_id": window_id,
        "status": status,
        "start_utc": _stamp(start),
        "end_utc_exclusive": _stamp(end),
        "affected_position_n": len(positions),
        "source_blank_n": counts["source_blank"],
        "absent_n": counts["absent_timestamp"],
        "classification": classification,
        "classification_semantics": "relative to exact-grid valid positions",
        "within_block_valid_raw_n": right - left,
        "left_observed_utc": _stamp(valid_times[left - 1]) if left else "unknown",
        "right_observed_utc": _stamp(valid_times[right]) if right < len(valid_times) else "unknown",
        "endpoint_semantics": "nearest valid raw observation within selected source overlap",
    }
