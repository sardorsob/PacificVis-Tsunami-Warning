import csv
import hashlib
import json
from pathlib import Path

import pytest
from mlflow import MlflowClient

from analysis.story.artifacts import load_decision_input
from analysis.story.atlas import AtlasError
from scripts.story.build_story_atlas import main as atlas_main

PLOT_IDS = (
    "01_pacific_evidence_map",
    "02_observation_coverage",
    "03_station_timeseries",
    "04_distance_contour_diagnostic",
)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _stage_cli_fixture(root: Path) -> dict[str, Path]:
    processed = root / "accepted-fixture"
    processed.mkdir()
    _write_csv(
        processed / "event.csv",
        ("event_id", "origin_time_utc", "latitude", "longitude", "status"),
        [
            {
                "event_id": "official20110311054624120_30",
                "origin_time_utc": "2011-03-11T05:46:24.120Z",
                "latitude": "38.297",
                "longitude": "142.373",
                "status": "reviewed",
            }
        ],
    )
    _write_csv(
        processed / "station.csv",
        (
            "station_id",
            "source_id",
            "station_type",
            "name",
            "latitude",
            "longitude",
            "availability",
            "units",
            "vertical_reference",
            "horizontal_datum",
            "time_basis",
        ),
        [
            {
                "station_id": "coast",
                "source_id": "coastal-source",
                "station_type": "coastal",
                "name": "Coastal fixture",
                "latitude": "20.0",
                "longitude": "-155.0",
                "availability": "approved",
                "units": "m",
                "vertical_reference": "STND",
                "horizontal_datum": "unknown",
                "time_basis": "GMT",
            },
            {
                "station_id": "dart",
                "source_id": "dart-source",
                "station_type": "dart",
                "name": "DART fixture",
                "latitude": "30.0",
                "longitude": "150.0",
                "availability": "approved",
                "units": "m water column",
                "vertical_reference": "unknown",
                "horizontal_datum": "unknown",
                "time_basis": "UTC",
            },
        ],
    )
    _write_csv(
        processed / "observation.csv",
        (
            "observation_id",
            "station_id",
            "source_time",
            "observed_at_utc",
            "raw_value",
            "residual_value",
            "units",
            "vertical_reference",
        ),
        [
            {
                "observation_id": "coast-observed",
                "station_id": "coast",
                "source_time": "2011-03-11 05:46",
                "observed_at_utc": "2011-03-11T05:46:00Z",
                "raw_value": "0",
                "residual_value": "",
                "units": "m",
                "vertical_reference": "STND",
            },
            {
                "observation_id": "coast-off-grid",
                "station_id": "coast",
                "source_time": "2011-03-11 05:46:59",
                "observed_at_utc": "2011-03-11T05:46:59Z",
                "raw_value": "1",
                "residual_value": "",
                "units": "m",
                "vertical_reference": "STND",
            },
            {
                "observation_id": "coast-blank",
                "station_id": "coast",
                "source_time": "2011-03-11 05:48",
                "observed_at_utc": "2011-03-11T05:48:00Z",
                "raw_value": "",
                "residual_value": "",
                "units": "m",
                "vertical_reference": "STND",
            },
            {
                "observation_id": "dart-observed",
                "station_id": "dart",
                "source_time": "2011 03 11 05 46 24",
                "observed_at_utc": "2011-03-11T05:46:24Z",
                "raw_value": "10",
                "residual_value": "1",
                "units": "m water column",
                "vertical_reference": "unknown",
            },
        ],
    )
    _write_csv(
        processed / "ttt_contour.csv",
        (
            "contour_id",
            "hours",
            "coordinates",
            "crs",
            "coordinate_order",
            "longitude_boundary_precision",
            "crosses_antimeridian",
        ),
        [
            {
                "contour_id": "one-a",
                "hours": "1",
                "coordinates": json.dumps([[170.0, 0.0], [179.0, 1.0]]),
                "crs": "EPSG:4326",
                "coordinate_order": "longitude, latitude",
                "longitude_boundary_precision": "false",
                "crosses_antimeridian": "false",
            },
            {
                "contour_id": "six-a",
                "hours": "6",
                "coordinates": json.dumps([[-170.0, 0.0], [-160.0, 1.0]]),
                "crs": "EPSG:4326",
                "coordinate_order": "longitude, latitude",
                "longitude_boundary_precision": "false",
                "crosses_antimeridian": "false",
            },
        ],
    )
    (processed / "accounting.json").write_text(
        json.dumps(
            {
                "row_counts": {"event": 1, "station": 2, "observation": 4, "ttt_contour": 2},
                "rejection_counts": {"api_or_record_rejection": 0, "blocked_source": 1},
            }
        ),
        encoding="utf-8",
    )

    missingness_config = root / "missingness.toml"
    missingness_config.write_text(
        """[windows.coast]
station_id = "coast"
name = "Coastal fixture"
start_utc = "2011-03-11T05:46:00Z"
end_utc_exclusive = "2011-03-11T05:49:00Z"
cadence_seconds = 60
""",
        encoding="utf-8",
    )
    missingness_summary = root / "missingness-summary.json"
    missingness_summary.write_text(
        json.dumps(
            {
                "coastal_windows": [
                    {
                        "station_id": "coast",
                        "name": "Coastal fixture",
                        "strict_coverage_percent": 33.3333,
                        "sample_density_coverage_percent": 66.6667,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    coastline = root / "coastline.geojson"
    coastline.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-10.0, -20.0], [10.0, 20.0]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[30.0, -20.0], [40.0, 20.0]],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    atlas_config = root / "story-atlas.toml"
    atlas_config.write_text(
        """schema_version = "1"
event_id = "official20110311054624120_30"
evidence_state = "preliminary_storyboard_evidence"
display_crs = "+proj=eqearth +lon_0=-160 +datum=WGS84 +units=m +no_defs +type=crs"
central_meridian = -160.0
start_hours = -6.0
end_hours = 30.0
highlighted_contour_hours = [1, 6]
range_radii_km = [2500]
dart_station_ids = ["dart"]
coastal_station_ids = ["coast"]
figure_dpi = 160
""",
        encoding="utf-8",
    )
    return {
        "processed": processed,
        "missingness_config": missingness_config,
        "missingness_summary": missingness_summary,
        "coastline": coastline,
        "atlas_config": atlas_config,
    }


def _cli_args(paths: dict[str, Path], root: Path) -> list[str]:
    return [
        "--processed-dir",
        str(paths["processed"]),
        "--missingness-config",
        str(paths["missingness_config"]),
        "--missingness-summary",
        str(paths["missingness_summary"]),
        "--coastline",
        str(paths["coastline"]),
        "--config",
        str(paths["atlas_config"]),
        "--artifact-dir",
        str(root / "artifacts"),
        "--run-dir",
        str(root / "run"),
        "--report",
        str(root / "EDA_REPORT.md"),
        "--run-id",
        "fixture-story-atlas",
        "--git-sha",
        "abc1234",
        "--working-tree",
        "clean",
        "--mlflow-dir",
        str(root / "mlflow"),
        "--mlflow-experiment",
        "fixture-story-eda",
    ]


def _replace_arg(arguments: list[str], flag: str, value: Path) -> list[str]:
    updated = arguments.copy()
    updated[updated.index(flag) + 1] = str(value)
    return updated


def _write_decision_input(
    path: Path,
    *,
    plot_ids: tuple[str, ...] = PLOT_IDS,
    disposition: str = "retain",
    manual_qa: str = "Checked at full size and thumbnail size.",
) -> None:
    lines = [
        'schema_version = "1"',
        'evidence_state = "preliminary_storyboard_evidence"',
        'reviewer = "Fixture reviewer"',
        'review_date = "2026-09-16"',
    ]
    for index, plot_id in enumerate(plot_ids, start=1):
        lines.extend(
            [
                "",
                "[[decisions]]",
                f'plot_id = "{plot_id}"',
                f'observation = "Observed fixture result {index}."',
                f'question = "Review question {index}?"',
                f'follow_up = "Review follow-up {index}."',
                f'result = "Reviewed fixture result {index}."',
                f'disposition = "{disposition}"',
                'storyboard_implication = "No promotion from fixture review."',
                f'manual_qa = "{manual_qa}"',
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_writes_story_only_atlas_evidence_and_mlflow_run(tmp_path: Path) -> None:
    paths = _stage_cli_fixture(tmp_path)
    artifact_dir = tmp_path / "artifacts"
    run_dir = tmp_path / "run"
    report_path = tmp_path / "EDA_REPORT.md"
    tracking_dir = tmp_path / "mlflow"

    result = atlas_main(_cli_args(paths, tmp_path))

    assert result == 0
    assert {path.name for path in artifact_dir.iterdir()} == {
        "01_pacific_evidence_map.png",
        "01_pacific_evidence_map.svg",
        "02_observation_coverage.png",
        "02_observation_coverage.svg",
        "03_station_timeseries.png",
        "03_station_timeseries.svg",
        "04_distance_contour_diagnostic.png",
        "04_distance_contour_diagnostic.svg",
        "atlas-manifest.json",
        "decision-ledger.csv",
    }
    assert {path.name for path in run_dir.iterdir()} == {
        "config.json",
        "inputs.json",
        "meta.json",
        "metrics.json",
        "notes.md",
        "outputs.json",
    }
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["lane"] == "story"
    assert meta["evidence_state"] == "preliminary_storyboard_evidence"
    report = report_path.read_text(encoding="utf-8")
    assert "No story claim has been promoted" in report
    assert "`retain` preview" in report
    assert "Inspect all four figures" in report
    manifest_text = (artifact_dir / "atlas-manifest.json").read_text(encoding="utf-8")
    assert "paper" not in manifest_text.lower()

    client = MlflowClient(tracking_uri=tracking_dir.resolve().as_uri())
    experiment = client.get_experiment_by_name("fixture-story-eda")
    assert experiment is not None
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    tags = runs[0].data.tags
    assert tags["lane"] == "story"
    assert tags["evidence_state"] == "preliminary_storyboard_evidence"
    assert tags["portable_run_id"] == "fixture-story-atlas"
    assert len(tags["input_fingerprint_sha256"]) == 64


def test_cli_uses_reviewed_decisions_verbatim_and_reconciles_manifest(tmp_path: Path) -> None:
    paths = _stage_cli_fixture(tmp_path)
    decision_input = tmp_path / "decisions.toml"
    _write_decision_input(decision_input)
    arguments = [*_cli_args(paths, tmp_path), "--decision-input", str(decision_input)]

    assert atlas_main(arguments) == 0

    artifact_dir = tmp_path / "artifacts"
    manifest = json.loads((artifact_dir / "atlas-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["artifacts"]) == 8
    required_keys = {
        "artifact_id",
        "title",
        "question",
        "lane",
        "generating_command",
        "git_sha",
        "candidate_build_id",
        "input_checksums",
        "projection",
        "time_basis",
        "units",
        "longitude_handling",
        "input_count",
        "output_count",
        "rejection_count",
        "path",
        "media_type",
        "dimensions",
        "sha256",
        "evidence_state",
        "finding",
        "limitation",
        "disposition",
        "storyboard_implication",
        "manual_qa",
    }
    decision_hash = _sha256(decision_input)
    for record in manifest["artifacts"]:
        assert required_keys <= set(record)
        artifact_path = Path(record["path"])
        assert artifact_path.is_file()
        assert record["sha256"] == _sha256(artifact_path)
        assert any(item["sha256"] == decision_hash for item in record["input_checksums"])
    ledger = (artifact_dir / "decision-ledger.csv").read_text(encoding="utf-8")
    report = (tmp_path / "EDA_REPORT.md").read_text(encoding="utf-8")
    assert "Observed fixture result 1." in ledger
    assert "Reviewed fixture result 4." in report
    assert "`retain` preview" not in report
    assert "Inspect all four figures" not in report
    assert "Hand this preliminary atlas to the independent Checker" in report
    headings = [
        "## Run and evidence state",
        "## Inputs and source boundary",
        "## Fixed diagnostic atlas",
        "## Adaptive decision ledger",
        "## Interpretation",
        "## Limitations",
        "## Takeaways",
        "## Next steps",
        "## Input and output fingerprints",
    ]
    assert [report.index(heading) for heading in headings] == sorted(
        report.index(heading) for heading in headings
    )


@pytest.mark.parametrize(
    ("plot_ids", "disposition", "manual_qa", "match"),
    [
        (PLOT_IDS[:-1], "retain", "Checked.", "each atlas plot"),
        ((*PLOT_IDS[:-1], PLOT_IDS[-2]), "retain", "Checked.", "each atlas plot"),
        (PLOT_IDS, "promote", "Checked.", "Stage A disposition"),
        (PLOT_IDS, "retain", "", "manual_qa"),
    ],
)
def test_decision_input_rejects_incomplete_or_promoting_review(
    tmp_path: Path,
    plot_ids: tuple[str, ...],
    disposition: str,
    manual_qa: str,
    match: str,
) -> None:
    decision_input = tmp_path / "decisions.toml"
    _write_decision_input(
        decision_input,
        plot_ids=plot_ids,
        disposition=disposition,
        manual_qa=manual_qa,
    )

    with pytest.raises(AtlasError, match=match):
        load_decision_input(decision_input)


@pytest.mark.parametrize("existing_flag", ["--artifact-dir", "--run-dir"])
def test_cli_refuses_existing_output_directories_without_partial_output(
    tmp_path: Path, existing_flag: str
) -> None:
    paths = _stage_cli_fixture(tmp_path)
    arguments = _cli_args(paths, tmp_path)
    existing = Path(arguments[arguments.index(existing_flag) + 1])
    existing.mkdir()

    with pytest.raises(SystemExit):
        atlas_main(arguments)

    other_flag = "--run-dir" if existing_flag == "--artifact-dir" else "--artifact-dir"
    assert not Path(arguments[arguments.index(other_flag) + 1]).exists()
    assert not (tmp_path / "EDA_REPORT.md").exists()


@pytest.mark.parametrize("paper_folder", ["paper", "arrival-timing"])
def test_cli_rejects_lane_crossing_output_path(tmp_path: Path, paper_folder: str) -> None:
    paths = _stage_cli_fixture(tmp_path)
    forbidden = tmp_path / "artifacts" / "eda" / paper_folder / "atlas"
    arguments = _replace_arg(_cli_args(paths, tmp_path), "--artifact-dir", forbidden)

    with pytest.raises(SystemExit):
        atlas_main(arguments)

    assert not forbidden.exists()
    assert not (tmp_path / "run").exists()


def test_cli_missing_input_or_mismatched_event_leaves_no_partial_output(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    missing_paths = _stage_cli_fixture(missing_root)
    missing_paths["coastline"].unlink()
    with pytest.raises(SystemExit):
        atlas_main(_cli_args(missing_paths, missing_root))
    assert not (missing_root / "artifacts").exists()
    assert not (missing_root / "run").exists()

    mismatch_root = tmp_path / "mismatch"
    mismatch_root.mkdir()
    mismatch_paths = _stage_cli_fixture(mismatch_root)
    mismatch_paths["atlas_config"].write_text(
        mismatch_paths["atlas_config"]
        .read_text(encoding="utf-8")
        .replace("official20110311054624120_30", "wrong-event"),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        atlas_main(_cli_args(mismatch_paths, mismatch_root))
    assert not (mismatch_root / "artifacts").exists()
    assert not (mismatch_root / "run").exists()
