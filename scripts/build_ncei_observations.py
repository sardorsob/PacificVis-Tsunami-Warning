"""Build an immutable, separate NCEI reported-observation product from cached pages.

No network or onset inference. A duration candidate is an explicitly reported,
complete positive initial-wave travel duration, not a model-ready timing label.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import shutil
import sys
import tempfile
import tomllib
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import CONTRACT_FIELDS, SourceContract, load_contracts  # noqa: E402
from scripts.generate_waveform_contracts import validate_frozen_events  # noqa: E402

RECIPE = "ncei-secondary-reported-v1"
TARGET = "ncei_reported_initial_wave_travel_minutes_v1"
MISSING = "not_provided"
NATIVE_FIELDS = (
    "id",
    "tsunamiEventId",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "sourceEventValidity",
    "sourceCauseCode",
    "earthquakeEventId",
    "volcanoEventId",
    "sourceEqMagnitude",
    "doubtful",
    "publish",
    "typeMeasurementId",
    "country",
    "area",
    "locationName",
    "latitude",
    "longitude",
    "distFromSource",
    "arrDay",
    "arrHour",
    "arrMin",
    "travHours",
    "travMins",
    "maxWaveArrDay",
    "maxWaveArrHour",
    "maxWaveArrMin",
    "runupHt",
    "runupHoriz",
    "maxTroughHt",
    "maxTroughDay",
    "maxTroughHour",
    "maxTroughMin",
    "period",
    "firstMotion",
    "regionCode",
    "sourceOceanicTsunami",
    "referenceIds",
    "comments",
)
OBSERVATION_COLUMNS = (
    (
        "development_event_id",
        "ncei_event_id",
        "ncei_runup_id",
        "source_id",
        "source_row_number",
        "source_record_id",
        "source_family",
        "source_url",
        "raw_path",
        "source_sha256",
        "source_page",
        "event_match_json",
        "raw_record_json",
        "travel_state",
        "reported_duration_minutes",
        "arrival_utc",
        "arrival_calendar_state",
        "arrival_component_state",
        "max_wave_arrival_component_state",
        "coordinate_state",
        "coordinate_accuracy",
        "coordinate_datum",
        "coordinate_crs",
        "coordinate_semantics",
        "measurement_family",
        "reference_lineage_state",
        "attribution_restriction",
        "model_eligible",
        "physical_onset_validated",
        "target_id",
        "target_version",
    )
    + tuple("native_" + key for key in NATIVE_FIELDS)
    + (
        "duplicate_id_state",
        "collection_complete",
        "candidate_reason_codes",
        "duration_candidate",
    )
)


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(path: Path, root: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("input/output path escapes project root")
    return path


def _load_json(path: Path) -> Any:
    value = json.loads(path.read_text(encoding="utf-8"))
    _json(value)  # Reject nonstandard NaN/Infinity even in unused native fields.
    return value


def _verified(path: Path, root: Path, expected: str | None = None) -> str:
    path = _inside(path, root)
    digest = _sha(path)
    sidecar = _inside(path.with_name(path.name + ".sha256"), root)
    if sidecar.read_text().strip() != digest or (expected is not None and digest != expected):
        raise ValueError("raw source checksum mismatch")
    return digest


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _native(record: dict[str, Any], key: str) -> str:
    if key not in record:
        return MISSING
    value = record[key]
    return value if isinstance(value, str) else _json(value)


def _component_state(record: dict[str, Any], keys: tuple[str, ...], bounds: tuple[int, ...]) -> str:
    present = [record.get(key) is not None for key in keys]
    if not any(present):
        return "missing_components"
    if not all(present):
        return "partial_components"
    if any(
        not _integer(record[key], 1 if key.endswith("Day") else 0) or record[key] > bound
        for key, bound in zip(keys, bounds, strict=True)
    ):
        return "invalid_components"
    return "complete_components"


def _travel(record: dict[str, Any]) -> tuple[str, int | str]:
    present = [record.get(key) is not None for key in ("travHours", "travMins")]
    if not any(present):
        return "missing_components", "unknown"
    if not all(present):
        return "partial_components", "unknown"
    hours, minutes = record["travHours"], record["travMins"]
    if not _integer(hours) or not _integer(minutes) or minutes > 59:
        return "invalid_components", "unknown"
    duration = hours * 60 + minutes
    if duration <= 0:
        return "nonpositive_duration", "unknown"
    return "complete_positive", duration


def _coordinates(record: dict[str, Any]) -> str:
    values = [record.get("latitude"), record.get("longitude")]
    if all(value is None for value in values):
        return "missing_coordinates"
    if any(value is None for value in values):
        return "partial_coordinates"
    for value, bound in zip(values, (90, 180), strict=True):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or abs(value) > bound:
            return "invalid_coordinates"
        if not math.isfinite(value):
            return "invalid_coordinates"
    return "reported_native_coordinates"


def _proof(schema: Path, proof: Path, source: Path, root: Path) -> None:
    _verified(schema, root)
    document = _load_json(schema)
    fields = document["components"]["schemas"]["RunupView"]["properties"]
    required = {
        "id",
        "tsunamiEventId",
        "arrDay",
        "arrHour",
        "arrMin",
        "travHours",
        "travMins",
        "typeMeasurementId",
        "publish",
        "doubtful",
        "latitude",
        "longitude",
        "maxWaveArrDay",
        "maxWaveArrHour",
        "maxWaveArrMin",
    }
    if (
        not required <= set(fields)
        or "/hazard-service/api/v1/tsunamis/runups" not in document["paths"]
    ):
        raise ValueError("NCEI schema lacks required source fields")
    text, digest = _inside(source, root).read_text(encoding="utf-8"), _sha(source)
    evidence = _load_json(_inside(proof, root))["official_app_semantic_evidence"]
    quotes: list[str] = []
    for quote in evidence:
        start, end = quote["start_char"], quote["end_char"]
        if (
            not _integer(start)
            or not _integer(end)
            or end <= start
            or quote["source_sha256"] != digest
            or text[start:end] != quote["text"]
        ):
            raise ValueError("official semantics quote/hash mismatch")
        quotes.append(quote["text"].lower())
    combined = "\n".join(quotes)
    if not all(
        fragment in combined
        for fragment in (
            "arrival of the initial tsunami wave",
            "time in hours and minutes",
            "arrival of the maximum tsunami wave",
            "latitude and longitude",
        )
    ):
        raise ValueError("official source semantics not demonstrated")


def _matches(
    path: Path, events: dict[str, dict[str, Any]], root: Path
) -> dict[str, dict[str, str]]:
    with _inside(path, root).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    ncei_ids: set[int] = set()
    for row in rows:
        event_id = row["development_event_id"]
        ncei_id = int(row["ncei_event_id"])
        if (
            event_id not in events
            or events[event_id]["role"] != "development"
            or event_id in result
            or ncei_id in ncei_ids
            or ncei_id <= 0
            or row["review_status"] != "independently_reviewed"
            or not all(
                row.get(key, "").strip()
                for key in ("reviewer", "review_basis", "metadata_source_id", "metadata_source_url")
            )
        ):
            raise ValueError("event match is not a unique independently reviewed development match")
        metadata = _inside(root / row["metadata_raw_path"], root)
        _verified(metadata, root, row["metadata_sha256"])
        items = _load_json(metadata)["items"]
        matching = [item for item in items if item.get("id") == ncei_id]
        if len(matching) != 1:
            raise ValueError("matched NCEI event absent or duplicated in pinned metadata")
        source_date = "-".join(
            f"{matching[0][key]:0{width}d}"
            for key, width in (("year", 4), ("month", 2), ("day", 2))
        )
        if source_date != events[event_id]["usgs_time"][:10]:
            raise ValueError("matched metadata source date differs from frozen event")
        result[event_id] = row
        ncei_ids.add(ncei_id)
    return result


def _query(contract: SourceContract) -> tuple[int, int, int]:
    parsed = urlsplit(contract.url)
    query = parse_qs(parsed.query, strict_parsing=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.ngdc.noaa.gov"
        or parsed.fragment
        or parsed.path != "/hazel/hazard-service/api/v1/tsunamis/runups"
        or set(query) != {"tsunamiEventId", "typeMeasurementId", "itemsPerPage", "page"}
        or sorted(query["typeMeasurementId"]) != ["2", "3"]
        or any(len(query[key]) != 1 for key in ("tsunamiEventId", "itemsPerPage", "page"))
    ):
        raise ValueError("unsupported or unsafe NCEI runup query")
    event, page, size = (int(query[key][0]) for key in ("tsunamiEventId", "page", "itemsPerPage"))
    if event <= 0 or page <= 0 or not 1 <= size <= 200:
        raise ValueError("invalid NCEI query pagination")
    return event, page, size


def _sources(
    configs: Sequence[Path], receipts: Sequence[Path], root: Path
) -> tuple[dict[str, SourceContract], dict[str, list[dict[str, Any]]]]:
    contracts: dict[str, SourceContract] = {}
    for path in configs:
        for contract in load_contracts(_inside(path, root)):
            if contract.source_id in contracts and contracts[contract.source_id] != contract:
                raise ValueError("conflicting repeated source contract")
            if contract.availability != "approved":
                raise ValueError("only approved NCEI observation contracts can be processed")
            contracts[contract.source_id] = contract
    results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in receipts:
        path = _inside(path, root)
        inputs = _load_json(path.with_name("inputs.json"))
        outputs = _load_json(path)
        if (
            len({row["source_id"] for row in inputs}) != len(inputs)
            or len({row["source_id"] for row in outputs}) != len(outputs)
            or {row["source_id"] for row in inputs} != {row["source_id"] for row in outputs}
        ):
            raise ValueError("receipt input/output source conservation failure")
        for row in inputs:
            contract = contracts.get(row["source_id"])
            if contract is None or any(
                str(getattr(contract, key)) != row[key] for key in CONTRACT_FIELDS
            ):
                raise ValueError("receipt differs from pinned source contract")
        for row in outputs:
            results[row["source_id"]].append(
                {**row, "receipt_path": path.relative_to(root).as_posix()}
            )
    if not contracts or set(contracts) != set(results):
        raise ValueError("each configured source requires an acquisition disposition")
    return contracts, results


def _csv(path: Path, rows: list[dict[str, Any]], columns: Sequence[str]) -> None:
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped,
    ):
        with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)


def build_ncei_observations(
    configs: Sequence[Path],
    receipts: Sequence[Path],
    event_matches: Path,
    events_config: Path,
    selection: Path,
    schema: Path,
    semantics_proof: Path,
    semantics_source: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Verify cached sources and publish deterministic source-grain observations."""
    root = root.resolve()
    output = _inside(output, root)
    if output.exists():
        raise FileExistsError("immutable NCEI output already exists")
    events_config, selection = _inside(events_config, root), _inside(selection, root)
    events = validate_frozen_events(tomllib.loads(events_config.read_text()), selection)
    matches = _matches(event_matches, events, root)
    _proof(schema, semantics_proof, semantics_source, root)
    contracts, results = _sources(configs, receipts, root)
    pages: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_pins: set[Path] = set()
    for source_id, contract in sorted(contracts.items()):
        ncei_id, query_page, size = _query(contract)
        metadata = json.loads(contract.station_metadata)
        event_id = metadata["event_id"]
        if (
            event_id not in matches
            or int(matches[event_id]["ncei_event_id"]) != ncei_id
            or type(metadata.get("ncei_event_id")) is not int
            or metadata["ncei_event_id"] != ncei_id
        ):
            raise ValueError("source contract lacks the reviewed development event match")
        attempts = results[source_id]
        if any(row["local_path"] != contract.local_path.as_posix() for row in attempts):
            raise ValueError("receipt source path mismatch")
        successes = [row for row in attempts if row["status"] in {"downloaded", "cached"}]
        page: dict[str, Any] = dict(
            development_event_id=event_id,
            ncei_event_id=ncei_id,
            source_id=source_id,
            source_url=contract.url,
            raw_path=contract.local_path.as_posix(),
            acquisition_receipts=_json(sorted({row["receipt_path"] for row in attempts})),
            acquisition_dispositions=_json(
                [
                    {
                        key: attempt.get(key, "not_recorded")
                        for key in (
                            "receipt_path",
                            "status",
                            "reason",
                            "sha256",
                            "bytes",
                            "final_url",
                        )
                    }
                    for attempt in sorted(attempts, key=lambda attempt: attempt["receipt_path"])
                ]
            ),
            acquisition_status="verified" if successes else "unavailable",
            source_sha256="unknown",
            page=query_page,
            items_per_page=size,
            total_pages="unknown",
            total_items="unknown",
            source_records=0,
        )
        if successes:
            raw_path = _inside(root / contract.local_path, root)
            digest = _verified(raw_path, root)
            if any(
                row["sha256"] != digest
                or row["bytes"] != raw_path.stat().st_size
                or (
                    row.get("final_url") != contract.url
                    and not (row["status"] == "cached" and row.get("final_url") == "not-recorded")
                )
                for row in successes
            ):
                raise ValueError("receipt checksum/size/final URL mismatch")
            source_pins.update((raw_path, raw_path.with_name(raw_path.name + ".sha256")))
            payload_value = _load_json(raw_path)
            if not isinstance(payload_value, dict):
                raise ValueError("NCEI page must be an object")
            payload = cast(dict[str, Any], payload_value)
            if {"error", "errors"} & payload.keys():
                raise ValueError("NCEI error response cannot be parsed as observation data")
            for key in ("status", "statusCode", "status_code"):
                status = payload.get(key)
                if isinstance(status, str):
                    status = status.strip().casefold()
                    if status.isdecimal():
                        status = int(status)
                if (
                    isinstance(status, (int, float))
                    and not isinstance(status, bool)
                    and status >= 400
                ) or status in ("error", "failed", "failure"):
                    raise ValueError("NCEI error response cannot be parsed as observation data")
            if (
                not isinstance(payload.get("items"), list)
                or any(not isinstance(row, dict) for row in payload["items"])
                or any(
                    not _integer(payload.get(key))
                    for key in ("page", "totalPages", "itemsPerPage", "totalItems")
                )
                or payload["page"] != query_page
                or payload["itemsPerPage"] != size
                or payload["page"] > max(1, payload["totalPages"])
                or len(payload["items"]) > size
            ):
                raise ValueError("NCEI page schema/query mismatch")
            page.update(
                source_sha256=digest,
                total_pages=payload["totalPages"],
                total_items=payload["totalItems"],
                source_records=len(payload["items"]),
            )
            for ordinal, item in enumerate(cast(list[dict[str, Any]], payload["items"]), 1):
                if type(item.get("tsunamiEventId")) is not int or item["tsunamiEventId"] != ncei_id:
                    raise ValueError("raw record event differs from reviewed development event")
                travel_state, duration = _travel(item)
                row = dict(
                    development_event_id=event_id,
                    ncei_event_id=ncei_id,
                    ncei_runup_id=item.get("id", "unknown"),
                    source_id=source_id,
                    source_row_number=ordinal,
                    source_record_id=f"{source_id}:{ordinal}",
                    source_family="NCEI_secondary_reported",
                    source_url=contract.url,
                    raw_path=contract.local_path.as_posix(),
                    source_sha256=digest,
                    source_page=query_page,
                    event_match_json=_json(matches[event_id]),
                    raw_record_json=_json(item),
                    travel_state=travel_state,
                    reported_duration_minutes=duration,
                    arrival_utc="unknown",
                    arrival_calendar_state="month_year_unresolved",
                    arrival_component_state=_component_state(
                        item, ("arrDay", "arrHour", "arrMin"), (31, 23, 59)
                    ),
                    max_wave_arrival_component_state=_component_state(
                        item, ("maxWaveArrDay", "maxWaveArrHour", "maxWaveArrMin"), (31, 23, 59)
                    ),
                    coordinate_state=_coordinates(item),
                    coordinate_accuracy="unknown",
                    coordinate_datum="unknown",
                    coordinate_crs="unknown",
                    coordinate_semantics="reported_effect_location_not_verified_deployment",
                    measurement_family=(
                        "tide_gauge"
                        if item.get("typeMeasurementId") == 2
                        else "deep_ocean_gauge"
                        if item.get("typeMeasurementId") == 3
                        else "other_or_unknown"
                    ),
                    reference_lineage_state="original_references_not_independently_reviewed",
                    attribution_restriction="preserve_NOAA_and_original_provider_credit_review_redistribution",
                    model_eligible=False,
                    physical_onset_validated=False,
                    target_id="NCEI-OBS-DURATION",
                    target_version=TARGET,
                )
                row.update({"native_" + key: _native(item, key) for key in NATIVE_FIELDS})
                records.append(row)
        pages.append(page)
        grouped[event_id].append(page)

    identities: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if _integer(row["ncei_runup_id"], 1):
            identities[(row["development_event_id"], row["ncei_runup_id"])].append(row)
    event_states: list[dict[str, Any]] = []
    for event_id, event_pages in sorted(grouped.items()):
        event_rows = [row for row in records if row["development_event_id"] == event_id]
        issues: list[str] = []
        available = [page for page in event_pages if page["acquisition_status"] == "verified"]
        totals = {
            (page["total_pages"], page["total_items"], page["items_per_page"]) for page in available
        }
        if len(available) != len(event_pages):
            issues.append("unavailable_pages")
        if len(totals) != 1:
            issues.append("inconsistent_or_absent_page_metadata")
        else:
            count, total, size = next(iter(totals))
            if count != (math.ceil(total / size) if total else count) or (
                not total and count not in (0, 1)
            ):
                issues.append("inconsistent_total_pages")
            if sorted(page["page"] for page in available) != list(range(1, max(count, 1) + 1)):
                issues.append("missing_or_duplicate_pages")
            if total != len(event_rows):
                issues.append("total_items_mismatch")
            for page in available:
                expected = min(size, max(0, total - (page["page"] - 1) * size))
                if page["source_records"] != expected:
                    issues.append("page_row_count_mismatch")
        valid_ids = {
            row["ncei_runup_id"] for row in event_rows if _integer(row["ncei_runup_id"], 1)
        }
        if len(valid_ids) != len(event_rows):
            issues.append("duplicate_or_invalid_runup_ids")
        complete = not issues
        event_states.append(
            dict(
                development_event_id=event_id,
                ncei_event_id=int(matches[event_id]["ncei_event_id"]),
                source_records=len(event_rows),
                unique_runup_ids=len(valid_ids),
                collection_complete=complete,
                collection_reason_codes=sorted(set(issues)),
            )
        )
        for row in event_rows:
            siblings = (
                identities.get((event_id, row["ncei_runup_id"]), [])
                if _integer(row["ncei_runup_id"], 1)
                else []
            )
            row["duplicate_id_state"] = (
                "invalid_id"
                if not _integer(row["ncei_runup_id"], 1)
                else "unique"
                if len(siblings) == 1
                else "duplicate_identical"
                if len({r["raw_record_json"] for r in siblings}) == 1
                else "duplicate_conflicting"
            )
            reasons: list[str] = []
            if not complete:
                reasons.append("incomplete_collection")
            if row["duplicate_id_state"] != "unique":
                reasons.append(row["duplicate_id_state"])
            if row["travel_state"] != "complete_positive":
                reasons.append(row["travel_state"])
            item = json.loads(row["raw_record_json"])
            if item.get("doubtful") != "n":
                reasons.append("doubtfulness_not_clear")
            if item.get("publish") is not True:
                reasons.append("publication_not_true")
            if type(item.get("typeMeasurementId")) is not int or item["typeMeasurementId"] not in (
                2,
                3,
            ):
                reasons.append("measurement_not_requested_gauge")
            if row["coordinate_state"] == "invalid_coordinates":
                reasons.append("invalid_coordinates")
            row["collection_complete"] = complete
            row["candidate_reason_codes"] = _json(reasons)
            row["duration_candidate"] = not reasons

    records.sort(
        key=lambda row: (
            events[row["development_event_id"]]["usgs_time"],
            row["development_event_id"],
            row["ncei_runup_id"] if _integer(row["ncei_runup_id"], 1) else sys.maxsize,
            row["source_id"],
            row["source_row_number"],
        )
    )
    pages.sort(
        key=lambda page: (
            events[page["development_event_id"]]["usgs_time"],
            page["development_event_id"],
            page["page"],
            page["source_id"],
        )
    )
    summary: dict[str, Any] = dict(
        recipe_version=RECIPE,
        source_family="NCEI_secondary_reported",
        target_version=TARGET,
        source_records=len(records),
        unique_runup_ids=len(identities),
        reported_duration_candidates=sum(row["duration_candidate"] for row in records),
        collection_complete=all(state["collection_complete"] for state in event_states),
        events=event_states,
        travel_states=dict(sorted(Counter(row["travel_state"] for row in records).items())),
        arrival_component_states=dict(
            sorted(Counter(row["arrival_component_state"] for row in records).items())
        ),
        candidate_reason_counts=dict(
            sorted(
                Counter(
                    reason
                    for row in records
                    for reason in json.loads(row["candidate_reason_codes"])
                ).items()
            )
        ),
        model_eligible=False,
        physical_onset_validated=False,
        limitations=[
            "Reported durations are separate NCEI candidates, not NTWC arrival/calibration pairs.",
            "Arrival month/year remain unresolved; source date describes the source event.",
            "Original references and historical deployments are not independently validated.",
            "Coordinates have unknown datum/accuracy; no MCAR/MAR/MNAR claim is made.",
            "An NCEI metadata match does not clear existing event attribution/model restrictions.",
        ],
    )
    input_paths = (
        set(configs) | set(receipts) | {path.with_name("inputs.json") for path in receipts}
    )
    input_paths.update(
        (event_matches, events_config, selection, schema, semantics_proof, semantics_source)
    )
    for match in matches.values():
        path = root / match["metadata_raw_path"]
        input_paths.update((path, path.with_name(path.name + ".sha256")))
    input_paths.update(source_pins)
    pins = [
        {"path": _inside(path, root).relative_to(root).as_posix(), "sha256": _sha(path)}
        for path in input_paths
    ]
    pins.sort(key=lambda pin: pin["path"])
    columns = OBSERVATION_COLUMNS
    dictionary = dict(
        grain="One raw NCEI runup record occurrence per source page; duplicate IDs are retained.",
        target=dict(
            id="NCEI-OBS-DURATION",
            version=TARGET,
            units="minutes",
            meaning="Explicit complete positive initial-wave reported travel duration.",
            eligibility="Complete unique-ID pagination, hours>=0, minutes0..59, sum>0; "
            "doubtful=n; publish=true; measurement2/3; no invalid coordinates. "
            "Missing coordinate components are retained as unknown and do not imply a deployment.",
        ),
        missing=dict(native_absent=MISSING, native_null="null", derived_unresolved="unknown"),
        columns={
            key: (
                "Original source field; type and absence preserved in raw_record_json."
                if key.startswith("native_")
                else key.replace("_", " ")
            )
            for key in columns
        },
        native_field_semantics={
            "year/month/day/hour/minute/second": "NCEI source-event origin fields.",
            "arrDay/arrHour/arrMin": "Initial-wave UTC calendar day/hour/minute as reported.",
            "travHours/travMins": "Initial-wave duration from source to effect location.",
            "maxWaveArrDay/maxWaveArrHour/maxWaveArrMin": "Maximum-wave arrival only.",
            "typeMeasurementId": "Requested gauge categories: 2 tide gauge, 3 deep ocean gauge.",
            "latitude/longitude": "Reported effect location; deployment unverified.",
            "runupHt/runupHoriz/maxTroughHt": "Native measurements; no arrival substitution.",
            "doubtful/publish/sourceEventValidity/sourceCauseCode": "Native flags/codes.",
        },
        raw_preservation="Original JSON bytes remain at raw_path with SHA256; "
        "raw_record_json preserves all fields.",
        arrival="arr* is initial-wave UTC day/hour/minute; no month/year inference. "
        "maxWaveArr* stays separate.",
        geography="Reported effect location; accuracy, datum and CRS unverified. "
        "No station identity crosswalk.",
        science="All model_eligible and physical_onset_validated flags remain false.",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ncei-build-", dir=output.parent))
    try:
        _csv(temporary / "observations.csv.gz", records, columns)
        _csv(
            temporary / "reported_duration_candidates.csv.gz",
            [row for row in records if row["duration_candidate"]],
            columns,
        )
        _csv(temporary / "source_pages.csv.gz", pages, list(pages[0]))
        for name, value in (("summary.json", summary), ("data_dictionary.json", dictionary)):
            (temporary / name).write_text(_json(value) + "\n")
        manifest = dict(
            recipe_version=RECIPE,
            inputs=pins,
            code=[
                dict(path=relative, sha256=_sha(Path(__file__).resolve().parents[1] / relative))
                for relative in (
                    "scripts/build_ncei_observations.py",
                    "pipeline/acquisition.py",
                    "scripts/generate_waveform_contracts.py",
                )
            ],
            outputs=[
                dict(path=path.name, sha256=_sha(path), bytes=path.stat().st_size)
                for path in sorted(temporary.iterdir())
            ],
        )
        (temporary / "manifest.json").write_text(_json(manifest) + "\n")
        if output.exists():
            raise FileExistsError("immutable NCEI output already exists")
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--receipts", type=Path, action="append", required=True)
    for name in (
        "event-matches",
        "events",
        "selection",
        "schema",
        "semantics-proof",
        "semantics-source",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(
        _json(
            build_ncei_observations(
                args.config,
                args.receipts,
                args.event_matches,
                args.events,
                args.selection,
                args.schema,
                args.semantics_proof,
                args.semantics_source,
                args.root,
                args.output,
            )
        )
    )


if __name__ == "__main__":
    main()
