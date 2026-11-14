"""Events index (`events.json`, schema 1): lists events and pins their verified bundles.

The index is the browser's upstream anchor. The builder reads no selection role;
a test keeps every configured event ID inside the frozen development selection.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, cast

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
IDENTITY = ("event_id", "origin_time_utc", "latitude", "longitude")
BUNDLE_OPTIONS = {"records_bundle", "layers_bundle"}
INDEX_KEYS = {"schema_version", "evidence_state", "default_event_id", "events"}
EVENT_KEYS = {*FIELDS, "records", "layers", "arrivals"}
BUNDLE_KEYS = {"bundle_id", "manifest_sha256", "manifest_bytes"}
ASSET_KEYS = {"path", "sha256", "bytes"}
MAX_ARRIVALS_BYTES = 2_097_152
SAFE_ID = r"[a-zA-Z0-9_-]+"
SHA256 = r"[0-9a-f]{64}"
NONEMPTY = r"(?s).+"
UTC_TIME = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z"


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


def validate_events_index(value: object) -> None:
    """Apply every schema-1 index rule to a parsed JSON value; touch no file.

    Raises ValueError naming the first broken rule. O(n log n) in the event count.
    """
    index = _object(value, INDEX_KEYS, "index")
    if index["schema_version"] != "1" or index["evidence_state"] != "internal_descriptive_only":
        raise ValueError("index must be schema_version 1 and internal_descriptive_only")
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
        for kind in ("records", "layers"):
            if event[kind] is not None:
                ref = _object(event[kind], BUNDLE_KEYS, kind)
                bundle_ids.append(_text(ref["bundle_id"], SAFE_ID, f"{kind}.bundle_id"))
                _text(ref["manifest_sha256"], SHA256, f"{kind}.manifest_sha256")
                _count(ref["manifest_bytes"], f"{kind}.manifest_bytes")
        if event["arrivals"] is not None:
            ref = _object(event["arrivals"], ASSET_KEYS, "arrivals")
            path = _text(ref["path"], rf"{SAFE_ID}/{SAFE_ID}\.json", "arrivals.path")
            if path.split("/")[1] != f"{event_id}.json":
                raise ValueError(f"arrivals file must be named {event_id}.json: {path}")
            _text(ref["sha256"], SHA256, "arrivals.sha256")
            _count(ref["bytes"], "arrivals.bytes", MAX_ARRIVALS_BYTES)
    event_ids = [event_id for _, event_id in order]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("event IDs must be unique")
    if len(set(bundle_ids)) != len(bundle_ids):
        raise ValueError("each bundle ID must be used by one event only")
    if order != sorted(order):
        raise ValueError("events must sort by origin instant, then event_id")
    if index["default_event_id"] not in event_ids:
        raise ValueError("default_event_id must name a listed event")


def _pin(root: Path, bundle_id: object) -> tuple[dict[str, Any], dict[str, Any]]:
    """Check every manifest asset's bytes and SHA-256; return the BundleRef and manifest."""
    bundle_id = _text(bundle_id, SAFE_ID, "bundle name")
    directory = _path(root, bundle_id)
    data = _path(directory, "manifest.json").read_bytes()
    manifest: dict[str, Any] = json.loads(data)
    if manifest.get("bundle_id") != bundle_id:
        raise ValueError(f"manifest bundle_id differs from its directory: {bundle_id}")
    for asset in manifest["assets"]:
        path = _path(directory, asset["path"])
        if path.stat().st_size != asset["bytes"] or _hash(path) != asset["sha256"]:
            raise ValueError(f"asset differs from its manifest: {bundle_id}/{asset['path']}")
    ref = {
        "bundle_id": bundle_id,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "manifest_bytes": len(data),
    }
    return ref, manifest


def build_events_index(*, bundles_root: Path, config_path: Path, replace: bool = False) -> Path:
    """Verify the listed bundles and publish `<bundles_root>/events.json` by one rename.

    An identical index is left alone; a different one is replaced only with
    `replace`; a symlinked index is always refused. Raises ValueError for unsafe,
    changed or invalid input and FileExistsError for a different existing index.
    Work is linear in the listed bundles' bytes.
    """
    root = bundles_root.resolve()
    if not root.is_dir():
        raise ValueError("bundles root must be an existing directory")
    settings = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if set(settings) != {"default_event_id", "events"}:
        raise ValueError("config must give exactly default_event_id and events")
    events: list[dict[str, Any]] = []
    for entry in settings["events"]:
        if "arrivals" in entry:
            raise ValueError("arrivals not supported until T-SV-01B")
        if not set(FIELDS) <= set(entry) <= set(FIELDS) | BUNDLE_OPTIONS:
            raise ValueError(f"config event needs {FIELDS} and only {sorted(BUNDLE_OPTIONS)}")
        event: dict[str, Any] = {key: entry[key] for key in FIELDS}
        event |= {"records": None, "layers": None, "arrivals": None}
        if "records_bundle" in entry:
            event["records"], manifest = _pin(root, entry["records_bundle"])
            if manifest.get("event") != {key: entry[key] for key in IDENTITY}:
                raise ValueError(f"records manifest event differs from config: {entry['event_id']}")
        if "layers_bundle" in entry:
            event["layers"], manifest = _pin(root, entry["layers_bundle"])
            if manifest.get("origin_time_utc") != entry["origin_time_utc"]:
                raise ValueError(f"layers manifest origin differs from config: {entry['event_id']}")
        events.append(event)
    index = {
        "schema_version": "1",
        "evidence_state": "internal_descriptive_only",
        "default_event_id": settings["default_event_id"],
        "events": events,
    }
    validate_events_index(index)
    target = root / "events.json"
    # ponytail: the staged file sits in a hidden sibling directory (same filesystem), as in
    # map_layers; the rename replaces events.json atomically and the directory is removed.
    with tempfile.TemporaryDirectory(prefix=".events-", dir=root) as temporary:
        staged = Path(temporary) / "events.json"
        _write_json(staged, index)
        if target.is_symlink():
            raise ValueError(f"existing events index is a symbolic link: {target}")
        if target.exists():
            if target.read_bytes() == staged.read_bytes():
                return target
            if not replace:
                raise FileExistsError(f"a different events index exists (use replace): {target}")
        staged.replace(target)
    return target
