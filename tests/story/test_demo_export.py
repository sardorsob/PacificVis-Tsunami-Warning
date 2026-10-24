"""Browser exports fail closed and preserve source evidence, not fixtures."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from analysis.story import demo_export


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "source"
    event = {
        "event_id": "event",
        "origin_time_utc": "2011-03-11T05:46:24.120Z",
        "latitude": "38.297",
        "longitude": "142.373",
        "status": "reviewed",
    }
    _csv(root / "processed/event.csv", [event])
    stations = [
        dict(
            station_id=sid,
            source_id=f"source-{sid}",
            station_type=kind,
            name=sid,
            latitude="19.7",
            longitude="-155",
            availability="approved",
            units=unit,
            vertical_reference=datum,
            horizontal_datum="unknown",
            coordinate_order="latitude, longitude",
            time_basis="UTC",
        )
        for sid, kind, unit, datum in [
            ("coast", "coastal", "m", "STND"),
            ("dart", "dart", "m water column", "unknown"),
        ]
    ]
    _csv(root / "processed/station.csv", stations)
    observations: list[dict[str, str]] = []
    for index, (sid, at, raw, residual, extra) in enumerate(
        [
            ("coast", "00:00:00", "0", "", '{"out_of_range":"T","token":"SECRET"}'),
            ("coast", "00:01:00", "", "", ""),
            ("coast", "00:02:59", "2.263", "", ""),
            ("dart", "00:00:00", "5662.37331", "-0.01457", "0.000"),
            ("dart", "00:15:00", "5662.4", "0", "0.000"),
        ]
    ):
        station = next(s for s in stations if s["station_id"] == sid)
        observations.append(
            dict(
                observation_id=f"obs-{index}",
                station_id=sid,
                source_id=station["source_id"],
                source_time=f"original-{index}",
                observed_at_utc=f"2011-03-11T{at}Z",
                raw_value=raw,
                fitted_value="",
                residual_value=residual,
                source_extra=extra,
                units=station["units"],
                vertical_reference=station["vertical_reference"],
            )
        )
    _csv(root / "processed/observation.csv", observations)
    coverage = dict(
        station_id="coast",
        window_id="common_day",
        start_utc="2011-03-11T00:00:00Z",
        end_utc_exclusive="2011-03-12T00:00:00Z",
        accepted_sample_n="3",
        valid_sample_n="2",
        expected_n="1440",
        cadence_seconds="60",
        source_grid_anchor_utc="2011-03-11T00:00:00Z",
        strict_numerator_n="1",
        strict_denominator_n="1440",
        strict_percent="0.0694",
        absent_n="1438",
        source_blank_n="1",
        off_grid_n="1",
        off_grid_valid_n="1",
        sample_density_numerator_n="2",
        sample_density_denominator_n="1440",
        sample_density_percent="0.1389",
    )
    _csv(
        root / "followup/coverage-by-window.csv",
        [coverage, {**coverage, "window_id": "source_full"}],
    )
    for name in ("coverage-spans", "gap-blocks"):
        _csv(
            root / f"followup/{name}.csv",
            [
                dict(
                    station_id="coast",
                    window_id="common_day",
                    start_utc="2011-03-11T00:02:00Z",
                    end_utc_exclusive="2011-03-11T00:03:00Z",
                    status="absent_timestamp",
                    absent_n="1",
                    source_blank_n="0",
                )
            ],
        )
    _csv(
        root / "provenance.csv",
        [
            dict(
                source_id=f"source-{sid}",
                publisher="Publisher",
                title="Record",
                url="https://example.org/archive?token=SECRET",
                accessed_on="2026-10-24",
                license_or_terms="internal only",
                version_or_date="v1",
                processing_level="raw",
                sha256="a" * 64,
                local_path="/Users/private/SECRET",
                notes="SECRET",
            )
            for sid in ("coast", "dart")
        ],
    )
    _json(
        root / "coast.json",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "LineString", "coordinates": [[179, 0], [-179, 1]]},
                }
            ],
        },
    )
    _json(root / "shared-inputs.json", [])
    _json(root / "shared-outputs.json", [])
    _json(root / "receipt.json", {"status": "accepted"})
    release: dict[str, Any] = dict(
        schema_version=1,
        release_id="descriptive",
        arrival_comparison_allowed=False,
        physical_arrival_records_released=0,
        continuous_nctr_field="blocked_no_proxy",
        allowed_uses=["descriptive_data_quality"],
        prohibited_uses=["operational_warning"],
    )
    for key, name in [
        ("input_manifest", "shared-inputs.json"),
        ("output_manifest", "shared-outputs.json"),
        ("review_receipt", "receipt.json"),
    ]:
        release[key] = dict(path=name, sha256=_hash(root / name))
    _json(root / "release.json", release)
    accepted = [
        dict(path=p.relative_to(root).as_posix(), sha256=_hash(p))
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.relative_to(root).as_posix().startswith("followup/")
    ]
    _json(root / "followup/inputs.json", accepted)
    outputs = [
        dict(path=f"{name}.csv", sha256=_hash(root / f"followup/{name}.csv"))
        for name in ("coverage-by-window", "coverage-spans", "gap-blocks")
    ]
    _json(root / "followup/outputs.json", outputs)
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                'schema_version = "1"',
                'bundle_id = "test-v1"',
                'event_id = "event"',
                'station_ids = ["coast", "dart"]',
                "expected_observation_count = 5",
                'selected_station_id = "coast"',
                'pinned_station_id = "dart"',
                'default_window_id = "common_day"',
                'default_product_key = "raw_value"',
                'processed = "processed"',
                'followup = "followup"',
                'release = "release.json"',
                'provenance = "provenance.csv"',
                'coastline = "coast.json"',
                f'inputs_sha256 = "{_hash(root / "followup/inputs.json")}"',
                f'outputs_sha256 = "{_hash(root / "followup/outputs.json")}"',
                f'release_sha256 = "{_hash(root / "release.json")}"',
                f'provenance_sha256 = "{_hash(root / "provenance.csv")}"',
                "[[windows]]",
                'id = "common_day"',
                'label = "Common UTC day"',
                'start_utc = "2011-03-11T00:00:00Z"',
                'end_utc_exclusive = "2011-03-12T00:00:00Z"',
            ]
        ),
        encoding="utf-8",
    )
    return root, config


def _build(source: tuple[Path, Path], output: Path) -> Path:
    root, config = source
    return demo_export.export_demo_bundle(source_root=root, output_root=output, config_path=config)


def test_deterministic_non_overwrite_and_preserved_evidence(
    source: tuple[Path, Path], tmp_path: Path
):
    first = _build(source, tmp_path / "one")
    second = _build(source, tmp_path / "two")
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*.json")} == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*.json")
    }
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["accounting"]["source_observation_count"] == 5
    assert manifest["release"]["arrival_comparison_allowed"] is False
    dependencies = {r["path"]: r["sha256"] for r in manifest["input_fingerprints"]}
    for name in ("coverage-by-window", "coverage-spans", "gap-blocks"):
        relative = f"followup/{name}.csv"
        assert dependencies[relative] == _hash(source[0] / relative)
    assert manifest["config_sha256"] == _hash(source[1])
    coast = json.loads((first / "stations/coast.json").read_text())
    rows = [dict(zip(coast["columns"], row, strict=True)) for row in coast["rows"]]
    assert rows[0]["raw_value"] == 0
    assert rows[0]["qc_flags"]["out_of_range"] == "T"
    assert rows[1]["raw_value"] is None
    assert rows[2]["grid_status"] == "off_grid"
    assert coast["support"][0]["strict_denominator_n"] == 1440
    dart = json.loads((first / "stations/dart.json").read_text())
    assert dart["support"][0]["strict_percent"] is None
    assert dart["support"][0]["cadence_seconds_counts"] == [{"seconds": 900, "count": 1}]
    assert b"SECRET" not in b"".join(p.read_bytes() for p in first.rglob("*.json"))
    assert manifest["stations"][0]["source"]["url"] is None
    for asset in manifest["assets"]:
        assert _hash(first / asset["path"]) == asset["sha256"]
    with pytest.raises(FileExistsError):
        _build(source, tmp_path / "one")


def test_changed_source_bytes_fail_without_publication(source: tuple[Path, Path], tmp_path: Path):
    (source[0] / "processed/observation.csv").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        _build(source, tmp_path / "out")
    assert not (tmp_path / "out/test-v1").exists()


def test_missing_cache_fails_without_fixture_fallback(source: tuple[Path, Path], tmp_path: Path):
    with pytest.raises((ValueError, FileNotFoundError)):
        demo_export.export_demo_bundle(
            source_root=tmp_path / "missing", output_root=tmp_path / "out", config_path=source[1]
        )


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "nonfinite", "schema"])
def test_invalid_rows_rejected_after_fingerprint_validation(
    source: tuple[Path, Path],
    tmp_path: Path,
    mutation: str,
):
    root, config = source
    path = root / "processed/observation.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if mutation == "unknown":
        rows[0]["station_id"] = "unknown"
    elif mutation == "duplicate":
        rows[1]["observation_id"] = rows[0]["observation_id"]
    elif mutation == "nonfinite":
        rows[0]["raw_value"] = "NaN"
    else:
        for row in rows:
            del row["raw_value"]
    _csv(path, rows)
    inputs = root / "followup/inputs.json"
    records = json.loads(inputs.read_text())
    next(record for record in records if record["path"] == "processed/observation.csv")[
        "sha256"
    ] = _hash(path)
    old_hash = _hash(inputs)
    _json(inputs, records)
    config.write_text(config.read_text().replace(old_hash, _hash(inputs)), encoding="utf-8")
    with pytest.raises(ValueError):
        _build(source, tmp_path / "out")
    assert not (tmp_path / "out/test-v1").exists()


def test_incomplete_write_is_not_published(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(demo_export, "_write_json", fail)
    with pytest.raises(OSError, match="disk full"):
        _build(source, tmp_path / "out")
    assert not (tmp_path / "out/test-v1").exists()
    assert list((tmp_path / "out").iterdir()) == []


def _resign(source: tuple[Path, Path], changed: Path) -> None:
    """Model a separately reviewed fixture revision, not an unchecked corruption."""
    root, config = source
    inputs = root / "followup/inputs.json"
    old_hash = _hash(inputs)
    records = json.loads(inputs.read_text(encoding="utf-8"))
    next(r for r in records if r["path"] == changed.relative_to(root).as_posix())["sha256"] = _hash(
        changed
    )
    _json(inputs, records)
    config.write_text(
        config.read_text(encoding="utf-8").replace(old_hash, _hash(inputs)), encoding="utf-8"
    )


def test_duplicate_station_is_rejected(source: tuple[Path, Path], tmp_path: Path) -> None:
    path = source[0] / "processed/station.csv"
    with path.open(encoding="utf-8") as stream:
        stations = list(csv.DictReader(stream))
    _csv(path, [*stations, stations[0]])
    _resign(source, path)
    with pytest.raises(ValueError, match="station cohort"):
        _build(source, tmp_path / "out")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.org/record", "https://example.org/record"),
        ("https://example.org/?key=SECRET", None),
        ("javascript:alert(1)", None),
        ("https://user:password@example.org/", None),
        ("file:///Users/private", None),
    ],
)
def test_safe_links_only(value: str, expected: str | None) -> None:
    assert demo_export._safe_url(value) == expected  # pyright: ignore[reportPrivateUsage]


def test_fingerprint_cannot_escape_root(source: tuple[Path, Path], tmp_path: Path) -> None:
    root, config = source
    inputs = root / "followup/inputs.json"
    old_hash = _hash(inputs)
    _json(inputs, [{"path": "../../outside", "sha256": "a" * 64}])
    config.write_text(config.read_text().replace(old_hash, _hash(inputs)), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        _build(source, tmp_path / "out")


def test_late_source_change_prevents_publication(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_json = demo_export._write_json  # pyright: ignore[reportPrivateUsage]

    def mutate(path: Path, value: object) -> None:
        write_json(path, value)
        if path.name == "manifest.json":
            (source[0] / "processed/observation.csv").write_text("changed", encoding="utf-8")

    monkeypatch.setattr(demo_export, "_write_json", mutate)
    with pytest.raises(ValueError, match="checksum"):
        _build(source, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_late_destination_is_never_overwritten(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_json = demo_export._write_json  # pyright: ignore[reportPrivateUsage]
    destination = tmp_path / "out/test-v1"

    def compete(path: Path, value: object) -> None:
        write_json(path, value)
        if path.name == "manifest.json":
            destination.mkdir()
            (destination / "original").write_text("preserved", encoding="utf-8")

    monkeypatch.setattr(demo_export, "_write_json", compete)
    with pytest.raises(FileExistsError):
        _build(source, tmp_path / "out")
    assert (destination / "original").read_text() == "preserved"


def test_late_followup_output_change_prevents_publication(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = source
    inputs = root / "followup/inputs.json"
    old_hash = _hash(inputs)
    accepted = json.loads(inputs.read_text(encoding="utf-8"))
    # Match the real dependency graph: generated outputs are not raw input entries.
    _json(inputs, [r for r in accepted if not r["path"].startswith("followup/")])
    config.write_text(
        config.read_text(encoding="utf-8").replace(old_hash, _hash(inputs)), encoding="utf-8"
    )
    read_table = demo_export._table  # pyright: ignore[reportPrivateUsage]

    def mutate_before_read(path: Path, required: set[str]) -> list[dict[str, str]]:
        if path.name == "coverage-by-window.csv":
            path.write_text(
                path.read_text(encoding="utf-8").replace("0.0694", "100"), encoding="utf-8"
            )
        return read_table(path, required)

    monkeypatch.setattr(demo_export, "_table", mutate_before_read)
    with pytest.raises(ValueError, match="checksum"):
        _build(source, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_late_config_change_prevents_publication(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_json = demo_export._write_json  # pyright: ignore[reportPrivateUsage]

    def mutate_config(path: Path, value: object) -> None:
        write_json(path, value)
        if path.name == "geometry.json":
            with source[1].open("a", encoding="utf-8") as stream:
                stream.write("\n# changed after initial parsing\n")

    monkeypatch.setattr(demo_export, "_write_json", mutate_config)
    with pytest.raises(ValueError, match="config checksum"):
        _build(source, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_late_release_receipt_change_prevents_publication(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = source
    inputs = root / "followup/inputs.json"
    old_hash = _hash(inputs)
    accepted = json.loads(inputs.read_text(encoding="utf-8"))
    _json(inputs, [r for r in accepted if r["path"] != "receipt.json"])
    config.write_text(
        config.read_text(encoding="utf-8").replace(old_hash, _hash(inputs)), encoding="utf-8"
    )
    write_json = demo_export._write_json  # pyright: ignore[reportPrivateUsage]

    def mutate_receipt(path: Path, value: object) -> None:
        write_json(path, value)
        if path.name == "geometry.json":
            _json(root / "receipt.json", {"status": "changed after review verification"})

    monkeypatch.setattr(demo_export, "_write_json", mutate_receipt)
    with pytest.raises(ValueError, match="checksum"):
        _build(source, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []
