"""Story reported-times files (`<arrivals_bundle_id>/<event_id>.json`, schema 1).

Published NTWC estimates and source-reported times (NTWC observed times, NCEI travel
durations) with plain differences. They are not validated physical arrivals, errors,
warning times or model outputs. NTWC and NCEI rows are never merged or differenced.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pyproj import Geod, Transformer

from analysis.story.atlas import DISPLAY_CRS, shift_longitude
from analysis.story.demo_export import (
    _hash,  # pyright: ignore[reportPrivateUsage]
    _path,  # pyright: ignore[reportPrivateUsage]
    _utc,  # pyright: ignore[reportPrivateUsage]
    _write_json,  # pyright: ignore[reportPrivateUsage]
)
from analysis.story.events_index import (
    IDENTITY,
    MAX_ARRIVALS_BYTES,
    NONEMPTY,
    SAFE_ID,
    SHA256,
    UTC_TIME,
    _object,  # pyright: ignore[reportPrivateUsage]
    _text,  # pyright: ignore[reportPrivateUsage]
)

EXACT = "exact_reported_timestamp"
NTWC_ARRIVAL = "NTWC_reported_observed_arrival"
NCEI_ARRIVAL = "source_reported_initial_wave"
EVIDENCE = "data/processed/arrival-evidence/foundation-v1"
RELEASE_MANIFEST = "artifacts/releases/story-reported-times-v1.json"
TABLES = (
    "source_records",
    "observations",
    "forecast_instances",
    "pair_members",
    "sites",
    "site_links",
)
INPUTS = {
    f"{EVIDENCE}/manifest.json",
    *(f"{EVIDENCE}/{name}.csv.gz" for name in TABLES),
    RELEASE_MANIFEST,
}
RECORDS_MANIFEST = r"([a-zA-Z0-9_-][a-zA-Z0-9_.-]*/)*[a-zA-Z0-9_-]+/manifest\.json"
SPEED_KM_PER_H = 713
RELEASE: dict[str, Any] = {
    "allowed_uses": [
        "display_source_reported_times",
        "display_published_estimates",
        "display_plain_differences",
    ],
    "arrival_comparison_allowed": False,
    "estimate_difference_display_allowed": True,
    "physical_arrival_records_released": 0,
    "prohibited_uses": [
        "physical_arrival_validation",
        "modeled_minus_observed_residual",
        "model_output_display",
        "actionable_warning_time",
        "operational_warning",
        "public_release_before_release_gate",
        "selection_or_reserved_event_display",
        "fitted_or_predicted_value_display",
        "paper_figure_or_model_code_use",
        "cross_source_difference",
    ],
    "release_id": "story-reported-times-v1",
    "reported_arrival_display_allowed": True,
}
LITERALS: dict[str, Any] = {
    "schema_version": "1",
    "exporter_version": "1",
    "evidence_state": "internal_descriptive_only",
    "display_crs": DISPLAY_CRS,
    "coordinate_order": "x,y",
    "release": RELEASE,
    "ruler": {
        "speed_km_per_h": SPEED_KM_PER_H,
        "statement": "Constant long-wave speed over a 4 km deep ocean. A ruler, not a prediction.",
    },
}
TOP_KEYS = {
    *LITERALS,
    "event_id",
    "origin_time_utc",
    "places",
    "reports",
    "accounting",
    "input_fingerprints",
    "config_sha256",
}
PLACE_KEYS = {
    "site_id",
    "label",
    "position_status",
    "latitude",
    "longitude",
    "x",
    "y",
    "distance_km",
    "ruler_minutes",
    "record",
}
REPORT_KEYS = {
    "report_id",
    "source",
    "site_id",
    "place_text",
    "gauge_kind",
    "reported_minutes",
    "reported_origin",
    "reported_utc",
    "reported_text",
    "origin_offset_seconds",
    "estimate_minutes",
    "estimate_utc",
    "estimate_text",
    "reported_minus_estimate_minutes",
    "reported_minus_ruler_minutes",
    "source_flags",
    "source_id",
    "source_sha256",
}
ACCOUNTING_KEYS = {
    "ntwc_table_rows",
    "ntwc_rows_with_reported_time",
    "ntwc_rows_with_estimate",
    "ntwc_rows_with_both_times",
    "ntwc_pairs_with_position",
    "ntwc_reported_with_position",
    "ncei_records",
    "ncei_reported_durations",
    "ncei_durations_with_position",
    "reports",
    "places",
}
NCEI_ONLY_NULL = (
    "reported_utc",
    "reported_text",
    "estimate_minutes",
    "estimate_utc",
    "estimate_text",
    "reported_minus_estimate_minutes",
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _same(stored: object, expected: object) -> bool:
    """Equal JSON value and type, so 0 is not false and 41 is not 41.0."""
    return type(stored) is type(expected) and stored == expected


def _array(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{what} must be an array")
    return cast(list[object], value)


def _float(value: object, what: str, limit: float = math.inf) -> float:
    if not isinstance(value, float) or not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f"{what} must be a finite float within ±{limit}: {value!r}")
    return value


def _integer(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} must be a JSON integer: {value!r}")
    return value


def _raw(value: object, what: str) -> None:
    if not isinstance(value, str) or not value or value != " ".join(value.split()):
        raise ValueError(f"{what} must be nonempty text with whitespace collapsed: {value!r}")


def _round(value: float, digits: int) -> float:
    """Built-in round; + 0.0 turns -0.0 into 0.0 so no zero reads as negative."""
    return round(value, digits) + 0.0


def _before_origin(minutes: float | None) -> bool:
    """Listed but not drawn: a time before the origin never gets a difference."""
    return minutes is not None and minutes < 0


def _minutes(at: str, origin: datetime) -> float:
    return _round((_utc(at) - origin).total_seconds() / 60, 3)


def _fingerprints(value: object) -> bool:
    """Check the input allowlist; return whether a records manifest is among the inputs."""
    paths: list[str] = []
    for item in _array(value, "input_fingerprints"):
        fingerprint = _object(item, {"path", "sha256"}, "input fingerprint")
        paths.append(_text(fingerprint["path"], NONEMPTY, "input path"))
        _text(fingerprint["sha256"], SHA256, "input sha256")
    if paths != sorted(set(paths)):
        raise ValueError("input_fingerprints must be unique and sorted by path")
    extra = [path for path in paths if path not in INPUTS]
    if not INPUTS <= set(paths) or len(extra) > 1:
        raise ValueError(
            "input_fingerprints must list the released inputs and one records manifest"
        )
    for path in extra:
        if not re.fullmatch(RECORDS_MANIFEST, path) or "models" in path.split("/"):
            raise ValueError(f"input is not on the allowlist: {path}")
    return bool(extra)


def _place(value: object, has_records: bool) -> dict[str, Any]:
    place = _object(value, PLACE_KEYS, "place")
    _text(place["site_id"], NONEMPTY, "place.site_id")
    _text(place["label"], NONEMPTY, "place.label")
    if place["position_status"] not in ("reviewed", "source_position"):
        raise ValueError(f"unknown position_status: {place['position_status']!r}")
    _float(place["latitude"], "place.latitude", 90)
    _float(place["longitude"], "place.longitude", 180)
    _integer(place["x"], "place.x")
    _integer(place["y"], "place.y")
    distance = _float(place["distance_km"], "place.distance_km")
    if distance < 0 or round(distance, 1) != distance:
        raise ValueError(f"distance_km must be ≥ 0 and rounded to 0.1: {distance!r}")
    if not _same(place["ruler_minutes"], round(distance / SPEED_KM_PER_H * 60, 1)):
        raise ValueError(f"ruler_minutes must be round(distance_km / 713 × 60, 1): {place!r}")
    if place["record"] is not None:
        record = _object(place["record"], {"station_id", "link"}, "place.record")
        _text(record["station_id"], NONEMPTY, "record.station_id")
        if record["link"] not in ("same_provider_id", "within_1km"):
            raise ValueError(f"unknown record link: {record['link']!r}")
        if record["link"] == "same_provider_id" and not place["site_id"].endswith(
            f":{record['station_id']}"
        ):
            raise ValueError(f"a provider-ID link names the site's own ID: {place['site_id']}")
        if not has_records:
            raise ValueError("a record link needs the records manifest among the inputs")
    return place


def _ntwc(report: dict[str, Any], origin: datetime) -> None:
    if report["gauge_kind"] != "unknown" or report["origin_offset_seconds"] is not None:
        raise ValueError("an NTWC report has gauge_kind unknown and no origin offset")
    if report["source_flags"] != []:
        raise ValueError("an NTWC report has no source flags")
    if report["reported_origin"] not in (None, "usgs_reviewed"):
        raise ValueError("an NTWC reported time counts from the reviewed USGS origin")
    for side in ("reported", "estimate"):
        at = report[f"{side}_utc"]
        expected = None if at is None else _minutes(_text(at, UTC_TIME, f"{side}_utc"), origin)
        if not _same(report[f"{side}_minutes"], expected):
            raise ValueError(f"{side}_minutes must be ({side}_utc − origin) in minutes: {report!r}")
        if report[f"{side}_text"] is not None:
            _raw(report[f"{side}_text"], f"{side}_text")
    if report["reported_minutes"] is None and report["estimate_minutes"] is None:
        raise ValueError(f"an NTWC report needs an exact reported time or estimate: {report!r}")
    difference = report["reported_minus_estimate_minutes"]
    if difference is not None:
        if report["reported_utc"] is None or report["estimate_utc"] is None:
            raise ValueError("a reported-minus-estimate difference needs both exact times")
        if _before_origin(report["reported_minutes"]) or _before_origin(report["estimate_minutes"]):
            raise ValueError(f"no difference is written for a time before the origin: {report!r}")
        seconds = (_utc(report["reported_utc"]) - _utc(report["estimate_utc"])).total_seconds()
        if not _same(difference, _round(seconds / 60, 3)):
            raise ValueError(f"difference must be reported minus estimate of its row: {report!r}")


def _ncei(report: dict[str, Any]) -> None:
    if report["gauge_kind"] not in ("tide_gauge", "deep_ocean_gauge"):
        raise ValueError(f"unknown NCEI gauge_kind: {report['gauge_kind']!r}")
    if report["source_flags"] not in ([], ["doubtful"]):
        raise ValueError(f"unknown NCEI source flags: {report['source_flags']!r}")
    if report["reported_origin"] != "ncei_native":
        raise ValueError("an NCEI duration counts from the NCEI origin")
    if report["reported_minutes"] is None or report["reported_minutes"] <= 0:
        raise ValueError("an NCEI report needs a positive reported duration")
    if report["origin_offset_seconds"] is not None:
        _float(report["origin_offset_seconds"], "origin_offset_seconds")
    for key in NCEI_ONLY_NULL:
        if report[key] is not None:
            raise ValueError(f"an NCEI report has null {key}")


def _report(value: object, origin: datetime, places: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report = _object(value, REPORT_KEYS, "report")
    _text(report["report_id"], NONEMPTY, "report_id")
    _raw(report["place_text"], "place_text")
    _text(report["source_id"], NONEMPTY, "source_id")
    _text(report["source_sha256"], SHA256, "source_sha256")
    site_id, minutes = report["site_id"], report["reported_minutes"]
    if site_id is not None and site_id not in places:
        raise ValueError(f"report names no listed place: {site_id!r}")
    if minutes is not None:
        _float(minutes, "reported_minutes")
    if (report["reported_origin"] is None) != (minutes is None):
        raise ValueError("reported_origin is null exactly when reported_minutes is null")
    ruler = None
    if minutes is not None and site_id is not None and not _before_origin(minutes):
        ruler = _round(minutes - places[site_id]["ruler_minutes"], 1)
    if not _same(report["reported_minus_ruler_minutes"], ruler):
        raise ValueError(f"reported_minus_ruler_minutes must be {ruler!r}: {report!r}")
    if report["source"] == "ntwc":
        _ntwc(report, origin)
    elif report["source"] == "ncei":
        _ncei(report)
    else:
        raise ValueError(f"unknown source: {report['source']!r}")
    return report


def _accounting(value: object, reports: list[dict[str, Any]], place_count: int) -> None:
    accounting = _object(value, ACCOUNTING_KEYS, "accounting")
    if any(_integer(accounting[key], f"accounting.{key}") < 0 for key in ACCOUNTING_KEYS):
        raise ValueError("accounting counts are nonnegative")
    ntwc = [r for r in reports if r["source"] == "ntwc"]
    ncei = [r for r in reports if r["source"] == "ncei"]
    differences = [r for r in ntwc if r["reported_minus_estimate_minutes"] is not None]
    # A pair-table row with a time before the origin still counts but has no difference.
    withheld = [
        r
        for r in ntwc
        if r["reported_minus_estimate_minutes"] is None
        and r["reported_minutes"] is not None
        and r["estimate_minutes"] is not None
        and (_before_origin(r["reported_minutes"]) or _before_origin(r["estimate_minutes"]))
    ]
    placed = [r for r in differences if r["site_id"] is not None]
    bounds = {
        "ntwc_rows_with_both_times": (len(differences), len(differences) + len(withheld)),
        "ntwc_pairs_with_position": (
            len(placed),
            len(placed) + sum(r["site_id"] is not None for r in withheld),
        ),
    }
    for key, (low, high) in bounds.items():
        if not low <= accounting[key] <= high:
            raise ValueError(f"accounting.{key} must be in [{low}, {high}]: {accounting[key]}")
    reported = [r for r in ntwc if r["reported_minutes"] is not None]
    derived = {
        "ntwc_rows_with_reported_time": len(reported),
        "ntwc_rows_with_estimate": sum(r["estimate_minutes"] is not None for r in ntwc),
        "ntwc_reported_with_position": sum(r["site_id"] is not None for r in reported),
        "ncei_reported_durations": len(ncei),
        "ncei_durations_with_position": sum(r["site_id"] is not None for r in ncei),
        "reports": len(reports),
        "places": place_count,
    }
    for key, count in derived.items():
        if accounting[key] != count:
            raise ValueError(f"accounting.{key} must equal {count}, not {accounting[key]}")
    if accounting["ntwc_table_rows"] < len(ntwc) or accounting["ncei_records"] < len(ncei):
        raise ValueError("accounting table rows must cover the listed reports")


def validate_arrivals(value: object) -> None:
    """Apply every value-only rule of the reported-times contract; touch no file.

    Raises ValueError naming the first broken rule. O(n log n) in places and reports.
    """
    doc = _object(value, TOP_KEYS, "arrivals file")
    for key, expected in LITERALS.items():
        if _canonical(doc[key]) != _canonical(expected):
            raise ValueError(f"{key} must be exactly {expected!r}")
    _text(doc["event_id"], SAFE_ID, "event_id")
    origin = _utc(_text(doc["origin_time_utc"], UTC_TIME, "origin_time_utc"))
    _text(doc["config_sha256"], SHA256, "config_sha256")
    has_records = _fingerprints(doc["input_fingerprints"])
    items = [_place(item, has_records) for item in _array(doc["places"], "places")]
    site_ids = [place["site_id"] for place in items]
    if site_ids != sorted(set(site_ids)):
        raise ValueError("places must be unique and sorted by site_id")
    places = {place["site_id"]: place for place in items}
    reports = [_report(item, origin, places) for item in _array(doc["reports"], "reports")]
    report_ids = [r["report_id"] for r in reports]
    if len(set(report_ids)) != len(report_ids):
        raise ValueError("report IDs must be unique")
    sources = [r["source"] for r in reports]
    if sources != sorted(sources, key=("ntwc", "ncei").index):
        raise ValueError("NTWC reports come before NCEI reports")
    labels: dict[str, str] = {}
    for report in reports:
        if report["site_id"] is not None:
            labels.setdefault(report["site_id"], report["place_text"])
    ntwc_sites = {r["site_id"] for r in reports if r["source"] == "ntwc"}
    for site_id, place in places.items():
        if site_id not in labels:
            raise ValueError(f"place is used by no report: {site_id}")
        if place["label"] != labels[site_id]:
            raise ValueError(f"label must be the place_text of the first report: {site_id}")
        if place["position_status"] != ("reviewed" if site_id in ntwc_sites else "source_position"):
            raise ValueError(f"position_status must be reviewed exactly for NTWC places: {site_id}")
    _accounting(doc["accounting"], reports, len(site_ids))


def _rows(path: Path) -> list[dict[str, str]]:
    # The largest released cell is about 16 KB, inside csv's default 128 KiB field limit.
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _by_record(rows: list[dict[str, str]], name: str) -> dict[str, dict[str, str]]:
    index = {row["source_record_id"]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError(f"duplicate source_record_id in {name}")
    return index


def _clean(text: str) -> str | None:
    """Source cell text with whitespace trimmed and collapsed; an empty cell is null."""
    return " ".join(text.split()) or None


def _base(
    record: dict[str, str], link: dict[str, str], resolved: str, place: str
) -> dict[str, Any]:
    return {
        "report_id": record["source_record_id"],
        "site_id": link["physical_site_id"] if link["decision"] == resolved else None,
        "place_text": _clean(place),
        "source_id": record["source_id"],
        "source_sha256": record["source_sha256"],
    }


def _reports(
    records: list[dict[str, str]], index: dict[str, dict[str, dict[str, str]]], origin: datetime
) -> list[dict[str, Any]]:
    """NTWC rows with an exact time or estimate, then NCEI positive durations, in table order."""
    observations, links = index["observations"], index["site_links"]
    reports: list[dict[str, Any]] = []
    for record in records:
        if record["source_family"] != "NTWC":
            continue
        rid = record["source_record_id"]
        observation, forecast = observations[rid], index["forecast_instances"][rid]
        if observation["arrival_definition"] != NTWC_ARRIVAL:
            raise ValueError(f"NTWC record without an NTWC observation: {rid}")
        reported = observation["observed_utc"] if observation["duration_state"] == EXACT else None
        estimate = forecast["estimated_utc"] if forecast["estimate_state"] == EXACT else None
        if reported is None and estimate is None:
            continue
        pair = index["pair_members"].get(rid)
        times = (reported, estimate)
        if pair is not None and (pair["observed_utc"], pair["estimated_utc"]) != times:
            raise ValueError(f"pair times differ from the exact reported time and estimate: {rid}")
        native = json.loads(record["native_record_json"])
        reported_minutes = None if reported is None else _minutes(reported, origin)
        estimate_minutes = None if estimate is None else _minutes(estimate, origin)
        difference = None
        if pair is not None and not (
            _before_origin(reported_minutes) or _before_origin(estimate_minutes)
        ):
            # The pair table stores estimated minus observed; the sign flips here only.
            difference = _round(-float(pair["estimated_minus_observed_seconds"]) / 60, 3)
        reports.append(
            _base(record, links[rid], "accepted", native["source_label"])
            | {
                "source": "ntwc",
                "gauge_kind": "unknown",
                "reported_minutes": reported_minutes,
                "reported_origin": None if reported is None else "usgs_reviewed",
                "reported_utc": reported,
                "reported_text": _clean(native["observed_raw"]),
                "origin_offset_seconds": None,
                "estimate_minutes": estimate_minutes,
                "estimate_utc": estimate,
                "estimate_text": _clean(forecast["native_estimate_text"]),
                "reported_minus_estimate_minutes": difference,
                "source_flags": [],
            }
        )
    for record in records:
        if record["source_family"] != "NCEI":
            continue
        rid = record["source_record_id"]
        observation = observations[rid]
        if observation["arrival_definition"] != NCEI_ARRIVAL:
            raise ValueError(f"NCEI record without an NCEI observation: {rid}")
        if observation["duration_state"] != "complete_positive":
            continue
        native = json.loads(record["native_record_json"])
        if native["native_doubtful"] not in ("y", "n"):
            raise ValueError(f"unknown NCEI doubtful value: {rid}")
        offset = observation["origin_difference_seconds"]
        reports.append(
            _base(record, links[rid], "source_native_position", native["native_locationName"])
            | {
                "source": "ncei",
                "gauge_kind": observation["measurement_family"],
                "reported_minutes": round(float(observation["duration_minutes"]), 3),
                "reported_origin": "ncei_native",
                "reported_utc": None,  # no arrival date is inferred
                "reported_text": None,
                "origin_offset_seconds": None if offset == "unknown" else float(offset),
                "estimate_minutes": None,
                "estimate_utc": None,
                "estimate_text": None,
                "reported_minus_estimate_minutes": None,  # never differenced against NTWC
                "source_flags": ["doubtful"] if native["native_doubtful"] == "y" else [],
            }
        )
    return reports


def _record(
    site_id: str, latitude: float, longitude: float, stations: list[dict[str, Any]], geod: Geod
) -> dict[str, str] | None:
    """Provider-ID match first, else the nearest records station within 1 km, then lowest ID."""
    for station in stations:
        key = station.get("display_station_key")  # records schema 2 names its provider key
        if key is None and station["source_id"].startswith("coops-"):
            key = f"coops:{station['station_id']}"
        if site_id == key:
            return {"station_id": station["station_id"], "link": "same_provider_id"}
    near = sorted(
        (geod.inv(longitude, latitude, s["longitude"], s["latitude"])[2], s["station_id"])
        for s in stations
    )
    near = [item for item in near if item[0] <= 1000]
    return {"station_id": near[0][1], "link": "within_1km"} if near else None


def _places(
    entry: dict[str, Any],
    reports: list[dict[str, Any]],
    sites: dict[str, dict[str, str]],
    stations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    geod = Geod(ellps="WGS84")
    transformer = Transformer.from_crs("EPSG:4326", DISPLAY_CRS, always_xy=True, force_over=True)
    labels: dict[str, str] = {}
    for report in reports:
        if report["site_id"] is not None:
            labels.setdefault(report["site_id"], report["place_text"])
    reviewed = {r["site_id"] for r in reports if r["source"] == "ntwc"}
    places: list[dict[str, Any]] = []
    for site_id in sorted(labels):
        latitude = float(sites[site_id]["latitude"])
        longitude = float(sites[site_id]["longitude"])
        metres = geod.inv(entry["longitude"], entry["latitude"], longitude, latitude)[2]
        distance = round(metres / 1000, 1)
        x, y = transformer.transform(shift_longitude(longitude), latitude)
        places.append(
            {
                "site_id": site_id,
                "label": labels[site_id],
                "position_status": "reviewed" if site_id in reviewed else "source_position",
                "latitude": latitude,
                "longitude": longitude,
                "x": round(x),
                "y": round(y),
                "distance_km": distance,
                "ruler_minutes": round(distance / SPEED_KM_PER_H * 60, 1),
                "record": _record(site_id, latitude, longitude, stations, geod),
            }
        )
    ruler = {place["site_id"]: place["ruler_minutes"] for place in places}
    for report in reports:
        minutes, site_id = report["reported_minutes"], report["site_id"]
        drawn = minutes is not None and site_id is not None and not _before_origin(minutes)
        report["reported_minus_ruler_minutes"] = (
            _round(minutes - ruler[site_id], 1) if drawn else None
        )
    return places


def _table_accounting(
    event_id: str, tables: dict[str, list[dict[str, str]]], links: dict[str, dict[str, str]]
) -> dict[str, int]:
    """Counts taken from the released tables; the validator reconciles them with the lists."""

    def rows(name: str) -> list[dict[str, str]]:
        return [row for row in tables[name] if row["event_id"] == event_id]

    def placed(selected: list[dict[str, str]], decision: str) -> int:
        return sum(links[row["source_record_id"]]["decision"] == decision for row in selected)

    observations = rows("observations")
    reported = [
        row
        for row in observations
        if row["arrival_definition"] == NTWC_ARRIVAL and row["duration_state"] == EXACT
    ]
    durations = [
        row
        for row in observations
        if row["arrival_definition"] == NCEI_ARRIVAL
        and row["duration_state"] == "complete_positive"
    ]
    pairs = rows("pair_members")
    families = [row["source_family"] for row in rows("source_records")]
    return {
        "ntwc_table_rows": families.count("NTWC"),
        "ntwc_rows_with_reported_time": len(reported),
        "ntwc_rows_with_estimate": sum(
            row["estimate_state"] == EXACT for row in rows("forecast_instances")
        ),
        "ntwc_rows_with_both_times": len(pairs),
        "ntwc_pairs_with_position": placed(pairs, "accepted"),
        "ntwc_reported_with_position": placed(reported, "accepted"),
        "ncei_records": families.count("NCEI"),
        "ncei_reported_durations": len(durations),
        "ncei_durations_with_position": placed(durations, "source_native_position"),
    }


def export_arrivals(*, source_root: Path, output_root: Path, config_path: Path) -> Path:
    """Verify the released inputs and publish one new arrivals bundle by a single rename.

    Writes `output_root/<arrivals_bundle_id>/<event_id>.json` for every configured event and
    never overwrites a bundle. Raises ValueError for unsafe, changed or unreconciled input
    and FileExistsError for an existing bundle. Linear in the released table rows.
    """
    if not source_root.is_absolute() or not source_root.is_dir():
        raise ValueError("explicit absolute source root is required")
    source_root = source_root.resolve()
    config_bytes = config_path.read_bytes()
    settings = tomllib.loads(config_bytes.decode("utf-8"))
    if set(settings) != {"arrivals_bundle_id", "release_manifest", "bundles_root", "events"}:
        raise ValueError(
            "config must give arrivals_bundle_id, release_manifest, bundles_root, events"
        )
    bundle_id = _text(settings["arrivals_bundle_id"], SAFE_ID, "arrivals_bundle_id")
    output_root = output_root.resolve()
    destination = output_root / bundle_id
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)

    package_path = f"{EVIDENCE}/manifest.json"
    package_bytes = _path(source_root, package_path).read_bytes()
    checked = {package_path: hashlib.sha256(package_bytes).hexdigest()}
    listed = {item["path"]: item["sha256"] for item in json.loads(package_bytes)["files"]}
    for name in TABLES:
        checked[f"{EVIDENCE}/{name}.csv.gz"] = listed[f"{name}.csv.gz"]
    release_bytes = _path(source_root, settings["release_manifest"]).read_bytes()
    manifest = json.loads(release_bytes)
    release = {key: manifest.get(key) for key in RELEASE}
    if _canonical(release) != _canonical(RELEASE):
        raise ValueError("release manifest fields differ from the contract literal")
    if manifest.get("source_package") != {"path": package_path, "sha256": checked[package_path]}:
        raise ValueError("release manifest names another arrival-evidence package")
    checked[settings["release_manifest"]] = hashlib.sha256(release_bytes).hexdigest()
    _verify(source_root, checked)
    shared = dict(checked)  # the validator holds these paths to the contract allowlist
    tables = {name: _rows(_path(source_root, f"{EVIDENCE}/{name}.csv.gz")) for name in TABLES}
    index = {
        name: _by_record(tables[name], name)
        for name in ("observations", "forecast_instances", "pair_members", "site_links")
    }
    sites = {row["physical_site_id"]: row for row in tables["sites"]}

    files: dict[str, dict[str, Any]] = {}
    for entry in settings["events"]:
        if not set(IDENTITY) <= set(entry) <= {*IDENTITY, "records_bundle"}:
            raise ValueError(f"config event needs {IDENTITY} and only records_bundle")
        event_id = _text(entry["event_id"], SAFE_ID, "event_id")
        records = [row for row in tables["source_records"] if row["event_id"] == event_id]
        if not records or event_id in files:
            raise ValueError(f"event absent from released source_records or repeated: {event_id}")
        inputs = dict(shared)
        stations: list[dict[str, Any]] = []
        if "records_bundle" in entry:
            name = _text(entry["records_bundle"], SAFE_ID, "records_bundle")
            relative = f"{settings['bundles_root']}/{name}/manifest.json"
            data = _path(source_root, relative).read_bytes()
            records_manifest = json.loads(data)
            if records_manifest["event"] != {key: entry[key] for key in IDENTITY}:
                raise ValueError(f"records manifest event differs from config: {event_id}")
            stations = records_manifest["stations"]
            inputs[relative] = checked[relative] = hashlib.sha256(data).hexdigest()
        reports = _reports(records, index, _utc(entry["origin_time_utc"]))
        places = _places(entry, reports, sites, stations)
        accounting = _table_accounting(event_id, tables, index["site_links"])
        files[event_id] = {
            **LITERALS,
            "release": release,
            "event_id": event_id,
            "origin_time_utc": entry["origin_time_utc"],
            "places": places,
            "reports": reports,
            "accounting": accounting | {"reports": len(reports), "places": len(places)},
            "input_fingerprints": [
                {"path": path, "sha256": sha256} for path, sha256 in sorted(inputs.items())
            ],
            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        }
        validate_arrivals(files[event_id])

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{bundle_id}-", dir=output_root) as temporary:
        staging = Path(temporary)
        for event_id, value in files.items():
            path = staging / f"{event_id}.json"
            _write_json(path, value)
            if path.stat().st_size > MAX_ARRIVALS_BYTES:
                raise ValueError(f"arrivals file exceeds {MAX_ARRIVALS_BYTES} bytes: {path.name}")
        # Recheck immutable inputs before publication; no partial bundle becomes visible.
        _verify(source_root, checked)
        if _hash(config_path) != hashlib.sha256(config_bytes).hexdigest():
            raise ValueError("config checksum changed during export")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        staging.rename(destination)
    return destination


def _verify(root: Path, checked: dict[str, str]) -> None:
    for relative, sha256 in checked.items():
        if _hash(_path(root, relative)) != sha256:
            raise ValueError(f"checksum mismatch: {relative}")
