"""Exploration-only native NCEI component census; no date or target repair."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from analysis.arrival.evidence import checked_path, sha256

COMPONENTS = (
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "arrDay",
    "arrHour",
    "arrMin",
    "travHours",
    "travMins",
)


def assess_components(native: dict[str, Any], threshold: float) -> dict[str, Any]:
    """TOD-only circular discrepancy; arrDay is range-checked, never calendar-resolved."""
    result: dict[str, Any] = {
        "assessment": "unassessed",
        "reason": "",
        "clock_modulo_residual_minutes": None,
        "absolute_residual_minutes": None,
        "large_component_disagreement": None,
    }
    invalid = [
        k
        for k in COMPONENTS
        if isinstance(native.get(k), bool)
        or not isinstance(native.get(k), (float, int))
        or not math.isfinite(native[k])
    ]
    if invalid:
        return {**result, "reason": "missing_or_nonfinite_components:" + ",".join(invalid)}
    try:
        for key in (
            "year",
            "month",
            "day",
            "hour",
            "minute",
            "arrDay",
            "arrHour",
            "arrMin",
            "travHours",
            "travMins",
        ):
            if int(native[key]) != native[key]:
                raise ValueError("noninteger_component")
        datetime(
            int(native["year"]),
            int(native["month"]),
            int(native["day"]),
            int(native["hour"]),
            int(native["minute"]),
        )
        if not (
            0 <= native["second"] < 60
            and 1 <= native["arrDay"] <= 31
            and 0 <= native["arrHour"] < 24
            and 0 <= native["arrMin"] < 60
            and native["travHours"] >= 0
            and 0 <= native["travMins"] < 60
        ):
            raise ValueError("component_range")
    except (ValueError, OverflowError):
        return {**result, "reason": "invalid_component_range_or_Gregorian_date"}
    source_tod = native["hour"] * 60 + native["minute"] + native["second"] / 60
    arrival_tod = native["arrHour"] * 60 + native["arrMin"]
    duration = native["travHours"] * 60 + native["travMins"]
    residual = (arrival_tod - source_tod - duration + 720) % 1440 - 720
    return {
        **result,
        "assessment": "assessed",
        "reason": "complete_native_components",
        "clock_modulo_residual_minutes": residual,
        "absolute_residual_minutes": abs(residual),
        "large_component_disagreement": abs(residual) > threshold,
    }


def prepare_sources(
    root: Path, rows: list[dict[str, Any]], manifest: list[dict[str, str]], exploration: set[str]
) -> dict[str, dict[str, Any]]:
    """Validate ALL selected metadata and bytes before any raw JSON is parsed."""
    by_id = {r["source_id"]: r for r in manifest}
    if len(by_id) != len(manifest):
        raise ValueError("duplicate source identity")
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity, position = row["record_id"].rsplit(":", 1)
        if row["event_id"] not in exploration:
            raise ValueError("only exploration source outcomes may be parsed")
        if not identity.startswith("recovery-ncei-") or not position.isdigit() or int(position) < 1:
            raise ValueError("unsupported frozen source position")
        source = by_id[identity]
        station = json.loads(source["notes"])["station_metadata"]
        if isinstance(station, str):
            station = json.loads(station.replace(r"\"", '"'))
        event = station.get("development_event_id", station.get("event_id"))
        number = station["ncei_event_id"]
        if (
            event != row["event_id"]
            or event not in exploration
            or station.get("event_id", event) != event
        ):
            raise ValueError("source metadata disagrees with exploration event")
        page = station.get("page", 1)
        pagination_pins = {}
        pagination = station.get("pagination_evidence")
        if pagination:
            page = pagination["page_requested"]
            total_pages = pagination["total_pages"]
            parent = by_id[pagination["page1_source_id"]]
            parent_station = json.loads(parent["notes"])["station_metadata"]
            if isinstance(parent_station, str):
                parent_station = json.loads(parent_station.replace(r"\"", '"'))
            if (
                parent_station.get("development_event_id", parent_station.get("event_id")) != event
                or parent_station.get("ncei_event_id") != number
            ):
                raise ValueError("pagination parent belongs to a different source event")
            proof = checked_path(root, pagination["qa_receipt"])
            if (
                isinstance(page, bool)
                or not isinstance(page, int)
                or isinstance(total_pages, bool)
                or not isinstance(total_pages, int)
                or total_pages <= 0
                or not 1 < page <= total_pages
                or parent["sha256"] != pagination["page1_sha256"]
                or sha256(checked_path(root, parent["local_path"])) != parent["sha256"]
                or sha256(proof) != pagination["qa_sha256"]
            ):
                raise ValueError("invalid explicit pagination evidence")
            pagination_pins = {
                parent["local_path"]: parent["sha256"],
                pagination["qa_receipt"]: pagination["qa_sha256"],
            }
        url = urlparse(source["url"])
        query = parse_qs(url.query)
        if (
            source["publisher"] != "NOAA NCEI"
            or url.scheme != "https"
            or url.netloc != "www.ngdc.noaa.gov"
            or url.path != "/hazel/hazard-service/api/v1/tsunamis/runups"
            or url.fragment
            or isinstance(number, bool)
            or not isinstance(number, int)
            or number <= 0
            or query.get("tsunamiEventId") != [str(number)]
            or sorted(query.get("typeMeasurementId", [])) != ["2", "3"]
            or set(query) != {"tsunamiEventId", "typeMeasurementId", "itemsPerPage", "page"}
            or query["itemsPerPage"] != ["200"]
            or query["page"] != [str(page)]
        ):
            raise ValueError("official source request/event mismatch")
        path = checked_path(root, source["local_path"])
        if (
            path.parent.name not in {"ncei-development-v1", "ncei-development-runups-v1"}
            or path.parent.parent != root / "data/raw/arrival-recovery"
            or path.name != identity + ".json"
        ):
            raise ValueError("unsupported native source path")
        try:
            native_origin = datetime.fromisoformat(
                station["ncei_origin_utc"].replace("Z", "+00:00")
            )
            offset = native_origin.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise ValueError("native origin requires explicit UTC offset")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError("invalid pinned native origin metadata") from error
        selected[identity] = {
            "path": source["local_path"],
            "sha256": source["sha256"],
            "event_id": event,
            "ncei_event_id": number,
            "native_origin": native_origin.timestamp(),
            "pagination_proof_pins": pagination_pins,
            "requested_page": page,
        }
    for source in selected.values():
        if sha256(checked_path(root, source["path"])) != source["sha256"]:
            raise ValueError("native source hash mismatch")
    return selected


def audit_records(
    root: Path,
    rows: list[dict[str, Any]],
    included: list[bool],
    manifest: list[dict[str, str]],
    exploration: set[str],
    threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    sources = prepare_sources(root, rows, manifest, exploration)
    pages = {
        key: json.loads(checked_path(root, value["path"]).read_text())
        for key, value in sources.items()
    }
    for identity, source in sources.items():
        if pages[identity].get("page") != source["requested_page"]:
            raise ValueError("native response page disagrees with checked request")
    results: list[dict[str, Any]] = []
    for row, primary in zip(rows, included, strict=True):
        identity, position = row["record_id"].rsplit(":", 1)
        source = sources[identity]
        item = pages[identity]["items"][int(position) - 1]
        if (
            not isinstance(item.get("id"), int)
            or isinstance(item["id"], bool)
            or item["id"] <= 0
            or item.get("tsunamiEventId") != source["ncei_event_id"]
            or item.get("typeMeasurementId") not in {2, 3}
            or item.get("locationName") != row["source_label"]
        ):
            raise ValueError("native source position/identity mismatch")
        if any(
            isinstance(item.get(k), bool)
            or not isinstance(item.get(k), (int, float))
            or not math.isfinite(item[k])
            for k in ("travHours", "travMins")
        ):
            raise ValueError("frozen positive duration lacks native complete components")
        duration = 60 * item["travHours"] + item["travMins"]
        if duration != float(row["target_minutes"]):
            raise ValueError("frozen native duration mismatch")
        # Validate a complete source origin independently of missing arrival fields.
        origin_fields = ("year", "month", "day", "hour", "minute", "second")
        origin = None
        if all(
            not isinstance(item.get(k), bool)
            and isinstance(item.get(k), (int, float))
            and math.isfinite(item[k])
            for k in origin_fields
        ):
            try:
                if (
                    any(int(item[k]) != item[k] for k in origin_fields[:-1])
                    or not 0 <= item["second"] < 60
                ):
                    raise ValueError("invalid source components")
                origin = (
                    datetime(
                        int(item["year"]),
                        int(item["month"]),
                        int(item["day"]),
                        int(item["hour"]),
                        int(item["minute"]),
                        tzinfo=UTC,
                    ).timestamp()
                    + item["second"]
                )
            except (ValueError, OverflowError):
                origin = None
        if origin is not None and not math.isclose(
            origin, source["native_origin"], abs_tol=1e-5, rel_tol=0
        ):
            raise ValueError("native source origin disagrees with pinned event metadata")
        assessment = assess_components(item, threshold)
        results.append(
            {
                **{
                    key: row[key]
                    for key in ("record_id", "event_id", "physical_site_id", "source_label")
                },
                "included_primary": primary,
                "native_item_id": item["id"],
                "native_tsunami_event_id": item["tsunamiEventId"],
                "reported_minutes": duration,
                **{key: item.get(key) for key in COMPONENTS},
                **assessment,
            }
        )
    pins = {value["path"]: value["sha256"] for value in sources.values()}
    for value in sources.values():
        pins.update(value["pagination_proof_pins"])
    return results, pins
