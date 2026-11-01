"""Audit samples freeze before picks and keep identity/outcome data out of blind copies."""

# pyright: reportPrivateUsage=false

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from scripts.build_multi_event_catalog import _json, _records, _sha, _write_csv, _write_json
from scripts.prepare_blinded_waveform_audit import (
    BLIND_COLUMNS,
    build,
    case_key,
    chart_points,
    chart_sources,
    choose_cases,
)


def make_fixture(root: Path) -> tuple[Path, Path]:
    selection = root / "selection.json"
    frozen: dict[str, Any] = {
        "events": [
            {
                "event_id": "private-dev-id",
                "role": "development",
                "region": "Pacific",
                "usgs_time": "2011-03-11T05:46:24Z",
            },
            {
                "event_id": "private-reserved-id",
                "role": "sealed_evaluation",
                "region": "Pacific",
                "usgs_time": "2012-03-11T05:46:24Z",
            },
        ]
    }
    frozen["selection_sha256"] = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(selection, frozen)
    sources: list[dict[str, Any]] = []
    for cadence, product in ((60, "one_minute_water_level"), (360, "water_level")):
        sid = "private-source-" + product
        rows = [
            {
                **dict.fromkeys(BLIND_COLUMNS, "unknown"),
                "timestamp_utc": stamp,
                "timestamp_state": "reported_utc",
                "value_state": "finite_numeric",
                "numeric_value": value,
                "source_id": sid,
                "event_id": "private-dev-id",
                "purpose": "event_window",
                "observed_raw": "PRIVATE_NTWC_CLOCK",
                "units": "m",
            }
            for stamp, value in [("2011-03-11T05:46:24Z", 1), ("2011-03-11T05:47:24Z", 2)]
        ]
        path = root / "waves" / f"{sid}.csv.gz"
        _write_csv(path, rows)
        sources.append(
            {
                "event_id": "private-dev-id",
                "source_id": sid,
                "purpose": "event_window",
                "processing_status": "normalized_source_samples",
                "source_url": f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=1234567&product={product}",
                "provider": "CO-OPS",
                "provider_station_id": "1234567",
                "output_path": path.name,
                "output_sha256": _sha(path),
                "units": "m",
                "vertical_datum": "STND",
                "declared_cadence_seconds": cadence,
            }
        )
    sources.append(
        {
            "event_id": "private-dev-id",
            "source_id": "private-missing-source",
            "source_url": "https://www.tsunami.gov/previous.events/example/Data/abcd_A_2011.070",
            "purpose": "event_window",
            "processing_status": "unavailable",
        }
    )
    manifest = root / "waves/manifest.json"
    _write_json(manifest, {"sources": sources, "input_sha256": {}})
    return selection, manifest


def test_blind_pack_retains_missing_cases_and_removes_private_identifiers(tmp_path: Path) -> None:
    selection, manifest = make_fixture(tmp_path)
    result = build(tmp_path, selection, manifest, tmp_path / "out", 2, 0)
    assert result["event_cases"] == 2 and result["reviewable_cases"] == 1 and result["picks"] == 0
    cases = _json(tmp_path / "out/blind/catalog.json")["cases"]
    assert [c["case_id"] for c in cases] == sorted(c["case_id"] for c in cases)
    assert sum(c["reviewable"] for c in cases) == 1
    assert any("no_normalized_source" in c["blocked_reasons"] for c in cases)
    for path in (tmp_path / "out/blind").rglob("*"):
        if path.suffix == ".json":
            text = path.read_text()
            assert "private-dev-id" not in text and "PRIVATE_NTWC" not in text
        if path.suffix == ".gz":
            rows = _records(path)
            assert len(rows) == 2 and set(rows[0]) == set(BLIND_COLUMNS)
            assert "PRIVATE_NTWC" not in json.dumps(rows) and "private-source" not in json.dumps(
                rows
            )
    reviewed = next(c for c in cases if c["reviewable"])
    assert len(reviewed["sources"]) == 2 and [
        s["declared_cadence_seconds"] for s in reviewed["sources"] if s["selected_for_chart"]
    ] == [60]
    assert "private-dev-id" in (tmp_path / "out/private/mapping.json").read_text()
    replay = build(tmp_path, selection, manifest, tmp_path / "replay", 2, 0)
    assert replay == result
    with pytest.raises(FileExistsError):
        build(tmp_path, selection, manifest, tmp_path / "out", 2, 0)


def test_reserved_input_and_changed_hash_fail_closed(tmp_path: Path) -> None:
    selection, manifest = make_fixture(tmp_path)
    data = _json(manifest)
    data["sources"][0]["event_id"] = "private-reserved-id"
    _write_json(manifest, data)
    with pytest.raises(ValueError, match="reserved"):
        build(tmp_path, selection, manifest, tmp_path / "out")
    data["sources"][0]["event_id"] = "private-dev-id"
    _write_json(manifest, data)
    (manifest.parent / data["sources"][0]["output_path"]).write_text("corruption")
    with pytest.raises(ValueError, match="checksum"):
        build(tmp_path, selection, manifest, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_chart_deduplication_and_gaps_never_change_original_rows() -> None:
    def row(t: str, v: str) -> dict[str, str]:
        return {
            "timestamp_utc": t,
            "numeric_value": v,
            "timestamp_state": "reported_utc",
            "value_state": "finite_numeric",
        }

    rows = [
        row("2011-03-11T00:00:00Z", "1"),
        row("2011-03-11T00:00:00Z", "1"),
        row("2011-03-11T00:01:00Z", "2"),
        row("2011-03-11T00:01:00Z", "3"),
        row("2011-03-11T00:03:00Z", "4"),
    ]
    x, y, counts = chart_points(rows, "2011-03-11T00:00:00Z", 60)
    assert len(rows) == 5 and counts["identical_duplicate_rows_removed"] == 1
    assert counts["conflicting_duplicate_rows"] == 2 and len(x) == 3 and math.isnan(y[1])


def test_case_sampling_is_order_independent_and_separates_providers_controls(
    tmp_path: Path,
) -> None:
    selection, manifest = make_fixture(tmp_path)
    sources = _json(manifest)["sources"]
    events = {r["event_id"]: r for r in _json(selection)["events"]}
    keys = list({case_key(s) for s in sources})
    assert choose_cases(keys, events, 2) == choose_cases(keys[::-1], events, 2)
    source = dict(
        sources[0],
        purpose="quiet_control",
        window_start_utc="2011-01-01T00:00:00Z",
        window_stop_utc="2011-01-05T00:00:00Z",
    )
    assert case_key(source) != case_key(dict(source, window_start_utc="2011-02-01T00:00:00Z"))
    assert chart_sources(sources[:2], "CO-OPS")[0]["declared_cadence_seconds"] == 60


def test_quiet_control_assignment_is_present_only_in_private_mapping(tmp_path: Path) -> None:
    selection, manifest = make_fixture(tmp_path)
    data = _json(manifest)
    original = data["sources"][0]
    control = dict(
        original,
        source_id="private-control-source",
        purpose="quiet_control",
        window_start_utc="2011-02-24T00:00:00Z",
        window_stop_utc="2011-02-28T00:00:00Z",
        output_path="control.csv.gz",
    )
    rows = _records(manifest.parent / original["output_path"])
    for row in rows:
        row["source_id"] = control["source_id"]
        row["purpose"] = "quiet_control"
        row["timestamp_utc"] = row["timestamp_utc"].replace("2011-03-11", "2011-02-25")
    _write_csv(manifest.parent / control["output_path"], rows)
    control["output_sha256"] = _sha(manifest.parent / control["output_path"])
    data["sources"].append(control)
    _write_json(manifest, data)
    result = build(tmp_path, selection, manifest, tmp_path / "out", 2, 1)
    assert result["control_cases"] == 1
    cases = _json(tmp_path / "out/blind/catalog.json")["cases"]
    mixed_ids = [case["case_id"] for case in cases]
    assert mixed_ids == sorted(mixed_ids)
    assert [r["case_id"] for r in _records(tmp_path / "out/blind/review-template.csv")] == mixed_ids
    assert (tmp_path / "out/blind/README.md").exists()
    for path in (tmp_path / "out/blind").rglob("*"):
        if path.suffix in {".json", ".csv", ".md"}:
            text = path.read_text()
        elif path.suffix == ".gz":
            text = json.dumps(_records(path))
        else:
            continue
        for forbidden in (
            "quiet_control",
            "quiet_status",
            '"purpose"',
            "not an earthquake origin",
            "private-control-source",
        ):
            assert forbidden not in text
    assert "quiet_control" in (tmp_path / "out/private/mapping.json").read_text()
    cases = _json(tmp_path / "out/blind/catalog.json")["cases"]
    assert len({case["reference_basis"] for case in cases}) == 1
