"""Verified, descriptive-only local browser bundle export."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import tempfile
import tomllib
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pyproj import Transformer

from analysis.story.atlas import (
    DISPLAY_CRS,
    project_line_parts,
    shift_longitude,
    split_at_display_seam,
)
from analysis.story.plots import _load_coastline_parts  # pyright: ignore[reportPrivateUsage]
from pipeline.normalize import IOC_QC_FLAGS

COLUMNS = [
    "observation_id",
    "source_id",
    "station_id",
    "source_time",
    "observed_at_utc",
    "raw_value",
    "fitted_value",
    "residual_value",
    "units",
    "vertical_reference",
    "raw_status",
    "residual_status",
    "grid_status",
    "qc_flags",
    "source_qc_status",
]
NUMBERS = {"raw_value", "fitted_value", "residual_value"}
SOURCE_FIELDS = (
    "source_id",
    "title",
    "publisher",
    "accessed_on",
    "version_or_date",
    "license_or_terms",
    "processing_level",
    "sha256",
)
COVERAGE_FIELDS = (
    "station_id",
    "window_id",
    "start_utc",
    "end_utc_exclusive",
    "accepted_sample_n",
    "valid_sample_n",
    "expected_n",
    "cadence_seconds",
    "source_grid_anchor_utc",
    "absent_n",
    "source_blank_n",
    "off_grid_n",
    "off_grid_valid_n",
    "strict_numerator_n",
    "strict_denominator_n",
    "strict_percent",
    "sample_density_numerator_n",
    "sample_density_denominator_n",
    "sample_density_percent",
    "supported_start_utc",
    "supported_end_utc_exclusive",
    "first_grid_utc",
    "last_grid_utc",
    "first_valid_raw_utc",
    "last_valid_raw_utc",
    "exact_valid_n",
)
SPAN_FIELDS = (
    "station_id",
    "window_id",
    "start_utc",
    "end_utc_exclusive",
    "status",
    "absent_n",
    "source_blank_n",
    "affected_position_n",
    "classification",
    "classification_semantics",
    "endpoint_semantics",
    "left_observed_utc",
    "right_observed_utc",
    "within_block_valid_raw_n",
)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError("source path escapes explicit source root")
    return path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify(root: Path, records: list[dict[str, str]]) -> None:
    seen: set[Path] = set()
    for record in records:
        path = _path(root, record["path"])
        if path in seen or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ValueError("invalid or duplicate fingerprint")
        seen.add(path)
        if _hash(path) != record["sha256"]:
            raise ValueError(f"checksum mismatch: {record['path']}")


def _table(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"schema mismatch: {path.name}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"malformed CSV: {path.name}")
    return rows


def _utc(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise ValueError("timestamp must explicitly use UTC")
    return at


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _number(value: str) -> float | None:
    if not value.strip():
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite measurement")
    return result


def _safe_url(value: str) -> str | None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
    ):
        return None
    return value


def _reference(row: dict[str, str], fields: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in fields:
        if key not in row:
            continue
        value = row[key]
        if key.endswith("_n") or key == "cadence_seconds":
            result[key] = int(value) if value not in ("", "unknown", "not applicable") else None
        elif key.endswith("_percent"):
            result[key] = _number(value) if value != "unknown" else None
        else:
            result[key] = value or "unknown"
    return result


def _geometry(path: Path, stations: list[dict[str, Any]], event: dict[str, Any]) -> dict[str, Any]:
    parts = tuple(
        part for line in _load_coastline_parts(path) for part in split_at_display_seam(line)
    )
    lines = project_line_parts(parts, DISPLAY_CRS)
    transformer = Transformer.from_crs("EPSG:4326", DISPLAY_CRS, always_xy=True, force_over=True)
    points: list[dict[str, Any]] = []
    for item in [event, *stations]:
        x, y = transformer.transform(shift_longitude(item["longitude"]), item["latitude"])
        points.append({"id": item.get("station_id", item.get("event_id")), "x": x, "y": y})
    return {
        "schema_version": "1",
        "display_crs": DISPLAY_CRS,
        "source_crs": "EPSG:4326",
        "coordinate_order": "x,y",
        "central_meridian": -160,
        "coastline": lines,
        "points": points,
        "bounds": [
            min(p[0] for line in lines for p in line),
            min(p[1] for line in lines for p in line),
            max(p[0] for line in lines for p in line),
            max(p[1] for line in lines for p in line),
        ],
    }


def export_demo_bundle(*, source_root: Path, output_root: Path, config_path: Path) -> Path:
    """Verify accepted bytes and atomically export a new descriptive-only bundle.

    No acquisition, source edits, imputation, resampling, onset picks or release
    promotion occur. Verification and grouping are O(n); sorting is O(n log n).
    Raises ValueError for invalid contracts, FileExistsError for existing bundles.
    """
    if not source_root.is_absolute() or not source_root.is_dir():
        raise ValueError("explicit absolute source root with accepted cache is required")
    source_root = source_root.resolve()
    config_bytes = config_path.read_bytes()
    config_sha256 = hashlib.sha256(config_bytes).hexdigest()
    settings = tomllib.loads(config_bytes.decode("utf-8"))
    if settings["schema_version"] != "1" or not re.fullmatch(
        r"[a-zA-Z0-9_-]+", settings["bundle_id"]
    ):
        raise ValueError("unsupported schema or unsafe bundle ID")
    output_root = output_root.resolve()
    destination = output_root / settings["bundle_id"]
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    followup = _path(source_root, settings["followup"])
    anchors = [
        {
            "path": (followup / name).relative_to(source_root).as_posix(),
            "sha256": settings[f"{kind}_sha256"],
        }
        for kind, name in [("inputs", "inputs.json"), ("outputs", "outputs.json")]
    ]
    anchors.extend(
        {"path": settings[key], "sha256": settings[f"{key}_sha256"]}
        for key in ("release", "provenance")
    )
    _verify(source_root, anchors)
    accepted: list[dict[str, str]] = _load_json(followup / "inputs.json")
    outputs: list[dict[str, str]] = _load_json(followup / "outputs.json")
    _verify(source_root, accepted)
    _verify(followup, outputs)
    output_dependencies = [
        {
            "path": _path(followup, r["path"]).relative_to(source_root).as_posix(),
            "sha256": r["sha256"],
        }
        for r in outputs
    ]
    release: dict[str, Any] = _load_json(_path(source_root, settings["release"]))
    if (
        release.get("schema_version") != 1
        or release.get("arrival_comparison_allowed") is not False
        or release.get("physical_arrival_records_released") != 0
        or release.get("continuous_nctr_field") != "blocked_no_proxy"
    ):
        raise ValueError("release is not the accepted descriptive-only contract")
    release_dependencies: list[dict[str, str]] = [
        release[k] for k in ("review_receipt", "input_manifest", "output_manifest")
    ]
    _verify(source_root, release_dependencies)
    processed = _path(source_root, settings["processed"])
    required_inputs = [processed / name for name in ("event.csv", "station.csv", "observation.csv")]
    required_inputs.append(_path(source_root, settings["coastline"]))
    indexed = {r["path"]: r["sha256"] for r in accepted}
    if any(
        indexed.get(path.relative_to(source_root).as_posix()) != _hash(path)
        for path in required_inputs
    ):
        raise ValueError("consumed input lacks accepted fingerprint")
    required_outputs = {
        f"{name}.csv" for name in ("coverage-by-window", "coverage-spans", "gap-blocks")
    }
    if not required_outputs.issubset({r["path"] for r in outputs}):
        raise ValueError("support table lacks accepted fingerprint")
    event_rows = _table(
        processed / "event.csv", {"event_id", "origin_time_utc", "status", "latitude", "longitude"}
    )
    if len(event_rows) != 1 or event_rows[0]["status"] != "reviewed":
        raise ValueError("one reviewed event required")
    event: dict[str, Any] = {key: event_rows[0][key] for key in ("event_id", "origin_time_utc")}
    if event["event_id"] != settings["event_id"]:
        raise ValueError("event differs from accepted cohort")
    _utc(event["origin_time_utc"])
    event.update({key: float(event_rows[0][key]) for key in ("latitude", "longitude")})
    station_rows = _table(
        processed / "station.csv",
        {
            "station_id",
            "source_id",
            "station_type",
            "units",
            "vertical_reference",
            "latitude",
            "longitude",
            "availability",
            "name",
            "horizontal_datum",
            "coordinate_order",
            "time_basis",
        },
    )
    station_index = {s["station_id"]: s for s in station_rows}
    if len(station_rows) != len(station_index) or sorted(station_index) != sorted(
        settings["station_ids"]
    ):
        raise ValueError("duplicate or different station cohort")
    provenance_rows = _table(
        _path(source_root, settings["provenance"]), set(SOURCE_FIELDS) | {"url"}
    )
    provenance = {row["source_id"]: row for row in provenance_rows}
    stations: list[dict[str, Any]] = []
    for _sid, station in sorted(station_index.items()):
        if (
            station["station_type"] not in ("coastal", "dart")
            or station["availability"] != "approved"
        ):
            raise ValueError("unapproved or unknown station type")
        if any(
            not station[k].strip()
            for k in ("source_id", "units", "vertical_reference", "time_basis")
        ):
            raise ValueError("blank measurement semantics")
        source: dict[str, Any] = {
            key: provenance[station["source_id"]][key] or "unknown" for key in SOURCE_FIELDS
        }
        source["url"] = _safe_url(provenance[station["source_id"]]["url"])
        info: dict[str, Any] = {
            key: station[key]
            for key in (
                "station_id",
                "source_id",
                "station_type",
                "name",
                "units",
                "vertical_reference",
                "horizontal_datum",
                "coordinate_order",
                "time_basis",
            )
        }
        info.update({key: float(station[key]) for key in ("latitude", "longitude")})
        if not -90 <= info["latitude"] <= 90 or not -180 <= info["longitude"] <= 180:
            raise ValueError("invalid source coordinates")
        info["source"] = source
        stations.append(info)
    windows: list[dict[str, str]] = settings["windows"]
    if len({w["id"] for w in windows}) != len(windows):
        raise ValueError("duplicate window")
    for window in windows:
        if _utc(window["start_utc"]) >= _utc(window["end_utc_exclusive"]):
            raise ValueError("invalid half-open window")
    if (
        settings["selected_station_id"] not in station_index
        or settings["pinned_station_id"] not in station_index
        or settings["default_window_id"] not in {w["id"] for w in windows}
        or settings["default_product_key"] not in NUMBERS
    ):
        raise ValueError("invalid default selection")
    coverage = _table(
        followup / "coverage-by-window.csv", {"station_id", "window_id", "accepted_sample_n"}
    )
    spans = _table(followup / "coverage-spans.csv", {"station_id", "window_id", "status"})
    gaps = _table(followup / "gap-blocks.csv", {"station_id", "window_id", "status"})
    rows = _table(processed / "observation.csv", set(COLUMNS[:10]) | NUMBERS | {"source_extra"})
    if len(rows) != settings["expected_observation_count"]:
        raise ValueError("source observation count differs")
    grouped: dict[str, list[dict[str, Any]]] = {sid: [] for sid in station_index}
    identities: set[str] = set()
    times: set[tuple[str, str]] = set()
    for row in rows:
        sid = row["station_id"]
        station = station_index.get(sid)
        if station is None or any(
            row[k] != station[k] for k in ("source_id", "units", "vertical_reference")
        ):
            raise ValueError("unknown station or inconsistent observation semantics")
        at = _utc(row["observed_at_utc"])
        key = sid, _stamp(at)
        if not row["observation_id"] or row["observation_id"] in identities or key in times:
            raise ValueError("duplicate or blank observation identity")
        if not row["source_time"].strip():
            raise ValueError("blank source time")
        identities.add(row["observation_id"])
        times.add(key)
        record: dict[str, Any] = {k: row[k] for k in COLUMNS[:10] if k not in NUMBERS}
        record.update({k: _number(row[k]) for k in NUMBERS})
        extra = row["source_extra"]
        parsed: dict[str, Any] = json.loads(extra) if extra.startswith("{") else {}
        flags = {k: str(parsed[k]) for k in IOC_QC_FLAGS if k in parsed}
        if any(
            value not in ("T", "F", "True", "False", "true", "false", "0", "1", "unknown")
            for value in flags.values()
        ):
            raise ValueError("unknown QC encoding")
        record["qc_flags"] = flags
        record["source_qc_status"] = (
            (
                "flagged"
                if any(v.upper() in ("T", "TRUE", "1") for v in flags.values())
                else "not_flagged"
            )
            if flags
            else "not_reported"
        )
        record["raw_status"] = "source_blank" if record["raw_value"] is None else "observed"
        record["residual_status"] = (
            "available"
            if record["residual_value"] is not None
            else "source_blank"
            if station["station_type"] == "dart"
            else "structurally_not_applicable"
        )
        grid = next((r for r in coverage if r["station_id"] == sid), None)
        if station["station_type"] == "coastal":
            if grid is None:
                raise ValueError("coastal source grid missing")
            offset = (at - _utc(grid["source_grid_anchor_utc"])).total_seconds()
            record["grid_status"] = (
                "on_grid" if offset % int(grid["cadence_seconds"]) == 0 else "off_grid"
            )
        else:
            record["grid_status"] = "not_applicable"
        grouped[sid].append(record)
    chunks: dict[str, dict[str, Any]] = {}
    for station in stations:
        sid = station["station_id"]
        records = sorted(grouped[sid], key=lambda r: (r["observed_at_utc"], r["observation_id"]))
        if not records:
            raise ValueError("station has no source observations")
        support: list[dict[str, Any]] = []
        selected_windows = [
            *windows,
            {
                "id": "source_full",
                "label": "Full source record",
                "start_utc": records[0]["observed_at_utc"],
                "end_utc_exclusive": _stamp(
                    _utc(records[-1]["observed_at_utc"]) + timedelta(microseconds=1)
                ),
            },
        ]
        for window in selected_windows:
            selected = [
                r
                for r in records
                if _utc(window["start_utc"])
                <= _utc(r["observed_at_utc"])
                < _utc(window["end_utc_exclusive"])
            ]
            table = next(
                (r for r in coverage if r["station_id"] == sid and r["window_id"] == window["id"]),
                None,
            )
            if station["station_type"] == "coastal":
                if table is None:
                    raise ValueError("reviewed coastal window missing")
                # Full source bounds are publisher-supported, not inferred from final observation.
                if window["id"] == "source_full":
                    selected = records
                entry = _reference(table, COVERAGE_FIELDS)
                if int(table["accepted_sample_n"]) != len(selected):
                    raise ValueError("window/source observation counts disagree")
                if int(table["valid_sample_n"]) != sum(
                    r["raw_value"] is not None for r in selected
                ):
                    raise ValueError("window/source valid counts disagree")
                entry["support_kind"] = "coastal_exact_grid"
            else:
                deltas = Counter(
                    (_utc(b["observed_at_utc"]) - _utc(a["observed_at_utc"])).total_seconds()
                    for a, b in zip(selected, selected[1:], strict=False)
                )
                entry = {
                    "station_id": sid,
                    "window_id": window["id"],
                    "start_utc": window["start_utc"],
                    "end_utc_exclusive": window["end_utc_exclusive"],
                    "support_kind": "dart_actual_timestamps",
                    "accepted_sample_n": len(selected),
                    "valid_sample_n": sum(r["raw_value"] is not None for r in selected),
                    "source_blank_n": sum(r["raw_value"] is None for r in selected),
                    "strict_percent": None,
                    "strict_numerator_n": None,
                    "strict_denominator_n": None,
                    "cadence_seconds_counts": [
                        {"seconds": seconds, "count": count}
                        for seconds, count in sorted(deltas.items())
                    ],
                }
            entry["product_valid_n"] = {
                key: sum(r[key] is not None for r in selected) for key in sorted(NUMBERS)
            }
            support.append(entry)
        station["observation_count"] = len(records)
        station["products"] = [
            {
                "key": key,
                "label": {
                    "raw_value": "Raw water column"
                    if station["station_type"] == "dart"
                    else "Raw coastal water level",
                    "fitted_value": "Publisher retrospective fitted tide",
                    "residual_value": "Publisher retrospective residual",
                }[key],
                "units": station["units"],
                "available": any(r[key] is not None for r in records),
            }
            for key in ("raw_value", "residual_value", "fitted_value")
        ]
        chunks[sid] = {
            "schema_version": "1",
            "station_id": sid,
            "columns": COLUMNS,
            "rows": [[r[k] for k in COLUMNS] for r in records],
            "support": support,
            "coverage_spans": [_reference(r, SPAN_FIELDS) for r in spans if r["station_id"] == sid],
            "gap_blocks": [_reference(r, SPAN_FIELDS) for r in gaps if r["station_id"] == sid],
        }
    geometry = _geometry(required_inputs[-1], stations, event)
    output_root.mkdir(parents=True, exist_ok=True)
    lock = output_root / f".{settings['bundle_id']}.lock"
    lock.mkdir()
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{settings['bundle_id']}-", dir=output_root
        ) as temporary:
            staging = Path(temporary)
            _write_json(staging / "geometry.json", geometry)
            for sid, chunk in chunks.items():
                _write_json(staging / f"stations/{sid}.json", chunk)
            assets = [
                {
                    "path": path.relative_to(staging).as_posix(),
                    "sha256": _hash(path),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(staging.rglob("*.json"))
            ]
            manifest = {
                "schema_version": "1",
                "exporter_version": "1",
                "bundle_id": settings["bundle_id"],
                "evidence_state": "internal_descriptive_only",
                "event": event,
                "release": {
                    key: release[key]
                    for key in (
                        "release_id",
                        "arrival_comparison_allowed",
                        "physical_arrival_records_released",
                        "continuous_nctr_field",
                        "allowed_uses",
                        "prohibited_uses",
                    )
                },
                "windows": [
                    *windows,
                    {"id": "source_full", "label": "Full source record (station-specific bounds)"},
                ],
                "default_state": {
                    "selectedStationId": settings["selected_station_id"],
                    "pinnedStationId": settings["pinned_station_id"],
                    "windowId": settings["default_window_id"],
                    "productKey": settings["default_product_key"],
                },
                "stations": stations,
                "assets": assets,
                "geometry_path": "geometry.json",
                "input_fingerprints": sorted(
                    {
                        r["path"]: r
                        for r in accepted + anchors + output_dependencies + release_dependencies
                    }.values(),
                    key=lambda r: r["path"],
                ),
                "config_sha256": config_sha256,
                "accounting": {
                    "source_observation_count": len(rows),
                    "exported_observation_count": sum(len(c["rows"]) for c in chunks.values()),
                    "station_count": len(stations),
                    "rejected_observation_count": 0,
                },
            }
            _write_json(staging / "manifest.json", manifest)
            # Recheck immutable inputs before publication; no partially written bundle is visible.
            _verify(source_root, accepted)
            _verify(source_root, anchors)
            _verify(followup, outputs)
            _verify(source_root, release_dependencies)
            if _hash(config_path) != config_sha256:
                raise ValueError("config checksum changed during export")
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(destination)
            staging.rename(destination)
    finally:
        lock.rmdir()
    return destination


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
    )
