"""Boundary tests for private evidence packaging and the development viewer."""

# pyright: reportPrivateUsage=false

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.build_multi_event_catalog import (
    WAVE_COLUMNS,
    _json,
    _records,
    _sha,
    _viewer,
    _write_csv,
    _write_json,
    build,
)


def fixture(root: Path) -> dict[str, Path]:
    paths = {name: root / name for name in ("census", "design", "crosswalk", "corpus", "waveforms")}
    paths.update(screen=root / "screen.json", selection=root / "selection.json")
    dispositions: list[dict[str, Any]] = []
    for eid, reason in (
        ("dev", "metadata_eligible"),
        ("reserved", "metadata_eligible"),
        ("excluded", "magnitude_below_threshold"),
    ):
        raw = root / f"{eid}.html"
        raw.write_text("RAW ARCHIVE " + eid)
        dispositions.append(
            {
                "event_id": eid,
                "archive_key": eid,
                "reason": reason,
                "identity_status": "reviewed",
                "local_path": raw.name,
                "source_sha256": _sha(raw),
                "url": f"https://example.org/{eid}",
            }
        )
    screen = {"dispositions": dispositions}
    _write_json(paths["screen"], screen)
    selected = {
        "screen_sha256": hashlib.sha256(json.dumps(screen, sort_keys=True).encode()).hexdigest(),
        "events": [
            {"event_id": "dev", "role": "development"},
            {"event_id": "reserved", "role": "sealed_evaluation"},
        ],
    }
    selected["selection_sha256"] = hashlib.sha256(
        json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(paths["selection"], selected)
    row = {"event_id": "dev", "role": "development", "table_index": 1, "row_index": 1}
    _write_json(paths["census"] / "rows.json", [row])
    _write_json(paths["census"] / "links.json", [])
    upstream = {
        "rows": _sha(paths["census"] / "rows.json"),
        "links": _sha(paths["census"] / "links.json"),
    }
    report = {
        "event_id": "dev",
        "report_id": "dev:1:1",
        "table_index": 1,
        "row_index": 1,
        "observed_raw": "PRIVATE_CLOCK",
        "source_id": "ntwc-dev",
        "raw_row_json": "PRIVATE_LABEL",
    }
    relative = "dev/arrival_report.csv.gz"
    _write_csv(paths["corpus"] / relative, [report])
    _write_json(
        paths["corpus"] / "summary.json",
        {
            "events": {"dev": {"source_rows": 1, "exact_pairs": 0}},
            "source_rows": 1,
            "input_sha256": upstream,
            "output_sha256": {relative: _sha(paths["corpus"] / relative)},
        },
    )
    station = {
        "event_id": "dev",
        "report_id": "dev:1:1",
        "role": "development",
        "link_code": "site",
        "physical_site_id": "unknown",
        "fit_eligible": False,
        "identity_tier": "archive_code",
        "explicit_both_values": True,
        "legacy_both_values": False,
    }
    _write_csv(paths["crosswalk"] / "event_site.csv", [dict(station, link_sensor=s) for s in "AB"])
    _write_json(paths["crosswalk"] / "connectivity.json", {"input_sha256": upstream})
    _write_csv(
        paths["design"] / "event_support.csv", [{"event_id": "dev", "source_pair_values": 1}]
    )
    _write_json(paths["design"] / "summary.json", {"input_sha256": upstream})
    _write_json(paths["waveforms"] / "manifest.json", {"input_sha256": {}, "sources": []})
    return paths


def package(root: Path, paths: dict[str, Path], name: str = "out") -> dict[str, Any]:
    return build(root, **paths, output=root / name)


def test_preserves_all_dispositions_reports_and_sensor_alternatives(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    result = package(tmp_path, paths)
    assert (result["archive_entries"], result["source_reports"], result["event_station_rows"]) == (
        3,
        1,
        2,
    )
    entries = {r["event_id"]: r for r in _json(tmp_path / "out/catalog.json")["entries"]}
    assert entries["reserved"]["data_status"] == "sealed_metadata_only"
    assert entries["reserved"]["source_reports"] == "unknown"
    assert entries["dev"]["viewer_blocked_reason"] == "display_coverage_qc_missing"
    assert all(not r["model_eligible"] for r in entries.values())
    assert _records(tmp_path / "out/paper/report_index.csv")[0]["observed_raw"] == "PRIVATE_CLOCK"
    viewer = (tmp_path / "out/viewer/catalog.json").read_text()
    assert "reserved" not in viewer and "PRIVATE" not in viewer
    assert _json(tmp_path / "out/viewer/catalog.json")["events"] == []


def test_reproducible_and_refuses_overwrite(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    first = package(tmp_path, paths)
    second = package(tmp_path, paths, "replay")
    assert first == second
    for name, digest in first["output_sha256"].items():
        assert _sha(tmp_path / "out" / name) == _sha(tmp_path / "replay" / name) == digest
    with pytest.raises(FileExistsError):
        package(tmp_path, paths)


@pytest.mark.parametrize("target", ["raw", "selection", "screen", "corpus", "lineage"])
def test_changed_evidence_fails_closed(tmp_path: Path, target: str) -> None:
    paths = fixture(tmp_path)
    if target == "raw":
        (tmp_path / "dev.html").write_text("changed")
    elif target in {"selection", "screen"}:
        obj = _json(paths[target])
        obj["changed"] = True
        _write_json(paths[target], obj)
    elif target == "corpus":
        (paths["corpus"] / "dev/arrival_report.csv.gz").write_bytes(b"changed")
    else:
        _write_json(paths["census"] / "links.json", ["changed"])
    with pytest.raises(ValueError, match="digest|checksum|match"):
        package(tmp_path, paths)
    assert not (tmp_path / "out").exists()


def test_reserved_waveform_value_is_rejected(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    _write_json(
        paths["waveforms"] / "manifest.json",
        {
            "input_sha256": {},
            "sources": [{"event_id": "reserved", "source_id": "unsafe"}],
        },
    )
    with pytest.raises(ValueError, match="reserved"):
        package(tmp_path, paths)


def test_lost_crosswalk_row_is_rejected(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    _write_csv(paths["crosswalk"] / "event_site.csv", [])
    with pytest.raises(ValueError, match="retain every"):
        package(tmp_path, paths)


def test_manifest_path_escape_is_rejected(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    summary = _json(paths["corpus"] / "summary.json")
    summary["output_sha256"] = {"../dev.html": _sha(tmp_path / "dev.html")}
    _write_json(paths["corpus"] / "summary.json", summary)
    with pytest.raises(ValueError, match="escapes"):
        package(tmp_path, paths)


def viewer_fixture(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    events = {
        "dev": {
            "role": "development",
            "usgs_place": "Ocean",
            "usgs_time": "2011-03-11T05:46:24Z",
            "usgs_latitude": 0,
            "usgs_longitude": 1,
            "usgs_mag": 8,
            "usgs_magType": "mww",
            "usgs_depth": 10,
        },
        "reserved": {"role": "sealed_evaluation"},
    }
    sources: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for number in range(3):
        sid = f"source-{number}"
        path = root / f"{sid}.csv.gz"
        rows = [
            {
                **dict.fromkeys(WAVE_COLUMNS, "unknown"),
                "event_id": "dev",
                "source_id": sid,
                "purpose": "event_window",
                "timestamp_state": "reported_utc",
                "timestamp_utc": time,
                "observed_raw": "PRIVATE_LABEL",
                "model_prediction": "PRIVATE_MODEL",
            }
            for time in ("2011-03-10T23:00:00Z", "2011-03-11T12:00:00Z")
        ]
        _write_csv(path, rows)
        sources.append(
            {
                "event_id": "dev",
                "source_id": sid,
                "normalized_path": path.name,
                "processing_status": "normalized_source_samples",
                "purpose": "event_window",
                "provider": "CO-OPS",
                "provider_station_id": str(1000000 + number),
                "display_station_key": f"coops:{1000000 + number}",
                "source_url": "https://example.org",
                "source_sha256": "a" * 64,
                "units": "m",
                "vertical_datum": "STND",
            }
        )
        coverage.append(
            {
                "event_id": "dev",
                "station_key": sid,
                "display_station_key": f"coops:{1000000 + number}",
                "rule_id": "viewer_36h_80pct_60min_v1",
                "purpose": "event_window",
                "expected_bins": 2160,
                "usable_bins": 1800,
                "coverage_fraction": 1800 / 2160,
                "longest_supported_minutes": 120,
                "sensor": "A",
                "display_eligible": True,
                "source_ids": [sid],
                "window_start_utc": "2011-03-10T23:46:24Z",
                "window_stop_utc": "2011-03-12T11:46:24Z",
            }
        )
    return events, sources, coverage


def test_viewer_allowlist_and_declared_window(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    exported, readiness = _viewer(tmp_path, tmp_path / "out", events, sources, coverage)
    assert len(exported) == 1 and readiness["dev"]["display_usable_station_count"] == 3
    assert "reserved" not in json.dumps(exported)
    for source in exported[0]["waveforms"]:
        rows = _records(tmp_path / "out/viewer" / source["path"])
        assert len(rows) == 1 and set(rows[0]) == set(WAVE_COLUMNS)
        assert rows[0]["timestamp_utc"] == "2011-03-11T12:00:00Z"
        assert "PRIVATE" not in json.dumps(rows)


def test_sensor_and_provider_aliases_do_not_inflate_station_count(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    coverage[1]["display_station_key"] = coverage[0]["display_station_key"]
    sources[1]["provider_station_id"] = sources[0]["provider_station_id"]
    sources[1]["display_station_key"] = sources[0]["display_station_key"]
    exported, readiness = _viewer(tmp_path, tmp_path / "out", events, sources, coverage)
    assert not exported and readiness["dev"]["display_usable_station_count"] == 2


def test_reserved_coverage_is_rejected(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    coverage[0]["event_id"] = "reserved"
    with pytest.raises(ValueError, match="reserved"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


@pytest.mark.parametrize(
    "change",
    [
        {"usable_bins": 1},
        {"longest_supported_minutes": 1},
        {"purpose": "quiet_control"},
        {"display_station_key": "unverified:ABC"},
        {"coverage_fraction": 1},
        {"source_ids": []},
    ],
)
def test_false_display_eligibility_fails_closed(tmp_path: Path, change: dict[str, Any]) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    coverage[0].update(change)
    with pytest.raises(ValueError, match="declared rule"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


def test_official_contours_keep_source_semantics_and_only_public_properties(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    geometry = {"type": "MultiLineString", "coordinates": [[[179, 0], [-179, 1]]]}
    _write_json(
        tmp_path / "contours.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "HOURS": 1,
                        "Name": "Official layer",
                        "private_model_result": "DO NOT EXPORT",
                    },
                }
            ],
        },
    )
    contour = {
        "event_id": "dev",
        "processed_path": "contours.geojson",
        "layer_id": 1,
        "source_url": "https://example.org/official-contours",
        "raw_sha256": "a" * 64,
        "units": "hours",
        "crs": "EPSG:4326 requested from service",
        "coordinate_order": "longitude, latitude",
        "horizontal_datum": "unknown",
        "origin_reference": "source-specific; NTWC equivalence unverified",
    }
    exported, _ = _viewer(tmp_path, tmp_path / "out", events, sources, coverage, [contour])
    layer = exported[0]["published_travel_time_contours"][0]
    assert not layer["ntwc_prediction_equivalence_verified"]
    published = _json(tmp_path / "out/viewer" / layer["path"])
    assert published["features"][0]["geometry"] == geometry
    assert published["features"][0]["properties"] == {"HOURS": 1, "Name": "Official layer"}
    assert "DO NOT EXPORT" not in json.dumps(published)


def test_quiet_control_source_cannot_be_relabelled_by_coverage(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    sources[0]["purpose"] = "quiet_control"
    with pytest.raises(ValueError, match="coverage source"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


@pytest.mark.parametrize(
    "window",
    [
        {"window_start_utc": "1900-01-01T00:00:00Z", "window_stop_utc": "2100-01-01T00:00:00Z"},
        {"window_start_utc": "2011-03-10T23:46:24"},
        {"window_stop_utc": "2011-03-12T12:46:24+01:00"},
    ],
)
def test_display_window_cannot_override_frozen_rule(tmp_path: Path, window: dict[str, str]) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    coverage[0].update(window)
    with pytest.raises(ValueError, match="UTC|frozen origin"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


def test_one_source_cannot_supply_three_station_identities(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    for row in coverage:
        row["source_ids"] = ["source-0"]
    with pytest.raises(ValueError, match="coverage source"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


def test_source_index_retains_purpose_namespace_window_and_qc(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    source = {
        "event_id": "dev",
        "source_id": "control",
        "purpose": "quiet_control",
        "provider": "CO-OPS",
        "provider_station_id": "1234567",
        "sensor": "water_level",
        "window_start_utc": "2011-02-24T00:00:00Z",
        "window_stop_utc": "2011-02-28T00:00:00Z",
        "processing_status": "no_data",
        "qc_states": {"unknown": 0},
        "value_states": {},
        "declared_cadence_seconds": 60,
    }
    _write_json(paths["waveforms"] / "manifest.json", {"input_sha256": {}, "sources": [source]})
    package(tmp_path, paths)
    row = _records(tmp_path / "out/paper/source_index.csv")[0]
    for key in (
        "purpose",
        "provider",
        "provider_station_id",
        "sensor",
        "window_start_utc",
        "window_stop_utc",
    ):
        assert row[key] == source[key]
    assert json.loads(row["qc_states"]) == {"unknown": 0}
    assert row["declared_cadence_seconds"] == "60"


def test_control_rows_cannot_hide_in_an_event_window_source(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    path = tmp_path / sources[0]["normalized_path"]
    rows = _records(path)
    rows[0]["purpose"] = "quiet_control"
    _write_csv(path, rows)
    with pytest.raises(ValueError, match="row identity"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


def test_other_provider_numeric_id_cannot_impersonate_a_coops_site(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    sources[0]["provider"] = "unrelated-provider"
    with pytest.raises(ValueError, match="coverage source"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


def test_oversized_contour_is_losslessly_compressed_and_declares_decoding(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    geometry = {"type": "MultiLineString", "coordinates": [[[179.125, -32.5]] * 35000]}
    layer = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {"HOURS": 1, "Name": "Published"},
            }
        ],
    }
    _write_json(tmp_path / "large.geojson", layer)
    contour = {
        "event_id": "dev",
        "processed_path": "large.geojson",
        "layer_id": 1,
        "source_url": "https://example.org/official",
        "raw_sha256": "a" * 64,
        "units": "hours",
        "crs": "EPSG:4326",
        "coordinate_order": "longitude, latitude",
        "horizontal_datum": "unknown",
        "origin_reference": "published source",
    }
    exported, _ = _viewer(tmp_path, tmp_path / "out", events, sources, coverage, [contour])
    asset = exported[0]["published_travel_time_contours"][0]
    data = (tmp_path / "out/viewer" / asset["path"]).read_bytes()
    assert asset["content_encoding"] == "gzip" and asset["media_type"] == "application/geo+json"
    assert asset["uncompressed_bytes"] > 2_000_000 > asset["compressed_bytes"] == len(data)
    assert json.loads(gzip.decompress(data)) == layer
    replay, _ = _viewer(tmp_path, tmp_path / "replay", events, sources, coverage, [contour])
    assert replay == exported


def test_asset_size_limit_applies_to_catalog_and_does_not_downsample(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    events["dev"]["usgs_place"] = "x" * 2_000_000
    with pytest.raises(ValueError, match="viewer asset exceeds"):
        _viewer(tmp_path, tmp_path / "out", events, sources, coverage)


def test_event_catalog_chronology_and_dictionary_contract(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    frozen = _json(paths["selection"])
    frozen["events"][0]["usgs_time"] = "2015-09-16T22:54:32Z"
    frozen["events"][1]["usgs_time"] = "2010-02-27T06:34:11+00:00"
    del frozen["selection_sha256"]
    frozen["selection_sha256"] = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(paths["selection"], frozen)
    package(tmp_path, paths)
    expected = ["reserved", "dev", "excluded"]
    assert [r["event_id"] for r in _records(tmp_path / "out/paper/event_index.csv")] == expected
    assert [r["event_id"] for r in _json(tmp_path / "out/catalog.json")["entries"]] == expected
    dictionary = _json(tmp_path / "out/data_dictionary.json")
    assert dictionary["tables"]["paper/event_index.csv"]["primary_key"] == ["archive_key"]
    assert dictionary["tables"]["paper/report_index.csv"]["primary_key"] == ["report_id"]
    assert set(dictionary["conventions"]) >= {
        "joins",
        "units",
        "missing_values",
        "gzip",
        "waveform_order",
    }


def test_waveform_export_keeps_native_row_order_and_duplicates(tmp_path: Path) -> None:
    events, sources, coverage = viewer_fixture(tmp_path)
    path = tmp_path / sources[0]["normalized_path"]
    row = _records(path)[1]
    original = [
        dict(row, timestamp_utc=t)
        for t in ("2011-03-11T18:00:00Z", "2011-03-11T12:00:00Z", "2011-03-11T12:00:00Z")
    ]
    _write_csv(path, original)
    exported, _ = _viewer(tmp_path, tmp_path / "out", events, sources, coverage)
    asset = next(r for r in exported[0]["waveforms"] if r["source_id"] == "source-0")
    rows = _records(tmp_path / "out/viewer" / asset["path"])
    assert [r["timestamp_utc"] for r in rows] == [r["timestamp_utc"] for r in original]


def test_report_index_uses_numeric_table_row_order(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    relative = "dev/arrival_report.csv.gz"
    base = _records(paths["corpus"] / relative)[0]
    reports = [dict(base, report_id=f"dev:1:{i}", row_index=i) for i in (10, 2, 1)]
    _write_csv(paths["corpus"] / relative, reports)
    census_row = _json(paths["census"] / "rows.json")[0]
    _write_json(paths["census"] / "rows.json", [dict(census_row, row_index=i) for i in (10, 2, 1)])
    sites = _records(paths["crosswalk"] / "event_site.csv")
    _write_csv(
        paths["crosswalk"] / "event_site.csv",
        [dict(site, report_id=f"dev:1:{i}") for i in (10, 2, 1) for site in sites],
    )
    upstream = {
        "rows": _sha(paths["census"] / "rows.json"),
        "links": _sha(paths["census"] / "links.json"),
    }
    summary = _json(paths["corpus"] / "summary.json")
    summary.update(source_rows=3, input_sha256=upstream)
    summary["events"]["dev"]["source_rows"] = 3
    summary["output_sha256"][relative] = _sha(paths["corpus"] / relative)
    _write_json(paths["corpus"] / "summary.json", summary)
    for path in (paths["crosswalk"] / "connectivity.json", paths["design"] / "summary.json"):
        _write_json(path, {"input_sha256": upstream})
    package(tmp_path, paths)
    result = _records(tmp_path / "out/paper/report_index.csv")
    assert [int(r["row_index"]) for r in result] == [1, 2, 10]
    assert {r["report_id"] for r in result} == {r["report_id"] for r in reports}


def test_coverage_dictionary_key_keeps_conflicting_provider_ids_distinct(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    rows = [
        {
            "event_id": "dev",
            "provider": "NOS",
            "station_key": "ntwc-same-code",
            "provider_station_id": station,
            "display_station_key": f"coops:{station}",
            "sensor": "A",
            "declared_cadence_seconds": 60,
            "units": "m",
            "vertical_datum": "unknown",
            "window_start_utc": "2011-03-11T00:00:00Z",
            "window_stop_utc": "2011-03-12T12:00:00Z",
            "display_eligible": False,
        }
        for station in ("1234567", "7654321")
    ]
    _write_json(
        paths["waveforms"] / "manifest.json",
        {"input_sha256": {}, "sources": [], "series_coverage": rows},
    )
    package(tmp_path, paths)
    dictionary = _json(tmp_path / "out/data_dictionary.json")
    keys = dictionary["tables"]["paper/series_coverage.csv"]["primary_key"]
    assert {"provider_station_id", "display_station_key"} <= set(keys)
    assert len({tuple(row[key] for key in keys) for row in rows}) == 2


def test_exact_url_overlap_inventory_retains_snapshots_without_deduplication(
    tmp_path: Path,
) -> None:
    paths = fixture(tmp_path)
    repeated = "https://example.org/capture"
    sources = [
        {
            "event_id": "dev",
            "source_id": sid,
            "source_url": url,
            "source_sha256": digest,
            "purpose": purpose,
            "sensor": sensor,
            "units": units,
            "vertical_datum": datum,
            "processing_status": "retained_source",
            "source_rows": 4 if purpose == "event_window" else 0,
        }
        for sid, url, digest, purpose, sensor, units, datum in (
            ("z", repeated, "a" * 64, "event_window", "A", "m", "STND"),
            ("a", repeated, "b" * 64, "event_window", "B", "cm", "unknown"),
            ("h", repeated, "a" * 64, "header_evidence", "A", "m", "STND"),
            ("other-url", "https://example.org/other", "a" * 64, "event_window", "A", "m", "STND"),
            ("missing-1", "unknown", "unknown", "diagnostic", "unknown", "unknown", "unknown"),
            ("missing-2", "unknown", "unknown", "diagnostic", "unknown", "unknown", "unknown"),
        )
    ]
    _write_json(paths["waveforms"] / "manifest.json", {"input_sha256": {}, "sources": sources})
    result = package(tmp_path, paths)
    rows = _records(tmp_path / "out/paper/source_url_overlaps.csv")
    assert [row["source_id"] for row in rows] == ["a", "h", "z"]
    assert all(row["source_url"] == repeated and row["group_source_count"] == "3" for row in rows)
    for row in rows:
        original = next(s for s in sources if s["source_id"] == row["source_id"])
        for field in ("source_sha256", "purpose", "sensor", "units", "vertical_datum"):
            assert row[field] == original[field]
    assert len(_records(tmp_path / "out/paper/source_index.csv")) == len(sources)
    assert result["repeated_source_url_groups"] == 1 and result["overlap_source_entries"] == 3
    dictionary = _json(tmp_path / "out/data_dictionary.json")
    assert "not unique measurements" in dictionary["conventions"]["observation_grain"]
    assert dictionary["tables"]["paper/source_url_overlaps.csv"]["primary_key"] == [
        "source_url", "source_id"
    ]
    assert _json(tmp_path / "out/viewer/catalog.json")["events"] == []
