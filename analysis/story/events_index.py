"""Events index (`events.json`, schema 2): lists events and pins their verified bundles.

The index is the browser's upstream anchor. The builder reads no selection role;
a test keeps every configured event ID inside the frozen development selection.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pyproj import Transformer

from analysis.story.atlas import DISPLAY_CRS, shift_longitude
from analysis.story.demo_export import (
    _hash,  # pyright: ignore[reportPrivateUsage]
    _path,  # pyright: ignore[reportPrivateUsage]
    _utc,  # pyright: ignore[reportPrivateUsage]
    _write_json,  # pyright: ignore[reportPrivateUsage]
)

FIELDS = (
    "event_id",
    "label",
    "origin_time_utc",
    "latitude",
    "longitude",
    "magnitude",
    "magnitude_type",
)
CONFIG_FIELDS = tuple(field for field in FIELDS if field != "label")  # labels: the names table
IDENTITY = ("event_id", "origin_time_utc", "latitude", "longitude")
BUNDLE_OPTIONS = {"records_bundle", "layers_bundle", "arrivals"}
INDEX_KEYS = {"schema_version", "evidence_state", "default_event_id", "basemap", "events"}
EVENT_KEYS = {*FIELDS, "x", "y", "counts", "records", "layers", "arrivals"}
BUNDLE_KEYS = {"bundle_id", "manifest_sha256", "manifest_bytes"}
ASSET_KEYS = {"path", "sha256", "bytes"}
COUNT_KEYS = {
    "ntwc_pairs",
    "ntwc_pairs_with_position",
    "ntwc_reported",
    "ncei_reported",
    "stations",
    "reported_per_hour",
}
CLOCK_HOURS = 30
EXCLUDED_REASON = "no_records_and_no_drawable_reported_time"
MAX_ARRIVALS_BYTES = 2_097_152
# Size budgets (raw bytes; 1 KB = 1,024 bytes as in the 2 MB = 2,097,152 rule).
MAX_ASSET_BYTES = 2_097_152  # every listed file except the Tōhoku schema-1 records bundle
MAX_EVENT_BYTES = 3_145_728  # opening an event, before any station record
MAX_FIRST_SCREEN_BYTES = 307_200  # index and basemap
SAFE_ID = r"[a-zA-Z0-9_-]+"
SHA256 = r"[0-9a-f]{64}"
NONEMPTY = r"(?s).+"
UTC_TIME = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z"
BASEMAP_PATH = rf"{SAFE_ID}/coastline\.json"


def _object(value: object, keys: set[str], what: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(cast(dict[str, Any], value)) != keys:
        raise ValueError(f"{what} must have exactly the keys {sorted(keys)}")
    return cast(dict[str, Any], value)


def _text(value: object, pattern: str, what: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"{what} must be a string matching {pattern}: {value!r}")
    return value


def _number(value: object, limit: float, what: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or abs(value) > limit
    ):
        raise ValueError(f"{what} must be a finite number within ±{limit}: {value!r}")


def _count(value: object, what: str, limit: float = math.inf) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= limit:
        raise ValueError(f"{what} must be a positive integer of at most {limit}: {value!r}")


def _whole(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{what} must be a nonnegative JSON integer: {value!r}")
    return value


def _asset_ref(value: object, pattern: str, what: str, limit: int) -> str:
    ref = _object(value, ASSET_KEYS, what)
    path = _text(ref["path"], pattern, f"{what}.path")
    _text(ref["sha256"], SHA256, f"{what}.sha256")
    _count(ref["bytes"], f"{what}.bytes", limit)
    return path


def _counts(event: dict[str, Any]) -> None:
    """Whole counts; one hour array per source over the 30-hour clock; null refs give zeros."""
    counts = _object(event["counts"], COUNT_KEYS, "counts")
    hours = _object(counts["reported_per_hour"], {"ntwc", "ncei"}, "counts.reported_per_hour")
    for key in sorted(COUNT_KEYS - {"reported_per_hour"}):
        _whole(counts[key], f"counts.{key}")
    on_clock = 0
    for source, total in (("ntwc", "ntwc_reported"), ("ncei", "ncei_reported")):
        per_hour = hours[source]
        if not isinstance(per_hour, list) or len(cast(list[object], per_hour)) != CLOCK_HOURS:
            raise ValueError(f"reported_per_hour.{source} must be an array of {CLOCK_HOURS}")
        hourly = [_whole(n, f"reported_per_hour.{source}") for n in cast(list[object], per_hour)]
        if sum(hourly) > counts[total]:
            raise ValueError(f"reported_per_hour.{source} counts more than counts.{total}")
        on_clock += sum(hourly)
    if counts["ntwc_pairs_with_position"] > counts["ntwc_pairs"]:
        raise ValueError("counts.ntwc_pairs_with_position exceeds counts.ntwc_pairs")
    if event["records"] is None and counts["stations"] != 0:
        raise ValueError("an event without a records bundle has 0 stations")
    reported = [counts[key] for key in COUNT_KEYS - {"stations", "reported_per_hour"}]
    if event["arrivals"] is None and (any(reported) or on_clock):
        raise ValueError("an event without a reported-times file has zero counts")


def validate_events_index(value: object) -> None:
    """Apply every schema-2 index rule to a parsed JSON value; touch no file.

    Raises ValueError naming the first broken rule. O(n log n) in the event count.
    """
    index = _object(value, INDEX_KEYS, "index")
    if index["schema_version"] != "2" or index["evidence_state"] != "internal_descriptive_only":
        raise ValueError("index must be schema_version 2 and internal_descriptive_only")
    _asset_ref(index["basemap"], BASEMAP_PATH, "basemap", MAX_ASSET_BYTES)
    if not isinstance(index["events"], list):
        raise ValueError("events must be an array")
    order: list[tuple[datetime, str]] = []
    bundle_ids: list[str] = []
    for item in cast(list[object], index["events"]):
        event = _object(item, EVENT_KEYS, "event")
        event_id = _text(event["event_id"], SAFE_ID, "event_id")
        origin = _text(event["origin_time_utc"], UTC_TIME, "origin_time_utc")
        order.append((_utc(origin), event_id))
        _text(event["label"], NONEMPTY, "label")
        _text(event["magnitude_type"], NONEMPTY, "magnitude_type")
        _number(event["latitude"], 90, "latitude")
        _number(event["longitude"], 180, "longitude")
        _number(event["magnitude"], math.inf, "magnitude")
        for axis in ("x", "y"):
            if isinstance(event[axis], bool) or not isinstance(event[axis], int):
                raise ValueError(f"{axis} must be a JSON integer: {event[axis]!r}")
        for kind in ("records", "layers"):
            if event[kind] is not None:
                ref = _object(event[kind], BUNDLE_KEYS, kind)
                bundle_ids.append(_text(ref["bundle_id"], SAFE_ID, f"{kind}.bundle_id"))
                _text(ref["manifest_sha256"], SHA256, f"{kind}.manifest_sha256")
                _count(ref["manifest_bytes"], f"{kind}.manifest_bytes")
        if event["arrivals"] is not None:
            pattern = rf"{SAFE_ID}/{SAFE_ID}\.json"
            path = _asset_ref(event["arrivals"], pattern, "arrivals", MAX_ARRIVALS_BYTES)
            if path.split("/")[1] != f"{event_id}.json":
                raise ValueError(f"arrivals file must be named {event_id}.json: {path}")
        _counts(event)
    event_ids = [event_id for _, event_id in order]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("event IDs must be unique")
    if len(set(bundle_ids)) != len(bundle_ids):
        raise ValueError("each bundle ID must be used by one event only")
    if order != sorted(order):
        raise ValueError("events must sort by origin instant, then event_id")
    if index["default_event_id"] not in event_ids:
        raise ValueError("default_event_id must name a listed event")


def _pin(root: Path, bundle_id: object) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """Check every manifest asset's bytes and SHA-256; return the BundleRef, manifest, sizes."""
    bundle_id = _text(bundle_id, SAFE_ID, "bundle name")
    directory = _path(root, bundle_id)
    data = _path(directory, "manifest.json").read_bytes()
    manifest: dict[str, Any] = json.loads(data)
    if manifest.get("bundle_id") != bundle_id:
        raise ValueError(f"manifest bundle_id differs from its directory: {bundle_id}")
    sizes = {f"{bundle_id}/manifest.json": len(data)}
    for asset in manifest["assets"]:
        path = _path(directory, asset["path"])
        if path.stat().st_size != asset["bytes"] or _hash(path) != asset["sha256"]:
            raise ValueError(f"asset differs from its manifest: {bundle_id}/{asset['path']}")
        sizes[f"{bundle_id}/{asset['path']}"] = asset["bytes"]
    ref = {
        "bundle_id": bundle_id,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "manifest_bytes": len(data),
    }
    return ref, manifest, sizes


def _arrivals(
    root: Path, entry: dict[str, Any], stations: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pin a reported-times file; check its rules, identity and record links."""
    from analysis.story.arrivals_export import validate_arrivals  # it imports this module

    path = _text(entry["arrivals"], rf"{SAFE_ID}/{SAFE_ID}\.json", "arrivals name")
    data = _path(root, path).read_bytes()
    value: dict[str, Any] = json.loads(data)
    validate_arrivals(value)
    identity = (entry["event_id"], entry["origin_time_utc"])
    if (value["event_id"], value["origin_time_utc"]) != identity:
        raise ValueError(f"arrivals event differs from config: {entry['event_id']}")
    for place in value["places"]:
        if place["record"] is not None and place["record"]["station_id"] not in stations:
            raise ValueError(f"arrivals record names no station of the records bundle: {path}")
    ref = {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return ref, value


def _on_clock(report: dict[str, Any]) -> bool:
    minutes = report["reported_minutes"]
    return minutes is not None and 0 <= minutes < CLOCK_HOURS * 60


def _event_counts(arrivals: dict[str, Any] | None, stations: int) -> dict[str, Any]:
    """Copy the reported-times accounting; count reported times on the clock by hour."""
    per_hour = {"ntwc": [0] * CLOCK_HOURS, "ncei": [0] * CLOCK_HOURS}
    counts = dict.fromkeys(COUNT_KEYS - {"stations", "reported_per_hour"}, 0)
    if arrivals is not None:
        for report in arrivals["reports"]:
            if _on_clock(report):
                per_hour[report["source"]][int(report["reported_minutes"] // 60)] += 1
        accounting = arrivals["accounting"]
        counts = {
            "ntwc_pairs": accounting["ntwc_rows_with_both_times"],
            "ntwc_pairs_with_position": accounting["ntwc_pairs_with_position"],
            "ntwc_reported": accounting["ntwc_rows_with_reported_time"],
            "ncei_reported": accounting["ncei_reported_durations"],
        }
    return counts | {"stations": stations, "reported_per_hour": per_hour}


def _labels(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    labels = {row["event_id"]: row["label"] for row in rows}
    if reader.fieldnames != ["event_id", "label"] or len(labels) != len(rows):
        raise ValueError("names table must have columns event_id,label and one row per event")
    return labels


def _budget(event_id: str, sizes: dict[str, int], stations: set[str], exempt: set[str]) -> None:
    opening = sum(size for path, size in sizes.items() if path not in stations)
    if opening > MAX_EVENT_BYTES:
        raise ValueError(f"opening {event_id} needs {opening} bytes, over {MAX_EVENT_BYTES}")
    for path, size in sizes.items():
        if size > MAX_ASSET_BYTES and path not in exempt:
            raise ValueError(f"file of {size} bytes is over {MAX_ASSET_BYTES}: {path}")


def build_events_index(
    *, bundles_root: Path, config_path: Path, report_path: Path, replace: bool = False
) -> Path:
    """Verify the listed bundles, publish `<bundles_root>/events.json` by one rename, and report.

    An event is listed when it has a records bundle or a drawable reported time. An identical
    index is left alone; a different one is replaced only with `replace`; a symlinked index is
    always refused. The report (excluded events, every listed file's bytes, totals) goes to
    `report_path`, outside the bundles root. Raises ValueError for unsafe, changed, invalid or
    oversized input and FileExistsError for a different existing index. Work is linear in the
    listed bundles' bytes.
    """
    root = bundles_root.resolve()
    if not root.is_dir():
        raise ValueError("bundles root must be an existing directory")
    report = report_path.resolve()
    if report.is_relative_to(root):
        raise ValueError("the report must be written outside the bundles root")
    settings = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if set(settings) != {"default_event_id", "names", "basemap", "events"}:
        raise ValueError("config must give exactly default_event_id, names, basemap and events")
    labels = _labels(config_path.parent / settings["names"])
    basemap_path = _text(settings["basemap"], BASEMAP_PATH, "basemap")
    basemap_data = _path(root, basemap_path).read_bytes()
    basemap: dict[str, Any] = {
        "path": basemap_path,
        "sha256": hashlib.sha256(basemap_data).hexdigest(),
        "bytes": len(basemap_data),
    }
    files = {basemap_path: len(basemap_data)}
    transformer = Transformer.from_crs("EPSG:4326", DISPLAY_CRS, always_xy=True, force_over=True)
    events: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for entry in settings["events"]:
        if not set(CONFIG_FIELDS) <= set(entry) <= set(CONFIG_FIELDS) | BUNDLE_OPTIONS:
            raise ValueError(f"config event needs {CONFIG_FIELDS} and only {BUNDLE_OPTIONS}")
        event: dict[str, Any] = {key: entry[key] for key in CONFIG_FIELDS}
        event |= {"records": None, "layers": None, "arrivals": None}
        stations: set[str] = set()
        sizes: dict[str, int] = {}
        station_files: set[str] = set()
        exempt: set[str] = set()
        arrivals = None
        if "records_bundle" in entry:
            event["records"], manifest, found = _pin(root, entry["records_bundle"])
            if manifest.get("event") != {key: entry[key] for key in IDENTITY}:
                raise ValueError(f"records manifest event differs from config: {entry['event_id']}")
            stations = {station["station_id"] for station in manifest.get("stations", [])}
            sizes |= found
            station_files = {path for path in found if path.split("/")[1] == "stations"}
            if manifest.get("schema_version") == "1":  # Tōhoku predates the 2 MB asset limit
                exempt = set(found)
        if "layers_bundle" in entry:
            event["layers"], manifest, found = _pin(root, entry["layers_bundle"])
            if manifest.get("origin_time_utc") != entry["origin_time_utc"]:
                raise ValueError(f"layers manifest origin differs from config: {entry['event_id']}")
            sizes |= found
        if "arrivals" in entry:
            event["arrivals"], arrivals = _arrivals(root, entry, stations)
            sizes[event["arrivals"]["path"]] = event["arrivals"]["bytes"]
        drawable = arrivals is not None and any(
            _on_clock(report) and report["site_id"] is not None for report in arrivals["reports"]
        )
        if event["records"] is None and not drawable:
            excluded.append({"event_id": entry["event_id"], "reason": EXCLUDED_REASON})
            continue
        _budget(entry["event_id"], sizes, station_files, exempt)
        x, y = transformer.transform(shift_longitude(entry["longitude"]), entry["latitude"])
        event |= {"x": round(x), "y": round(y), "counts": _event_counts(arrivals, len(stations))}
        events.append(event)
        files |= sizes
    if set(labels) != {event["event_id"] for event in events}:
        raise ValueError("the names table must label exactly the listed events")
    for event in events:
        event["label"] = labels[event["event_id"]]
    events.sort(key=lambda event: (_utc(event["origin_time_utc"]), event["event_id"]))
    index = {
        "schema_version": "2",
        "evidence_state": "internal_descriptive_only",
        "default_event_id": settings["default_event_id"],
        "basemap": basemap,
        "events": events,
    }
    validate_events_index(index)
    target = root / "events.json"
    # ponytail: the staged file sits in a hidden sibling directory (same filesystem), as in
    # map_layers; the rename replaces events.json atomically and the directory is removed.
    with tempfile.TemporaryDirectory(prefix=".events-", dir=root) as temporary:
        staged = Path(temporary) / "events.json"
        _write_json(staged, index)
        files["events.json"] = staged.stat().st_size
        if files["events.json"] + basemap["bytes"] > MAX_FIRST_SCREEN_BYTES:
            raise ValueError(f"index and basemap exceed {MAX_FIRST_SCREEN_BYTES} bytes")
        if target.is_symlink():
            raise ValueError(f"existing events index is a symbolic link: {target}")
        if not target.exists() or target.read_bytes() != staged.read_bytes():
            if target.exists() and not replace:
                raise FileExistsError(f"a different events index exists (use replace): {target}")
            staged.replace(target)
    _write_json(
        report,
        {
            "schema_version": "1",
            "excluded": sorted(excluded, key=lambda item: item["event_id"]),
            "files": [{"path": path, "bytes": size} for path, size in sorted(files.items())],
            "totals": {
                "listed_events": len(events),
                "excluded_events": len(excluded),
                "bytes": sum(files.values()),
            },
        },
    )
    return target
