"""Source-preserving references for adaptive story diagnostics."""

from __future__ import annotations

import json
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from analysis.story.artifacts import sha256_file, validate_story_output_path
from analysis.story.atlas import AtlasInputs, load_atlas_inputs
from pipeline.eda import verify_fingerprints
from pipeline.eda_audit import fingerprint, read_table
from pipeline.eda_report import write_csv, write_json
from pipeline.missingness import (
    CoastalCoverageTimeline,
    build_coastal_coverage_timelines,
    load_expected_windows,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FollowupInputs:
    """Verified shared evidence plus exact normalized sample metadata."""

    atlas: AtlasInputs
    timelines: tuple[CoastalCoverageTimeline, ...]
    metadata: dict[tuple[str, str], dict[str, str]]
    shared: dict[str, Any]
    settings: dict[str, Any]
    fingerprints: list[dict[str, str]]


def metadata_index(
    rows: list[dict[str, str]], stations: dict[str, dict[str, str]]
) -> dict[tuple[str, str], dict[str, str]]:
    """Validate exact sample identity and join semantics without altering values."""
    index: dict[tuple[str, str], dict[str, str]] = {}
    ids: set[str] = set()
    for row in rows:
        key = row["station_id"], row["observed_at_utc"]
        station = stations.get(key[0])
        if station is None or any(
            row[k] != station[k] for k in ("source_id", "units", "vertical_reference")
        ):
            raise ValueError("orphan or incompatible observation semantics")
        if key in index or row["observation_id"] in ids:
            raise ValueError("duplicate observation identity")
        index[key] = row
        ids.add(row["observation_id"])
    return index


def load_followup_inputs(
    processed: Path, atlas_run: Path, shared_run: Path, release: Path, config: Path
) -> FollowupInputs:
    """Verify recorded bytes before loading an explicitly named cohort and audit."""
    records: list[dict[str, str]] = []
    for run in (atlas_run, shared_run):
        entries: list[dict[str, str]] = json.loads(
            (run / "inputs.json").read_text(encoding="utf-8")
        )
        verify_fingerprints(ROOT, entries)
        records.extend(entries)
        outputs: list[dict[str, str]] = json.loads(
            (run / "outputs.json").read_text(encoding="utf-8")
        )
        output_root = shared_run if run == shared_run else ROOT
        verify_fingerprints(output_root, outputs)
        records.extend(fingerprint(output_root / r["path"], ROOT) for r in outputs)
        records.extend(fingerprint(run / name, ROOT) for name in ("inputs.json", "outputs.json"))
    decision = json.loads(release.read_text(encoding="utf-8"))
    verify_fingerprints(
        ROOT, [decision[k] for k in ("review_receipt", "input_manifest", "output_manifest")]
    )
    if decision["arrival_comparison_allowed"] is not False:
        raise ValueError("this diagnostic protocol requires descriptive-only release")
    if (
        decision["output_manifest"]["path"]
        != (shared_run / "outputs.json").relative_to(ROOT).as_posix()
    ):
        raise ValueError("release references a different shared run")
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    atlas = load_atlas_inputs(
        processed, ROOT / "artifacts/eda/missingness/missingness-summary.json"
    )
    if (
        atlas.event.event_id != settings["event_id"]
        or sorted(s.station_id for s in atlas.stations) != settings["station_ids"]
    ):
        raise ValueError("event or cohort differs from fixed configuration")
    for path in atlas.input_paths:
        if fingerprint(path, ROOT) not in records:
            raise ValueError("processed table lacks accepted fingerprint")
    rows = read_table(processed / "observation.csv")
    stations = {r["station_id"]: r for r in read_table(processed / "station.csv")}
    metadata = metadata_index(rows, stations)
    shared = json.loads((shared_run / "summary.json").read_text(encoding="utf-8"))
    picks = shared["picks"]
    if (
        len(picks) != 160
        or sorted(s["station_id"] for s in shared["summaries"]) != settings["station_ids"]
    ):
        raise ValueError("shared settings or cohort differ")
    windows = load_expected_windows(ROOT / settings["missingness_config"])
    timelines = build_coastal_coverage_timelines(processed, windows)
    for path in (config, release, ROOT / settings["missingness_config"]):
        records.append(fingerprint(path, ROOT))
    coast = ROOT / settings["coastline"]
    if fingerprint(coast, ROOT) not in records:
        raise ValueError("coastline lacks accepted fingerprint")
    records = sorted({r["path"]: r for r in records}.values(), key=lambda r: r["path"])
    return FollowupInputs(atlas, timelines, metadata, shared, settings, records)


def run_followups(
    inputs: FollowupInputs,
    tasks: tuple[str, ...],
    output: Path,
    *,
    run_id: str = "preview",
    git_sha: str = "unknown",
    command: str = "library diagnostic invocation",
) -> dict[str, Any]:
    """Publish a fresh diagnostic run atomically; unsupported tasks never write."""
    if (
        not tasks
        or not set(tasks) <= {"inputs", "regional", "coverage", "signal", "contours", "synthesis"}
        or len(set(tasks)) != len(tasks)
    ):
        raise ValueError("unsupported diagnostic task")
    if "synthesis" in tasks and not {"regional", "coverage", "signal"} <= set(tasks):
        raise ValueError("synthesis requires regional, coverage and signal diagnostics")
    validate_story_output_path(output.resolve())
    if output.resolve().is_relative_to(ROOT / "context"):
        raise ValueError("scientific outputs must not target private context")
    if output.exists():
        raise FileExistsError(output)
    verify_fingerprints(ROOT, inputs.fingerprints)
    result: dict[str, Any] = dict(
        lane="story",
        evidence_state="preliminary_storyboard_evidence",
        tasks=list(tasks),
        arrival_comparison_allowed=False,
        stations=len(inputs.atlas.stations),
        settings=inputs.settings,
        run_id=run_id,
        git_sha=git_sha,
        command=command,
        randomness="none",
        input_fingerprints=inputs.fingerprints,
        counts={
            "stations": len(inputs.atlas.stations),
            "observations": len(inputs.atlas.observations),
            "contour_parts": len(inputs.atlas.contours),
            "previously_rejected_records": cast(
                dict[str, int], inputs.atlas.accounting["row_counts"]
            )["rejected_record"],
        },
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".followups-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        tables: dict[str, list[dict[str, Any]]] = {}
        metrics: dict[str, Any] = {}
        if "regional" in tasks:
            from analysis.story.followup_plots import plot_regional_context

            metrics["regional"] = plot_regional_context(inputs, stage)
            tables["station-reference"] = regional_reference(inputs)
            tables["label-audit"] = metrics["regional"]["label_audit"]
        if "coverage" in tasks:
            from analysis.story.coverage_followups import coverage_references
            from analysis.story.coverage_plots import (
                plot_coverage_common_day,
                plot_coverage_mechanisms,
                plot_gap_details,
            )

            coverage = coverage_references(inputs)
            tables.update(coverage)
            for plot in (plot_coverage_common_day, plot_coverage_mechanisms, plot_gap_details):
                plot(inputs, stage, coverage)
        if "signal" in tasks:
            from analysis.story.signal_followups import signal_references
            from analysis.story.signal_plots import plot_signal_diagnostics

            signal = signal_references(inputs)
            tables.update(signal)
            plot_signal_diagnostics(inputs, signal, stage)
        if "contours" in tasks:
            from analysis.story.contour_followups import contour_references, plot_contour_geometry

            contours = contour_references(inputs)
            tables.update(contours)
            plot_contour_geometry(inputs, contours, stage)
        for name, rows in tables.items():
            write_csv(stage / f"{name}.csv", rows)
        result.update(tables=tables, metrics=metrics)
        if "synthesis" in tasks:
            from analysis.story.followup_artifacts import write_followup_bundle

            write_followup_bundle(result, stage, run_id, git_sha)
        write_json(stage / "inputs.json", inputs.fingerprints)
        write_json(stage / "summary.json", result)
        write_json(
            stage / "outputs.json",
            [{"path": p.name, "sha256": sha256_file(p)} for p in sorted(stage.iterdir())],
        )
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    return result


def regional_reference(inputs: FollowupInputs) -> list[dict[str, Any]]:
    """Keep the complete cohort and source coordinates; regions are display extents."""
    rows: list[dict[str, Any]] = []
    station_path = next(p for p in inputs.atlas.input_paths if p.name == "station.csv")
    station_metadata = {r["station_id"]: r for r in read_table(station_path)}
    for number, station in enumerate(inputs.atlas.stations, 1):
        regions = [
            name
            for name, (west, east, south, north) in inputs.settings["regions"].items()
            if west <= station.longitude <= east and south <= station.latitude <= north
        ]
        source = next(r for (sid, _), r in inputs.metadata.items() if sid == station.station_id)
        rows.append(
            dict(
                station_id=station.station_id,
                reference_number=number,
                name=station.name,
                type=station.station_type,
                source_id=station.source_id,
                longitude=station.longitude,
                latitude=station.latitude,
                horizontal_datum=station.horizontal_datum,
                vertical_datum=station.vertical_reference,
                units=station.units,
                coordinate_order=station_metadata[station.station_id]["coordinate_order"],
                display_coordinate_order="longitude, latitude",
                source_time_example=source["source_time"],
                region=",".join(regions) or "basin",
            )
        )
    return rows
