"""Records schema 2 (`records-<event_id>-v1`): display slices from the multi-event viewer export.

Each station's chosen gzip CSV is copied byte for byte; nothing is filled, resampled or picked.
The rows are descriptive source records, not validated arrivals or warning times.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
import tempfile
import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Any

from pyproj import Geod

from analysis.story.demo_export import (
    _geometry,  # pyright: ignore[reportPrivateUsage]
    _hash,  # pyright: ignore[reportPrivateUsage]
    _path,  # pyright: ignore[reportPrivateUsage]
    _safe_url,  # pyright: ignore[reportPrivateUsage]
    _utc,  # pyright: ignore[reportPrivateUsage]
    _write_json,  # pyright: ignore[reportPrivateUsage]
)
from analysis.story.events_index import (
    SAFE_ID,
    UTC_TIME,
    _text,  # pyright: ignore[reportPrivateUsage]
)

RELEASE: dict[str, Any] = {
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
PRODUCTS = ("one_minute_water_level", "water_level", "archive_window")  # preference order
DATUMS = {"STND": "STND", "MLLW": "MLLW", "Unknown": "unknown"}
COLUMNS = [
    "event_id",
    "source_id",
    "station_key",
    "sensor",
    "timestamp_utc",
    "numeric_value",
    "value_state",
    "timestamp_state",
    "duplicate_timestamp",
    "units",
    "vertical_datum",
    "qc_state",
    "qc_json",
]
STATES = {
    "value_state": {"finite_numeric", "blank"},
    "timestamp_state": {
        "reported_utc",
        "epoch_calendar_agree",
        "epoch_calendar_minute_agree",
        "header_day_end_boundary",
    },
    "duplicate_timestamp": {"True", "False"},
    "qc_state": {"provided", "not_provided"},
}


def _product(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "one_minute_water_level" in name:
        return "one_minute_water_level"
    if "water_level" in name:
        return "water_level"
    if name.startswith("ia-window-"):
        return "archive_window"
    raise ValueError(f"export file names no known product: {path}")


def _choose(files: list[dict[str, Any]]) -> dict[str, Any]:
    """One-minute, else six-minute, else archive window; then coverage, longest run, source_id."""
    return min(
        files,
        key=lambda f: (
            PRODUCTS.index(_product(f["path"])),
            -f["coverage_fraction"],
            -f["longest_supported_minutes"],
            f["source_id"],
        ),
    )


def _coordinate(value: object, limit: float, what: str) -> float:
    number = float(value) if isinstance(value, str | int | float) else math.nan
    if isinstance(value, bool) or not math.isfinite(number) or abs(number) > limit:
        raise ValueError(f"{what} must be a finite number within ±{limit}: {value!r}")
    return number


def _station(file: dict[str, Any], station_id: str) -> dict[str, Any]:
    if file["units"] != "m" or file["vertical_datum"] not in DATUMS:
        raise ValueError(f"unexpected units or datum: {file['source_id']}")
    return {
        "station_id": station_id,
        "display_station_key": file["display_station_key"],
        "name": file["station_name"],
        "product": _product(file["path"]),
        "latitude": _coordinate(file["latitude"], 90, "latitude"),
        "longitude": _coordinate(file["longitude"], 180, "longitude"),
        "units": file["units"],
        "vertical_datum": DATUMS[file["vertical_datum"]],
        "source": {
            "source_id": file["source_id"],
            "sha256": file["source_sha256"],
            "url": _safe_url(file["source_url"]),
        },
        "coverage_fraction": file["coverage_fraction"],
        "longest_supported_minutes": file["longest_supported_minutes"],
        "coverage_rule_id": file["coverage_rule_id"],
        "rows": file["rows"],
    }


def _check_rows(data: bytes, file: dict[str, Any], event_id: str, window: dict[str, str]) -> None:
    """The copied file must hold the catalog's rows with the contract's columns and states."""
    reader = csv.DictReader(io.StringIO(gzip.decompress(data).decode("utf-8")))
    rows = list(reader)
    if reader.fieldnames != COLUMNS or len(rows) != file["rows"]:
        raise ValueError(f"columns or row count differ from the catalog: {file['source_id']}")
    start, end = _utc(window["start_utc"]), _utc(window["end_utc_exclusive"])
    for row in rows:
        if (
            any(row[key] not in allowed for key, allowed in STATES.items())
            or (row["event_id"], row["units"], row["vertical_datum"])
            != (event_id, file["units"], file["vertical_datum"])
            or not start <= _utc(row["timestamp_utc"]) < end
        ):
            raise ValueError(f"row breaks the display-slice contract: {file['source_id']}")


def _window(origin: str) -> dict[str, str]:
    """Origin −6 h to +30 h; whole hours keep the origin's own fraction digits."""
    at, fraction = _utc(origin), origin[19:]

    def shift(hours: int) -> str:
        return (at + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S") + fraction

    return {
        "id": "display",
        "label": "6 hours before to 30 hours after the origin",
        "start_utc": shift(-6),
        "end_utc_exclusive": shift(30),
    }


def _bundle(
    event: dict[str, Any], viewer: Path, coastline: Path
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, Any]]:
    """Return the manifest body, the station files by asset path, and the geometry."""
    identity: dict[str, Any] = {
        "event_id": event["event_id"],
        "origin_time_utc": _text(event["origin_utc"], UTC_TIME, "origin_utc"),
        "latitude": _coordinate(event["latitude"], 90, "latitude"),
        "longitude": _coordinate(event["longitude"], 180, "longitude"),
    }
    window = _window(identity["origin_time_utc"])
    by_station: dict[str, list[dict[str, Any]]] = {}
    for file in event["waveforms"]:
        key = re.fullmatch(rf"coops:({SAFE_ID})", file["display_station_key"])
        if key is None:
            raise ValueError(f"unexpected display_station_key: {file['display_station_key']!r}")
        by_station.setdefault(key[1], []).append(file)
    stations: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    for station_id in sorted(by_station):
        chosen = _choose(by_station[station_id])
        data = _path(viewer, chosen["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != chosen["sha256"]:
            raise ValueError(f"checksum mismatch: {chosen['path']}")
        _check_rows(data, chosen, identity["event_id"], window)
        stations.append(_station(chosen, station_id))
        files[f"stations/{station_id}.csv.gz"] = data
    geod = Geod(ellps="WGS84")
    lon, lat = identity["longitude"], identity["latitude"]
    default = min(
        stations,
        key=lambda s: (geod.inv(lon, lat, s["longitude"], s["latitude"])[2], s["station_id"]),
    )
    body = {
        "event": identity,
        "window": window,
        "default_station_id": default["station_id"],
        "stations": stations,
        "accounting": {"station_count": len(stations), "rows": sum(s["rows"] for s in stations)},
    }
    return body, files, _geometry(coastline, stations, identity)


def export_display_records(
    *, source_root: Path, output_root: Path, config_path: Path
) -> list[Path]:
    """Verify the viewer export and publish one new records bundle per configured event.

    Each bundle is staged completely and published by its own rename; an existing bundle is
    never overwritten. Raises ValueError for unsafe, changed or contract-breaking input and
    FileExistsError for an existing bundle. Linear in the chosen station rows.
    """
    if not source_root.is_absolute() or not source_root.is_dir():
        raise ValueError("explicit absolute source root is required")
    source_root = source_root.resolve()
    config_bytes = config_path.read_bytes()
    settings = tomllib.loads(config_bytes.decode("utf-8"))
    keys = {"catalog", "catalog_sha256", "release_manifest", "coastline", "coastline_sha256"}
    if set(settings) != keys | {"event_ids"}:
        raise ValueError(f"config must give exactly {sorted(keys | {'event_ids'})}")
    checked = {
        settings["catalog"]: settings["catalog_sha256"],
        settings["coastline"]: settings["coastline_sha256"],
    }
    _verify(source_root, checked)
    release_bytes = _path(source_root, settings["release_manifest"]).read_bytes()
    release = json.loads(release_bytes)
    if json.dumps({k: release.get(k) for k in RELEASE}) != json.dumps(RELEASE):
        raise ValueError("release manifest fields differ from the schema-1 release literals")
    if release.get("source_package") != {
        "path": settings["catalog"],
        "sha256": settings["catalog_sha256"],
    }:
        raise ValueError("release manifest names another source package")
    checked[settings["release_manifest"]] = hashlib.sha256(release_bytes).hexdigest()
    catalog_path = _path(source_root, settings["catalog"])
    events = {event["event_id"]: event for event in json.loads(catalog_path.read_bytes())["events"]}
    output_root = output_root.resolve()
    names = [f"records-{_text(i, SAFE_ID, 'event_id')}-v1" for i in settings["event_ids"]]
    if len(set(names)) != len(names) or not names:
        raise ValueError("event_ids must be nonempty and unique")
    for name in names:
        if (output_root / name).exists() or (output_root / name).is_symlink():
            raise FileExistsError(output_root / name)
    fingerprints = [{"path": path, "sha256": sha} for path, sha in sorted(checked.items())]
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".records-", dir=output_root) as temporary:
        for event_id, name in zip(settings["event_ids"], names, strict=True):
            if event_id not in events:
                raise ValueError(f"event absent from the viewer catalog: {event_id}")
            body, files, geometry = _bundle(
                events[event_id], catalog_path.parent, _path(source_root, settings["coastline"])
            )
            staging = Path(temporary) / name
            _write_json(staging / "geometry.json", geometry)
            assets = [_asset(staging, "geometry.json", "identity")]
            for path, data in sorted(files.items()):
                (staging / path).parent.mkdir(parents=True, exist_ok=True)
                (staging / path).write_bytes(data)
                assets.append(_asset(staging, path, "gzip"))
            _write_json(
                staging / "manifest.json",
                {
                    "schema_version": "2",
                    "exporter_version": "1",
                    "bundle_id": name,
                    "evidence_state": "internal_descriptive_only",
                    **body,
                    "release": {key: release[key] for key in RELEASE},
                    "assets": assets,
                    "geometry_path": "geometry.json",
                    "input_fingerprints": fingerprints,
                    "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
                },
            )
        # Recheck immutable inputs before publication; no partial bundle becomes visible.
        _verify(source_root, checked)
        if _hash(config_path) != hashlib.sha256(config_bytes).hexdigest():
            raise ValueError("config checksum changed during export")
        for name in names:
            if (output_root / name).exists() or (output_root / name).is_symlink():
                raise FileExistsError(output_root / name)
            (Path(temporary) / name).rename(output_root / name)
    return [output_root / name for name in names]


def _asset(staging: Path, path: str, encoding: str) -> dict[str, Any]:
    stored = staging / path
    return {
        "path": path,
        "sha256": _hash(stored),
        "bytes": stored.stat().st_size,
        "content_encoding": encoding,
    }


def _verify(root: Path, checked: dict[str, str]) -> None:
    for relative, sha256 in checked.items():
        if _hash(_path(root, relative)) != sha256:
            raise ValueError(f"checksum mismatch: {relative}")
