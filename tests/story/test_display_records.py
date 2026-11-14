"""Records schema 2: display slices copied byte for byte from the multi-event viewer export."""

import gzip
import hashlib
import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from analysis.story.display_records import export_display_records

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/story-display-records.toml"
BUNDLES = ROOT / "app/demo-public/data"
ORIGIN = "2001-01-01T00:00:00.500Z"
HEADER = (
    "event_id,source_id,station_key,sensor,timestamp_utc,numeric_value,value_state,"
    "timestamp_state,duplicate_timestamp,units,vertical_datum,qc_state,qc_json"
)
TIMES = ("2001-01-01T00:00:00Z", "2001-01-01T00:01:00Z", "2001-01-01T00:02:00Z")
QUERY_URL = "https://api.example.org/data?station=1"
CLEAN_URL = "https://example.org/data.json"
WAVEFORMS: list[tuple[str, str, float, float, str, object, object, str]] = [
    # station, file name, coverage, longest supported minutes, datum, latitude, longitude, url
    ("1000002", "coops-window-ev-1-1000002-water_level-event_window", 1.0, 2160.0, "STND",
     "0.0", "-159.0", QUERY_URL),
    ("1000002", "coops-window-ev-1-1000002-one_minute_water_level-event_window", 0.5, 10.0,
     "STND", "0.0", "-159.0", CLEAN_URL),
    ("1000001", "ia-window-bbb", 0.9, 50.0, "Unknown", 0.0, -161.0, QUERY_URL),
    ("1000001", "ia-window-aaa", 0.9, 50.0, "Unknown", 0.0, -161.0, QUERY_URL),
    ("1000003", "coops-window-ev-1-1000003-water_level-event_window", 0.8, 30.0, "MLLW",
     0.0, -150.0, QUERY_URL),
    ("1000003", "coops-ev-1-1000003-water_level-event_window", 0.8, 40.0, "MLLW",
     0.0, -150.0, QUERY_URL),
    ("1000003", "coops-ev-1-1000003-water_level-other_window", 0.7, 2000.0, "MLLW",
     0.0, -150.0, QUERY_URL),
]  # fmt: skip
CHOSEN = {
    "1000001": "ia-window-aaa",  # archive windows tie on both measures: smaller source_id
    "1000002": "coops-window-ev-1-1000002-one_minute_water_level-event_window",
    "1000003": "coops-ev-1-1000003-water_level-event_window",  # coverage, then longest
}


def _station_csv(source_id: str, datum: str, times: tuple[str, ...] = TIMES, **row: str) -> bytes:
    lines = [HEADER]
    for i, at in enumerate(times):
        value, state = ("unknown", "blank") if i == 1 else ("1.25", "finite_numeric")
        cells = {
            "timestamp_state": "reported_utc",
            "duplicate_timestamp": "False",
            "qc_state": "not_provided",
            **row,
        }
        lines.append(
            f"ev-1,{source_id},coops-x,unknown,{at},{value},{state},{cells['timestamp_state']},"
            f"{cells['duplicate_timestamp']},m,{datum},{cells['qc_state']},{{}}"
        )
    return gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0)


def _source(
    tmp_path: Path,
    edit: Callable[[dict[str, Any]], object] | None = None,
    files: dict[str, bytes] | None = None,
) -> tuple[Path, Path]:
    """A source root with a one-event viewer catalog, its release, coastline and config."""
    root = tmp_path / "source"
    waveforms: list[dict[str, Any]] = []
    for station, name, coverage, longest, datum, latitude, longitude, url in WAVEFORMS:
        data = (files or {}).get(name) or _station_csv(name, datum)
        path = root / f"viewer/waveforms/ev-1/{name}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        waveforms.append(
            {
                "path": f"waveforms/ev-1/{name}.csv.gz",
                "sha256": hashlib.sha256(data).hexdigest(),
                "rows": len(TIMES),
                "content_encoding": "gzip",
                "display_station_key": f"coops:{station}",
                "station_name": f"Station {station}",
                "latitude": latitude,
                "longitude": longitude,
                "units": "m",
                "vertical_datum": datum,
                "source_id": name,
                "source_sha256": "f" * 64,
                "source_url": url,
                "coverage_fraction": coverage,
                "longest_supported_minutes": longest,
                "coverage_rule_id": "viewer_36h_80pct_60min_v1",
            }
        )
    catalog: dict[str, Any] = {
        "events": [
            {
                "event_id": "ev-1",
                "origin_utc": ORIGIN,
                "latitude": 0.0,
                "longitude": -160.0,
                "waveforms": waveforms,
            }
        ]
    }
    if edit is not None:
        edit(catalog)
    catalog_path = root / "viewer/catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    catalog_sha = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    release = json.loads(
        (ROOT / "artifacts/releases/multi-event-descriptive-v1.json").read_text(encoding="utf-8")
    )
    release["source_package"] = {"path": "viewer/catalog.json", "sha256": catalog_sha}
    (root / "release.json").write_text(json.dumps(release), encoding="utf-8")
    coast = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "LineString", "coordinates": [[-155.0, 19.0], [-154.0, 20.0]]},
            }
        ],
    }
    (root / "coast.geojson").write_text(json.dumps(coast), encoding="utf-8")
    coast_sha = hashlib.sha256((root / "coast.geojson").read_bytes()).hexdigest()
    config = tmp_path / "records.toml"
    config.write_text(
        f'catalog = "viewer/catalog.json"\ncatalog_sha256 = "{catalog_sha}"\n'
        'release_manifest = "release.json"\n'
        f'coastline = "coast.geojson"\ncoastline_sha256 = "{coast_sha}"\n'
        'event_ids = ["ev-1"]\n',
        encoding="utf-8",
    )
    return root, config


def _export(source: tuple[Path, Path], out: Path) -> list[Path]:
    root, config = source
    return export_display_records(source_root=root, output_root=out, config_path=config)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    [out] = _export(_source(tmp_path), tmp_path / "out")
    return out


def _manifest(bundle: Path) -> dict[str, Any]:
    return json.loads((bundle / "manifest.json").read_bytes())


def test_manifest_follows_records_schema_2(bundle: Path) -> None:
    manifest = _manifest(bundle)
    assert bundle.name == "records-ev-1-v1"
    assert set(manifest) == {
        "schema_version",
        "exporter_version",
        "bundle_id",
        "evidence_state",
        "event",
        "release",
        "window",
        "default_station_id",
        "stations",
        "assets",
        "geometry_path",
        "input_fingerprints",
        "config_sha256",
        "accounting",
    }
    assert (manifest["schema_version"], manifest["exporter_version"]) == ("2", "1")
    assert manifest["bundle_id"] == "records-ev-1-v1"
    assert manifest["evidence_state"] == "internal_descriptive_only"
    assert manifest["geometry_path"] == "geometry.json"
    assert manifest["event"] == {
        "event_id": "ev-1",
        "origin_time_utc": ORIGIN,
        "latitude": 0.0,
        "longitude": -160.0,
    }
    assert manifest["window"] == {
        "id": "display",
        "label": "6 hours before to 30 hours after the origin",
        "start_utc": "2000-12-31T18:00:00.500Z",
        "end_utc_exclusive": "2001-01-02T06:00:00.500Z",
    }
    assert manifest["release"] == {
        "release_id": "multi-event-descriptive-v1",
        "arrival_comparison_allowed": False,
        "physical_arrival_records_released": 0,
        "continuous_nctr_field": "blocked_no_proxy",
        "allowed_uses": ["descriptive_data_quality", "preliminary_story_diagnostics"],
        "prohibited_uses": [
            "physical_arrival_comparison",
            "modeled_minus_observed_residual",
            "community_timing_selection",
            "actionable_warning_time",
            "operational_warning",
            "public_story_scene_promotion",
        ],
    }
    assert [item["path"] for item in manifest["input_fingerprints"]] == [
        "coast.geojson",
        "release.json",
        "viewer/catalog.json",
    ]


def test_one_product_per_station_with_source_metadata(bundle: Path) -> None:
    stations = {s["station_id"]: s for s in _manifest(bundle)["stations"]}
    assert list(stations) == ["1000001", "1000002", "1000003"]  # code-point order
    assert {sid: s["source"]["source_id"] for sid, s in stations.items()} == CHOSEN
    assert [s["product"] for s in stations.values()] == [
        "archive_window",
        "one_minute_water_level",  # wins although the six-minute file covers more
        "water_level",
    ]
    assert [s["vertical_datum"] for s in stations.values()] == ["unknown", "STND", "MLLW"]
    one_minute = stations["1000002"]
    assert (one_minute["latitude"], one_minute["longitude"]) == (0.0, -159.0)  # from strings
    assert one_minute == {
        "station_id": "1000002",
        "display_station_key": "coops:1000002",
        "name": "Station 1000002",
        "product": "one_minute_water_level",
        "latitude": 0.0,
        "longitude": -159.0,
        "units": "m",
        "vertical_datum": "STND",
        "source": {
            "source_id": CHOSEN["1000002"],
            "sha256": "f" * 64,
            "url": CLEAN_URL,
        },
        "coverage_fraction": 0.5,
        "longest_supported_minutes": 10.0,
        "coverage_rule_id": "viewer_36h_80pct_60min_v1",
        "rows": 3,
    }
    assert stations["1000001"]["source"]["url"] is None  # a query URL is not retained


def test_station_files_are_the_export_bytes(bundle: Path, tmp_path: Path) -> None:
    manifest = _manifest(bundle)
    assets = manifest["assets"]
    assert [a["path"] for a in assets] == [
        "geometry.json",
        "stations/1000001.csv.gz",
        "stations/1000002.csv.gz",
        "stations/1000003.csv.gz",
    ]
    assert [a["content_encoding"] for a in assets] == ["identity", "gzip", "gzip", "gzip"]
    for asset in assets:
        data = (bundle / asset["path"]).read_bytes()
        assert (asset["bytes"], asset["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    for sid, name in CHOSEN.items():
        export = tmp_path / f"source/viewer/waveforms/ev-1/{name}.csv.gz"
        assert (bundle / f"stations/{sid}.csv.gz").read_bytes() == export.read_bytes()
    assert sorted(p.name for p in (bundle / "stations").iterdir()) == [
        f"{sid}.csv.gz" for sid in CHOSEN
    ]


def test_default_station_accounting_and_geometry(bundle: Path) -> None:
    manifest = _manifest(bundle)
    # 1000001 and 1000002 lie at the same geodesic distance: the lower ID wins.
    assert manifest["default_station_id"] == "1000001"
    assert manifest["accounting"] == {"station_count": 3, "rows": 9}
    geometry = json.loads((bundle / "geometry.json").read_bytes())
    assert geometry["schema_version"] == "1"
    assert [p["id"] for p in geometry["points"]] == ["ev-1", "1000001", "1000002", "1000003"]
    assert geometry["central_meridian"] == -160


def test_rerun_is_byte_identical_and_never_overwrites(bundle: Path, tmp_path: Path) -> None:
    source = (tmp_path / "source", tmp_path / "records.toml")
    [again] = _export(source, tmp_path / "again")
    names = sorted(p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(again).as_posix() for p in again.rglob("*") if p.is_file())
    assert all((bundle / n).read_bytes() == (again / n).read_bytes() for n in names)
    before = (bundle / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        _export(source, tmp_path / "out")
    assert (bundle / "manifest.json").read_bytes() == before
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["records-ev-1-v1"]


def _waveform(catalog: dict[str, Any], name: str) -> dict[str, Any]:
    return next(w for w in catalog["events"][0]["waveforms"] if w["source_id"] == name)


BAD: list[tuple[str, Callable[[dict[str, Any]], object] | None, dict[str, bytes]]] = [
    ("unknown datum", lambda c: _waveform(c, "ia-window-aaa").update(vertical_datum="NAVD"), {}),
    ("unknown units", lambda c: _waveform(c, "ia-window-aaa").update(units="ft"), {}),
    ("row count differs", lambda c: _waveform(c, "ia-window-aaa").update(rows=4), {}),
    ("station key", lambda c: _waveform(c, "ia-window-aaa").update(display_station_key="x:1"), {}),
    ("latitude out of range", lambda c: _waveform(c, "ia-window-aaa").update(latitude=91.0), {}),
    (
        "unknown product",
        lambda c: _waveform(c, "ia-window-aaa").update(path="waveforms/ev-1/other.csv.gz"),
        {},
    ),
    ("unknown event", lambda c: c["events"][0].update(event_id="ev-2"), {}),
    (
        "unknown timestamp state",
        None,
        {"ia-window-aaa": _station_csv("ia-window-aaa", "Unknown", timestamp_state="guessed")},
    ),
    (
        "row outside the display window",
        None,
        {"ia-window-aaa": _station_csv("ia-window-aaa", "Unknown", ("2001-01-02T06:00:01Z",) * 3)},
    ),
]


@pytest.mark.parametrize(
    ("edit", "files"), [(e, f) for _, e, f in BAD], ids=[name for name, _, _ in BAD]
)
def test_refuses_input_that_breaks_the_contract(
    tmp_path: Path, edit: Callable[[dict[str, Any]], object] | None, files: dict[str, bytes]
) -> None:
    with pytest.raises(ValueError):
        _export(_source(tmp_path, edit, files), tmp_path / "out")
    assert not (tmp_path / "out/records-ev-1-v1").exists()


def test_refuses_a_station_file_that_differs_from_the_catalog(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (tmp_path / "source/viewer/waveforms/ev-1/ia-window-aaa.csv.gz").write_bytes(
        _station_csv("ia-window-aaa", "Unknown", ("2001-01-01T00:05:00Z",) * 3)
    )
    with pytest.raises(ValueError, match="checksum"):
        _export(source, tmp_path / "out")


def test_refuses_a_release_that_differs_from_the_literals(tmp_path: Path) -> None:
    source = _source(tmp_path)
    release_path = tmp_path / "source/release.json"
    release = json.loads(release_path.read_bytes())
    release["allowed_uses"].reverse()
    release_path.write_text(json.dumps(release), encoding="utf-8")
    with pytest.raises(ValueError, match="release"):
        _export(source, tmp_path / "out")


def test_release_manifest_states_the_descriptive_scope() -> None:
    release = json.loads((ROOT / "artifacts/releases/multi-event-descriptive-v1.json").read_bytes())
    tohoku = json.loads((ROOT / "artifacts/releases/tohoku-descriptive-v1.json").read_bytes())
    for key in ("allowed_uses", "prohibited_uses", "arrival_comparison_allowed"):
        assert release[key] == tohoku[key]
    assert release["physical_arrival_records_released"] == 0
    assert release["continuous_nctr_field"] == "blocked_no_proxy"
    assert release["decision"] == "D-032"
    assert "not validated arrivals, warning times" in release["statement"]
    settings = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert release["source_package"] == {
        "path": settings["catalog"],
        "sha256": settings["catalog_sha256"],
    }


# Real export: every configured event, byte for byte against the published bundles.


def test_real_export_matches_the_catalog_and_the_published_bundles(tmp_path: Path) -> None:
    settings = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    viewer = ROOT / settings["catalog"]
    if not viewer.is_file():
        pytest.skip("local multi-event viewer export unavailable")
    outs = export_display_records(source_root=ROOT, output_root=tmp_path, config_path=CONFIG)
    assert [out.name for out in outs] == [f"records-{i}-v1" for i in settings["event_ids"]]
    catalog = {e["event_id"]: e for e in json.loads(viewer.read_bytes())["events"]}
    for out in outs:
        manifest = _manifest(out)
        event = catalog[manifest["event"]["event_id"]]
        keys = {w["display_station_key"] for w in event["waveforms"]}
        assert [s["display_station_key"] for s in manifest["stations"]] == sorted(keys)
        files = {w["source_id"]: w for w in event["waveforms"]}
        for station in manifest["stations"]:
            export = viewer.parent / files[station["source"]["source_id"]]["path"]
            stored = out / f"stations/{station['station_id']}.csv.gz"
            assert stored.read_bytes() == export.read_bytes()
        rows = sum(s["rows"] for s in manifest["stations"])
        assert manifest["accounting"] == {"station_count": len(keys), "rows": rows}
        published = BUNDLES / out.name
        if published.is_dir():
            names = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
            assert names == sorted(
                p.relative_to(published) for p in published.rglob("*") if p.is_file()
            )
            assert all((out / n).read_bytes() == (published / n).read_bytes() for n in names)


# Every configured ID is a development entry (a test, never a run-time read of the batch).


def _batch_entries() -> dict[str, dict[str, Any]]:
    path = ROOT / "config/ntwc-archive-batch-v2.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))["events"]


def _require_development(event_ids: list[str]) -> None:
    # The guard reports no IDs, so no reserved or excluded entry is ever printed.
    entries = _batch_entries()
    if not all(entries.get(event_id, {}).get("role") == "development" for event_id in event_ids):
        raise ValueError("a configured event is not a development entry of the frozen selection")


def _configured_ids() -> list[str]:
    ids: list[str] = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["event_ids"]
    for path in sorted((ROOT / "config").glob("story-map-layers-*.toml")):
        bundle_id: str = tomllib.loads(path.read_text(encoding="utf-8"))["bundle_id"]
        ids.append(bundle_id.removeprefix("layers-").removesuffix("-v1"))
    return ids


def test_records_and_layers_events_are_development_entries() -> None:
    assert len(_configured_ids()) == 13 + 7
    _require_development(_configured_ids())


def test_development_guard_rejects_another_role() -> None:
    event_ids = _configured_ids()
    event_ids[0] = next(
        i for i, entry in _batch_entries().items() if entry["role"] != "development"
    )
    with pytest.raises(ValueError):
        _require_development(event_ids)
