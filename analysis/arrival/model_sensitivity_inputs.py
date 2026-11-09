"""Pinned exploration-only input adapter for the prospective MS-5 design.

The caller owns scientific launch approval and supplies already checked Lanes.
Admission here checks hashes, paths and the accepted census reference closure
before any census CSV or selected raw page is parsed. The adapter never loads
other outcomes, discovers new pages, imputes publisher distances, or edits data.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from analysis.arrival.evidence import checked_path, read_rows, sha256
from analysis.arrival.model_data import (
    CONTRACT,
    CONVENTIONS,
    METADATA,
    SOURCE_MANIFEST,
    SPLIT,
    TARGET_FILES,
    Lane,
)
from analysis.arrival.model_sensitivity_design import (
    DEFINITION_RECORD_IDS,
    SensitivityInputs,
    site_key_invariance,
)
from analysis.arrival.model_source_components import prepare_sources

CENSUS_BASE = "artifacts/models/arrival-timing/native-time-component-census-v1"
CENSUS_REVIEW = CENSUS_BASE + "/review-acceptance.json"
CENSUS_INPUTS = CENSUS_BASE + "/inputs.json"
CENSUS_RECORDS = CENSUS_BASE + "/native-time-component-records.csv"
CENSUS_CONFIG = "config/arrival-source-component-audit-v1.toml"
SOURCE_LEDGER = "data/processed/arrival-evidence/foundation-v1/source_manifest.csv"
CENSUS_OUTPUTS = tuple(
    CENSUS_BASE + "/" + name
    for name in [
        "cohort-summary.csv",
        "event-summary.csv",
        "findings.md",
        "inputs.json",
        "native-time-component-records.csv",
        "output-checksums.json",
        "summary.json",
    ]
)
CONSUMED = (
    "analysis/arrival/model_sensitivity_inputs.py",
    "analysis/arrival/model_sensitivity_design.py",
    "analysis/arrival/model_source_components.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_curvature.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/evidence.py",
    "pyproject.toml",
    "uv.lock",
)
TOHOKU_EVENT = "official20110311054624120_30"
CHILE_EVENT = "official20100227063411530_30"
INFLUENTIAL_2014_EVENT = "usc000phx5"
LATA_EVENT = "usc000piqj"
LATA_RECORD = "recovery-ncei-6fa5e2d2459724b6:3"
CHECKS = {
    "all_records": 1070,
    "primary_records": 1064,
    "assessed_all": 1056,
    "assessed_primary": 1050,
    "unassessed": 14,
    "flagged": 4,
    "flagged_events": 4,
    "authorized_exploration_pages": 35,
    "input_pins": 50,
}


def required_sensitivity_paths() -> list[str]:
    """Static runtime/config requirements; the complete nested census closure is also required."""
    return sorted(
        {
            *CONSUMED,
            *CENSUS_OUTPUTS,
            CENSUS_REVIEW,
            CENSUS_CONFIG,
            CONTRACT,
            METADATA,
            SPLIT,
            SOURCE_MANIFEST,
            SOURCE_LEDGER,
            *TARGET_FILES.values(),
        }
    )


def _verify_pins(root: Path, pins: Mapping[str, str]) -> None:
    """Hash every supplied path without interpreting its scientific contents."""
    if not pins:
        raise ValueError("complete caller-provided source pins required")
    for name, digest in pins.items():
        if (
            not isinstance(name, str)
            or not name
            or Path(name).is_absolute()
            or Path(name).as_posix() != name
            or any(part in {".", ".."} for part in name.split("/"))
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("canonical relative paths and SHA256 pins required")
        path = checked_path(root, name)
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"sensitivity source hash mismatch: {name}")


def _preflight(root: Path, pins: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Inspect only verified reference/config metadata, never census/raw outcomes."""
    if not set(required_sensitivity_paths()) <= set(pins):
        raise ValueError("complete sensitivity source/config/receipt pins required")
    _verify_pins(root, pins)
    review = json.loads(checked_path(root, CENSUS_REVIEW).read_text(encoding="utf-8"))
    if (
        review.get("schema_version") != "arrival_native_components_acceptance_v1"
        or review.get("status") != "accepted_exploration_source_component_census"
        or any(review.get("checks", {}).get(key) != value for key, value in CHECKS.items())
        or set(review.get("files", {})) != set(CENSUS_OUTPUTS)
        or any(pins.get(path) != digest for path, digest in review["files"].items())
    ):
        raise ValueError("accepted complete native-component census output closure required")
    inputs = json.loads(checked_path(root, CENSUS_INPUTS).read_text(encoding="utf-8"))
    if (
        len(inputs.get("files", {})) != 50
        or inputs.get("raw_pages") != 35
        or inputs.get("confirmation_outcomes_parsed") is not False
        or inputs.get("reserved_outcomes") != "sealed"
        or any(pins.get(path) != digest for path, digest in inputs["files"].items())
    ):
        raise ValueError("complete fifty-pin census input/pagination closure required")
    raw = {path for path in inputs["files"] if path.startswith("data/raw/")}
    if len(raw) != 35 or any(
        str(Path(path).parent)
        not in {
            "data/raw/arrival-recovery/ncei-development-v1",
            "data/raw/arrival-recovery/ncei-development-runups-v1",
        }
        or not Path(path).name.startswith("recovery-ncei-")
        or not path.endswith(".json")
        for path in raw
    ):
        raise ValueError("exact thirty-five retained exploration native pages required")
    config = tomllib.loads(checked_path(root, CENSUS_CONFIG).read_text(encoding="utf-8"))
    if (
        config.get("schema_version") != "arrival_native_component_census_v1"
        or config.get("large_disagreement_minutes") != 60
        or config.get("source_manifest") != SOURCE_LEDGER
        or config.get("source_manifest_sha256") != pins.get(SOURCE_LEDGER)
        or inputs.get("design") != config
    ):
        raise ValueError("unchanged census source-ledger/rule contract required")
    contract = tomllib.loads(checked_path(root, CONTRACT).read_text(encoding="utf-8"))
    expected = {*TARGET_FILES.values(), SPLIT, METADATA, SOURCE_MANIFEST}
    if (
        any(contract.get(key) != value for key, value in CONVENTIONS.items())
        or set(contract.get("inputs", {})) != expected
        or any(pins.get(path) != digest for path, digest in contract["inputs"].items())
        or not {
            *expected,
            CONTRACT,
            CENSUS_CONFIG,
            SOURCE_LEDGER,
            "analysis/arrival/model_source_components.py",
            "analysis/arrival/model_data.py",
            "analysis/arrival/evidence.py",
            "analysis/arrival/model_validation_report.py",
            "scripts/audit_arrival_source_components.py",
        }
        <= set(inputs["files"])
    ):
        raise ValueError("complete frozen exploration model/source contract required")
    return inputs, contract


def verify_sensitivity_inputs(root: Path, pins: Mapping[str, str]) -> None:
    """Check pin/path/reference closure before the caller invokes its lane loader.

    This is source admission only, not a prospective fitting gate or fit approval.
    No census CSV, native page, or outcome table is parsed by this preflight.
    """
    _preflight(root, pins)


def _event_metadata(
    root: Path, lanes: Mapping[str, Lane]
) -> tuple[set[str], dict[str, dict[str, str]]]:
    split = tomllib.loads(checked_path(root, SPLIT).read_text(encoding="utf-8"))
    exploration, confirmation = (
        set(split.get("exploration", [])),
        set(split.get("confirmation", [])),
    )
    if (
        len(exploration) != 38
        or len(confirmation) != 19
        or len(split.get("exploration", [])) != 38
        or len(split.get("confirmation", [])) != 19
        or exploration & confirmation
        or split.get("metadata_only") is not True
    ):
        raise ValueError("frozen38exploration/19confirmation metadata split required")
    metadata = read_rows(checked_path(root, METADATA))
    by_event = {row["event_id"]: row for row in metadata}
    if len(by_event) != len(metadata) or set(by_event) != exploration | confirmation:
        raise ValueError("unique complete outcome-free event metadata required")
    if set(lanes) != set(TARGET_FILES):
        raise ValueError("three supplied source-specific lanes required")
    for target, lane in lanes.items():
        if lane.target != target or not set(lane.event_ids) <= exploration:
            raise ValueError("only provided frozen exploration lanes may be consumed")
        if len(lane.rows) != len(lane.record_ids) or len(set(lane.record_ids)) != len(lane.rows):
            raise ValueError("unique aligned lane record IDs required")
        if any(
            by_event[event]["sequence_group"] != sequence
            for event, sequence in zip(lane.event_ids, lane.sequences, strict=True)
        ):
            raise ValueError("lane sequences disagree with frozen event metadata")
    return exploration, by_event


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0 or str(result) != value:
        raise ValueError("canonical positive native item/event ID required")
    return result


def _boolean(value: str) -> bool:
    if value not in {"True", "False"}:
        raise ValueError("literal frozen Boolean cell required")
    return value == "True"


def _native_page(root: Path, path: str, digest: str) -> dict[str, Any]:
    """Parse exactly the bytes whose digest was admitted, including during drift."""
    payload = checked_path(root, path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("native source hash changed before raw parse")
    return json.loads(payload)


def load_sensitivity_inputs(
    root: Path, lanes: Mapping[str, Lane], pins: Mapping[str, str]
) -> SensitivityInputs:
    """Join the accepted census and exact native items to supplied exploration rows."""
    inputs, _ = _preflight(root, pins)
    exploration, metadata = _event_metadata(root, lanes)
    lane = lanes["NCEI-native-duration"]
    if (
        len(lane.rows) != 1070
        or lane.included.shape != (1070,)
        or lane.included.dtype != np.bool_
        or int(lane.included.sum()) != 1064
    ):
        raise ValueError("unchanged1070/1064/sixexcluded NCEI roles required")
    fields = {
        "record_id",
        "event_id",
        "physical_site_id",
        "source_label",
        "target_minutes",
        "measurement_family",
        "native_distance_km",
        "definition_conflict_candidate",
        "site_1km",
        "site_2km",
        "site_5km",
    }
    if any(not fields <= set(row) for row in lane.rows):
        raise ValueError("complete canonical NCEI source/EDA metadata required")
    manifest = read_rows(checked_path(root, SOURCE_LEDGER))
    sources = prepare_sources(root, list(lane.rows), manifest, exploration)
    raw_pins = {path for path in inputs["files"] if path.startswith("data/raw/")}
    if len(sources) != 35 or {source["path"] for source in sources.values()} != raw_pins:
        raise ValueError("exact census-selected thirty-five-page coverage required")
    for source in sources.values():
        required = {source["path"]: source["sha256"], **source["pagination_proof_pins"]}
        if any(
            pins.get(path) != digest or inputs["files"].get(path) != digest
            for path, digest in required.items()
        ):
            raise ValueError("all selected raw/pagination proof pins required before parsing")
    census_rows = read_rows(checked_path(root, CENSUS_RECORDS))
    fields = {
        "record_id",
        "event_id",
        "physical_site_id",
        "source_label",
        "included_primary",
        "native_item_id",
        "native_tsunami_event_id",
        "reported_minutes",
        "assessment",
        "large_component_disagreement",
    }
    if any(not fields <= set(row) for row in census_rows):
        raise ValueError("complete frozen census identity/assessment columns required")
    census = {row["record_id"]: row for row in census_rows}
    if len(census) != 1070 or len(census_rows) != 1070 or set(census) != set(lane.record_ids):
        raise ValueError("complete unique exact census/native-record join required")
    pages = {}
    for identity, source in sources.items():
        page = _native_page(root, source["path"], source["sha256"])
        items = page.get("items")
        if (
            type(page.get("page")) is not int
            or page["page"] != source["requested_page"]
            or not isinstance(items, list)
            or not 0 < len(items) <= 200
        ):
            raise ValueError("native response/request page or item coverage mismatch")
        identifiers = []
        for item in items:
            if (
                not isinstance(item, dict)
                or type(item.get("id")) is not int
                or item["id"] <= 0
                or type(item.get("tsunamiEventId")) is not int
                or item["tsunamiEventId"] != source["ncei_event_id"]
            ):
                raise ValueError("native page includes an invalid/foreign item identity")
            identifiers.append(item["id"])
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate native item identity in retained page")
        pages[identity] = items
    coastal, distances, triage, assessed = [], [], [], []
    native_seen = set()
    assessed_all = 0
    for i, row in enumerate(lane.rows):
        record = lane.record_ids[i]
        saved = census[record]
        identity, position = record.rsplit(":", 1)
        ordinal = _positive_int(position)
        items = pages[identity]
        if ordinal > len(items):
            raise ValueError("native item position outside retained page")
        item = items[ordinal - 1]
        key = item["tsunamiEventId"], item["id"]
        if key in native_seen:
            raise ValueError("duplicate native item across selected records/pages")
        native_seen.add(key)
        if (
            row["record_id"] != record
            or row["event_id"] != lane.event_ids[i]
            or row["physical_site_id"] != lane.site_ids[i]
            or saved["event_id"] != lane.event_ids[i]
            or saved["physical_site_id"] != lane.site_ids[i]
            or saved["source_label"] != row["source_label"]
            or item.get("locationName") != row["source_label"]
            or _boolean(saved["included_primary"]) != bool(lane.included[i])
            or _positive_int(saved["native_item_id"]) != item["id"]
            or _positive_int(saved["native_tsunami_event_id"]) != item["tsunamiEventId"]
        ):
            raise ValueError("census/lane/exact native-item identity or primary-role mismatch")
        family = {2: "tide_gauge", 3: "deep_ocean_gauge"}.get(item.get("typeMeasurementId"))
        if family is None or row.get("measurement_family") != family:
            raise ValueError("canonical EDA family disagrees with exact native measurement type")
        coastal.append(family == "tide_gauge")
        distance = item.get("distFromSource")
        if (
            isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or distance <= 0
        ):
            raise ValueError("missing/nonpositive publisher distance; no imputation permitted")
        if float(row["native_distance_km"]) != distance:
            raise ValueError("publisher distance disagrees with frozen EDA native km")
        distances.append(float(distance))
        for key in ["travHours", "travMins"]:
            if (
                isinstance(item.get(key), bool)
                or not isinstance(item.get(key), (int, float))
                or not math.isfinite(item[key])
            ):
                raise ValueError("complete finite native duration components required")
        duration = 60 * item["travHours"] + item["travMins"]
        if (
            item["travHours"] < 0
            or not 0 <= item["travMins"] < 60
            or duration != lane.y[i]
            or duration != float(saved["reported_minutes"])
            or duration != float(row["target_minutes"])
        ):
            raise ValueError("native/census/model duration changed")
        state = saved["assessment"]
        if state not in {"assessed", "unassessed"}:
            raise ValueError("unknown frozen component assessment")
        if state == "assessed":
            assessed_all += 1
            flagged = _boolean(saved["large_component_disagreement"])
            if lane.included[i]:
                assessed.append(record)
                if flagged:
                    triage.append(record)
        elif saved["large_component_disagreement"] != "not_applicable":
            raise ValueError("unassessed components must remain explicitly unassessed")
    if (
        assessed_all != 1056
        or len(assessed) != 1050
        or len(triage) != 4
        or len({census[record]["event_id"] for record in triage}) != 4
    ):
        raise ValueError("unchanged1050assessed/four-event triage cohorts required")
    definition = {
        row["record_id"] for row in lane.rows if _boolean(row["definition_conflict_candidate"])
    }
    if definition != set(DEFINITION_RECORD_IDS) or any(
        _boolean(row["definition_conflict_candidate"])
        for target in ["T-OBS", "T-CAL"]
        for row in lanes[target].rows
    ):
        raise ValueError("exact two NCEI-only frozen definition candidates required")
    lata = census.get(LATA_RECORD, {})
    if (
        lata.get("event_id") != LATA_EVENT
        or lata.get("native_item_id") != "29865"
        or lata.get("native_tsunami_event_id") != "5560"
        or not _boolean(lata.get("included_primary", "False"))
    ):
        raise ValueError("exact primary LATA native29865/event5560 binding required")
    influence = {}
    for label, event in [
        ("tohoku", TOHOKU_EVENT),
        ("chile2010", CHILE_EVENT),
        ("influential2014", INFLUENTIAL_2014_EVENT),
    ]:
        if event not in set(lane.event_ids) or event not in exploration:
            raise ValueError("prespecified exploration influence event missing")
        influence[label] = metadata[event]["sequence_group"]
    years = {}
    for event in sorted(set(lane.event_ids)):
        origin = datetime.fromisoformat(metadata[event]["origin_utc"].replace("Z", "+00:00"))
        offset = origin.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("explicit UTC outcome-free event origin required")
        years[event] = origin.year
    keys = {radius: tuple(row[f"site_{radius}km"] for row in lane.rows) for radius in [1, 2, 5]}
    site_key_invariance(lane, keys)
    _verify_pins(root, pins)
    return SensitivityInputs(
        coastal=np.asarray(coastal, dtype=bool),
        event_years=years,
        publisher_distance_km=np.asarray(distances, dtype=float),
        triage_record_ids=tuple(triage),
        component_assessed_record_ids=tuple(assessed),
        definition_record_ids=DEFINITION_RECORD_IDS,
        lata_record_id=LATA_RECORD,
        influence_sequences=influence,
        site_keys_by_km=keys,
    )
