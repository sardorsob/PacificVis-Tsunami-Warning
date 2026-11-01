"""Preserve development audit samples with source timing, values and missingness.

Each --config pairs with the corresponding --receipts outputs.json. Event identity
is the source path's parent directory, or an explicit --source-map JSON object
mapping source IDs to event IDs. No arrival labels, tide subtraction or interpolation.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import math
import re
import shutil
import sys
import tempfile
import tomllib
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.stations import parse_ntwc_header  # noqa: E402
from pipeline.acquisition import SourceContract, load_contracts, verify_cdx_evidence  # noqa: E402
from scripts.generate_waveform_contracts import (  # noqa: E402
    CONTROL_OFFSETS,
    event_window,
    overlapping_events,
    parse_utc,
    validate_frozen_events,
)

COLUMNS: tuple[str, ...] = (
    "observation_id",
    "source_row_id",
    "event_id",
    "source_id",
    "purpose",
    "source_row_number",
    "station_key",
    "provider_station_id",
    "sensor",
    "physical_site_id",
    "deployment_id",
    "timestamp_utc",
    "timestamp_state",
    "raw_timestamp",
    "raw_epoch",
    "raw_value",
    "numeric_value",
    "value_state",
    "units",
    "vertical_datum",
    "qc_state",
    "qc_json",
    "duplicate_timestamp",
    "raw_row_json",
)


class UnsupportedWaveformFormat(ValueError):
    """Retain a known source family whose clock or measurement meaning is unresolved."""

    def __init__(self, family: str, reason: str, processing_level: str = "unknown") -> None:
        super().__init__(reason)
        self.family = family
        self.processing_level = processing_level


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value(raw: Any) -> tuple[str | float, str]:
    if raw is None:
        return "unknown", "source_null"
    text = str(raw).strip()
    if not text:
        return "unknown", "blank"
    if text.casefold() in {"none", "null", "na", "n/a", "missing", "-"}:
        return "unknown", "source_missing_token"
    try:
        value = float(text)
    except ValueError:
        return "unknown", "nonnumeric"
    return (value, "finite_numeric") if math.isfinite(value) else ("unknown", "nonfinite")


def _coops(
    contract: SourceContract, raw: bytes, window: tuple[datetime, datetime]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = urlsplit(contract.url)
    query = parse_qs(url.query)
    product = query.get("product", [""])[0]
    if (
        url.hostname != "api.tidesandcurrents.noaa.gov"
        or product not in {"one_minute_water_level", "water_level"}
        or query.get("time_zone") != ["gmt"]
        or query.get("units") != ["metric"]
    ):
        raise ValueError("unsupported CO-OPS source/time basis/product")
    station = query["station"][0]
    start, stop = window
    if query.get("begin_date") != [start.strftime("%Y%m%d")] or query.get("end_date") != [
        (stop - timedelta(days=1)).strftime("%Y%m%d")
    ]:
        raise ValueError("CO-OPS window differs from frozen event origin")
    payload = json.loads(raw)
    if "error" in payload:
        if "data" in payload:
            raise ValueError("CO-OPS response mixes error and observation data")
        return [], dict(processing_status="unavailable_provider_response", provider_error=payload)
    if str(payload.get("metadata", {}).get("id")) != station:
        raise ValueError("CO-OPS station mismatch")
    cadence = 60 if product == "one_minute_water_level" else 360
    records: list[dict[str, Any]] = []
    for sample in payload["data"]:
        value, state = _value(sample.get("v"))
        stamp, time_state = "unknown", "invalid_timestamp"
        try:
            parsed = datetime.strptime(str(sample["t"]), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            if start <= parsed < stop and (parsed - start).total_seconds() % cadence == 0:
                stamp, time_state = parsed.isoformat().replace("+00:00", "Z"), "reported_utc"
            else:
                time_state = "outside_requested_grid"
        except (KeyError, ValueError):
            pass
        qc = {k: v for k, v in sample.items() if k not in {"t", "v"}}
        records.append(
            dict(
                timestamp_utc=stamp,
                timestamp_state=time_state,
                raw_timestamp=sample.get("t", ""),
                raw_epoch="not_provided",
                raw_value=sample.get("v", ""),
                numeric_value=value,
                value_state=state,
                qc_state="provided" if qc else "not_provided",
                qc_json=_json(qc),
                raw_row_json=_json(sample),
            )
        )
    return records, dict(
        station_key=f"coops-{station}",
        provider_station_id=station,
        provider="CO-OPS",
        display_station_key=f"coops:{station}",
        sensor="unknown",
        units="m",
        vertical_datum=query["datum"][0],
        declared_cadence_seconds=cadence,
        expected_grid_timestamps=int((stop - start).total_seconds() / cadence),
        source_metadata=payload["metadata"],
    )


def _ntwc_header(text: str, filename: str) -> dict[str, Any]:
    """Read supported header variants without inferring absent measurement metadata."""
    lines = text.splitlines()
    if lines and lines[0].startswith("# Water level record") and "# Detided by NCTR" in text:
        raise UnsupportedWaveformFormat(
            "nctr_predetided_event_relative",
            "provider-detided event-relative series needs verified height units and time zone; "
            "keep a separate derived-product family",
            "provider_predetided",
        )
    if lines and re.fullmatch(r"[+-]\d+\.\d+\s+\d{12}", lines[0].strip()):
        raise UnsupportedWaveformFormat(
            "headerless_encoded_clock",
            "headerless encoded clock needs source documentation for encoding, units and time zone",
        )
    if lines and re.fullmatch(r"\d+\.\d+\s+[+-]?\d+\.\d+", lines[0].strip()):
        raise UnsupportedWaveformFormat(
            "headerless_fractional_day",
            "headerless fractional-day candidate needs year/day convention, time zone and units",
        )
    unit_only = len(lines) >= 4 and lines[1].split() == [
        "Radar", "cm", "UTC", "sec", "Unfiltered"
    ]
    adapted = list(lines)
    if unit_only:
        # The short source header omits cadence, datum and relay. Explicit unknown
        # tokens let the shared identity/date checks run without inventing them.
        adapted[1] = "Radar cm UTC unknown sec unknown unknown Unfiltered"
    try:
        header = parse_ntwc_header("\n".join(adapted), filename)
    except ValueError as exc:
        if "header date conflicts with filename" in str(exc):
            raise UnsupportedWaveformFormat(
                "ntwc_header_filename_date_conflict",
                f"{exc}; a source-specific review rule is required before date promotion",
            ) from exc
        raise
    variable = re.fullmatch(r"([1-9]\d*(?:\.\d+)?)\+", str(header["cadence_value"]))
    if unit_only or variable:
        if " ".join(lines[3].split()) != (
            "Data Format: SampleTime(epochal 1/1/1970) WaterLevel SampleTime(yyymmddhhmmss)"
        ):
            raise ValueError("unsupported NTWC redundant-clock column definition")
        if header["time_basis"] != "UTC" or header["cadence_units"] not in {"min", "sec"}:
            raise ValueError("unsupported NTWC time basis or cadence units")
        if header["units"] not in {"m", "cm", "mm"} or header["processing"] != "Unfiltered":
            raise ValueError("unsupported NTWC measurement units or processing level")
        header.update(
            format_rule_id="ntwc_radar_unit_only_v1" if unit_only else "ntwc_variable_cadence_v1",
            source_measurement_header=lines[1],
            cadence_state="not_declared" if unit_only else "variable_nominal",
        )
        if variable:
            nominal = float(variable[1]) * (
                60 if header["cadence_units"] == "min" else 1
            )
            if not math.isfinite(nominal) or nominal <= 0:
                raise ValueError("invalid NTWC nominal cadence")
            header["nominal_cadence_seconds"] = nominal
    return header


def _ntwc(contract: SourceContract, raw: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text = raw.decode("utf-8")
    lines = text.splitlines()
    header = _ntwc_header(text, contract.local_path.name)
    if header["time_basis"] != "UTC" or header["cadence_units"] not in {"min", "sec"}:
        raise ValueError("unsupported NTWC time basis or cadence units")
    cadence: float | str = (
        "unknown"
        if header.get("cadence_state") in {"not_declared", "variable_nominal"}
        else float(header["cadence_value"]) * (60 if header["cadence_units"] == "min" else 1)
    )
    if isinstance(cadence, float) and (not math.isfinite(cadence) or cadence <= 0):
        raise ValueError("invalid NTWC cadence")
    day_end = datetime.fromisoformat(str(header["header_date"])).replace(tzinfo=UTC) + timedelta(
        days=1
    )
    records: list[dict[str, Any]] = []
    for line in lines[4:]:
        tokens = line.split()
        epoch, raw_value, calendar = tokens if len(tokens) == 3 else ("", "", "")
        value, state = _value(raw_value)
        stamp, time_state = "unknown", "malformed_row" if len(tokens) != 3 else "invalid_timestamp"
        if len(tokens) == 3:
            try:
                if not re.fullmatch(r"\d{12}(?:\d{2})?", calendar):
                    raise ValueError("unsupported calendar timestamp precision")
                date = datetime.strptime(
                    calendar, "%Y%m%d%H%M%S" if len(calendar) == 14 else "%Y%m%d%H%M"
                ).replace(tzinfo=UTC)
                epoch_date = datetime.fromtimestamp(int(epoch), UTC)
                comparable = (
                    epoch_date
                    if len(calendar) == 14
                    else epoch_date.replace(second=0, microsecond=0)
                )
                if comparable == date and epoch_date == day_end:
                    stamp = epoch_date.isoformat().replace("+00:00", "Z")
                    time_state = "header_day_end_boundary"
                elif comparable == date and date.date().isoformat() != header["header_date"]:
                    time_state = "outside_header_day"
                elif comparable == date:
                    stamp = epoch_date.isoformat().replace("+00:00", "Z")
                    time_state = (
                        "epoch_calendar_agree"
                        if len(calendar) == 14
                        else "epoch_calendar_minute_agree"
                    )
                else:
                    time_state = "epoch_calendar_mismatch"
            except (ValueError, OverflowError, OSError):
                pass
        records.append(
            dict(
                timestamp_utc=stamp,
                timestamp_state=time_state,
                raw_timestamp=calendar,
                raw_epoch=epoch,
                raw_value=raw_value,
                numeric_value=value,
                value_state=state,
                qc_state="not_provided",
                qc_json="{}",
                raw_row_json=_json({"line": line}),
            )
        )
    station_id = str(header["header_station_id"])
    meta = dict(
        station_key=f"ntwc-{header['link_code']}",
        provider_station_id="unknown"
        if station_id.casefold() in {"none", "unknown"}
        else station_id,
        sensor=header["link_sensor"],
        provider=header["provider"],
        display_station_key=f"coops:{station_id}"
        if header["provider"] in {"NOS", "NOAA", "CO-OPS"} and re.fullmatch(r"\d{7}", station_id)
        else f"unverified:ntwc-{header['link_code']}",
        units=header["units"],
        vertical_datum=header["vertical_datum"],
        declared_cadence_seconds=cadence,
        expected_grid_timestamps="unknown",
        source_metadata=header,
    )
    if header.get("format_rule_id"):
        meta["source_processing_level"] = "source_reported_unfiltered"
        meta["signal_family"] = (
            "bottom_pressure_or_depth"
            if str(header["header_name"]).casefold().startswith("dart")
            or str(header["measurement_system"]).casefold().startswith("dart")
            else "coastal_water_level"
        )
    return records, meta


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as stream,
        gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed,
    ):
        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
            writer = csv.DictWriter(text, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)


def _coverage(
    groups: dict[tuple[Any, ...], list[tuple[dict[str, Any], list[dict[str, Any]]]]],
    events: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Operational display coverage only; neither onset nor modeling eligibility."""
    result: list[dict[str, Any]] = []
    for key, members in sorted(groups.items()):
        eid, station, sensor, cadence, units, datum, _, _ = key
        start = parse_utc(events[eid]["usgs_time"]) - timedelta(hours=6)
        stop = start + timedelta(hours=36)
        expected = math.ceil((stop - start).total_seconds() / cadence)
        rows = [r for _, samples in members for r in samples]
        counts = Counter(r["timestamp_utc"] for r in rows if r["timestamp_utc"] != "unknown")
        bins = {
            int((datetime.fromisoformat(r["timestamp_utc"]) - start).total_seconds() // cadence)
            for r in rows
            if r["timestamp_utc"] != "unknown"
            and start <= datetime.fromisoformat(r["timestamp_utc"]) < stop
            and r["value_state"] == "finite_numeric"
            and counts[r["timestamp_utc"]] == 1
        }
        longest = streak = 0
        previous = -2
        for index in sorted(bins):
            streak = streak + 1 if index == previous + 1 else 1
            longest = max(longest, streak)
            previous = index
        meta = members[0][0]
        known = re.fullmatch(r"coops:\d{7}", meta["display_station_key"]) is not None
        result.append(
            dict(
                event_id=eid,
                station_key=station,
                sensor=sensor,
                display_station_key=meta["display_station_key"],
                display_eligible=known
                and len(bins) / expected >= 0.8
                and longest * cadence >= 3600,
                source_ids=sorted(m[0]["source_id"] for m in members),
                window_start_utc=start.isoformat(),
                window_stop_utc=stop.isoformat(),
                purpose="event_window",
                provider=meta["provider"],
                provider_station_id=meta["provider_station_id"],
                expected_bins=expected,
                usable_bins=len(bins),
                coverage_fraction=len(bins) / expected,
                longest_supported_minutes=longest * cadence / 60,
                sample_rows=len(rows),
                duplicate_timestamp_rows=sum(n for n in counts.values() if n > 1),
                unusable_value_rows=sum(r["value_state"] != "finite_numeric" for r in rows),
                invalid_timestamp_rows=sum(r["timestamp_utc"] == "unknown" for r in rows),
                declared_cadence_seconds=cadence,
                units=units,
                vertical_datum=datum,
                identity_status="source_header_or_provider_id" if known else "source_code_only",
                rule_id="viewer_36h_80pct_60min_v1",
            )
        )
    return result


def build(
    configs: Sequence[Path],
    receipts: Sequence[Path],
    events_config: Path,
    root: Path,
    output: Path,
    *,
    source_map: Path | None = None,
    selection: Path | None = None,
    known_catalog: Path | None = None,
    retain_unparsed: bool = False,
    header_evidence_configs: Sequence[Path] = (),
) -> dict[str, Any]:
    """Verify exact receipts and produce one immutable table per development source."""
    if len(configs) != len(receipts) or not configs:
        raise ValueError("each config requires one corresponding receipt")
    if output.exists():
        raise FileExistsError(output)
    header_configs = {p.resolve() for p in header_evidence_configs}
    if not header_configs <= {p.resolve() for p in configs}:
        raise ValueError("header evidence config is absent from paired configs")
    if header_configs and selection is None:
        raise ValueError("header evidence requires frozen selection verification")
    root = root.resolve()
    events: dict[str, dict[str, Any]] = {}
    event_document = tomllib.loads(events_config.read_text())
    if selection:
        validate_frozen_events(event_document, selection)
    for event in event_document["events"].values():
        eid = event["event_id"]
        if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", eid):
            raise ValueError("unsafe event ID")
        if eid in events:
            raise ValueError("duplicate event ID")
        if event["role"] not in {"development", "sealed_evaluation"}:
            raise ValueError("unknown event role")
        events[eid] = event
    reserved = {
        eid: parse_utc(e["usgs_time"])
        for eid, e in events.items()
        if e["role"] == "sealed_evaluation"
    }
    catalog_origins: dict[str, datetime] = {}
    if known_catalog:
        if (
            _sha(known_catalog)
            != known_catalog.with_name(known_catalog.name + ".sha256").read_text().strip()
        ):
            raise ValueError("catalog checksum mismatch")
        catalog_origins = {
            r["id"]: parse_utc(r["time"])
            for r in csv.DictReader(known_catalog.open())
            if r["type"] == "earthquake"
        }
    mapping: dict[str, str] = json.loads(source_map.read_text()) if source_map else {}
    entries: list[dict[str, Any]] = []
    summary: dict[str, Any] = dict(
        status="source_samples_only_not_onset_validated",
        sources=entries,
        input_sha256={
            str(p): _sha(p)
            for p in [
                *configs,
                *receipts,
                events_config,
                *([source_map] if source_map else []),
                *([selection] if selection else []),
                *([known_catalog] if known_catalog else []),
            ]
        },
        limitations=[
            "No onset picks, tide subtraction, interpolation or ETA alignment.",
            "Provider IDs and filename codes do not validate historical deployments.",
            "Numeric sentinel conventions are unverified; finite numbers remain unchanged.",
            "Duplicate timestamps remain separate source rows; observation IDs may repeat.",
            "Intervals above nominal cadence can include timing jitter; "
            "only CO-OPS has missing-grid counts.",
            "Display coverage is an operational 36-hour/80-percent/60-minute rule, "
            "not a scientific validation gate.",
        ],
    )
    if header_evidence_configs:
        summary["header_evidence_configs"] = [str(p) for p in header_evidence_configs]
    seen: set[str] = set()
    groups: dict[tuple[Any, ...], list[tuple[dict[str, Any], list[dict[str, Any]]]]] = defaultdict(
        list
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".audit-waveforms-", dir=output.parent))
    try:
        for config, receipt_path in zip(configs, receipts, strict=True):
            header_only = config.resolve() in header_configs
            contracts = load_contracts(config)
            declared = tomllib.loads(config.read_text()).get("source_windows", {})
            if header_only and declared:
                raise ValueError("header evidence cannot declare waveform windows")
            if declared and set(declared) != {c.source_id for c in contracts}:
                raise ValueError("declared source window/contract IDs differ")
            if declared and selection is None:
                raise ValueError("declared source windows require frozen selection verification")
            outcomes = json.loads(receipt_path.read_text())
            by_id = {x["source_id"]: x for x in outcomes}
            if len(by_id) != len(outcomes) or set(by_id) != {c.source_id for c in contracts}:
                raise ValueError("receipt/contract identities differ")
            for contract in contracts:
                sid = contract.source_id
                if sid in seen:
                    raise ValueError("duplicate source across configs")
                seen.add(sid)
                receipt = by_id[sid]
                if receipt["local_path"] != str(contract.local_path):
                    raise ValueError("receipt path differs from contract")
                is_coops = (
                    contract.source_class == "coastal water-level observation"
                    and "CO-OPS" in contract.format
                )
                is_ntwc = "ntwc" in contract.format.lower() and "ascii" in contract.format.lower()
                if header_only and not is_ntwc:
                    raise ValueError("header evidence requires an NTWC ASCII source")
                diagnostic = contract.source_class == "provider availability response"
                entry: dict[str, Any] = dict(
                    source_id=sid,
                    acquisition_status=receipt["status"],
                    reason=receipt["reason"],
                    source_url=contract.url,
                    raw_path=str(contract.local_path),
                    purpose="diagnostic" if diagnostic else "event_window",
                    source_rows=0,
                )
                entries.append(entry)
                if not (is_coops or is_ntwc or diagnostic):
                    entry["purpose"] = "outside_observation_scope"
                    entry["processing_status"] = "outside_observation_scope"
                    continue
                eid = mapping.get(sid, contract.local_path.parent.name)
                if eid not in events or events[eid]["role"] != "development":
                    raise ValueError("source belongs to absent or reserved event")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", sid):
                    raise ValueError("unsafe output identifier")
                entry["event_id"] = eid
                window = event_window(parse_utc(events[eid]["usgs_time"]))
                if sid in declared:
                    spec = declared[sid]
                    purpose, offset = spec["purpose"], int(spec.get("offset_days", "0"))
                    if (
                        spec["event_id"] != eid
                        or purpose not in {"event_window", "quiet_control"}
                        or offset
                        not in ({0} if purpose == "event_window" else set(CONTROL_OFFSETS))
                    ):
                        raise ValueError("source window identity/purpose/offset mismatch")
                    window = (parse_utc(spec["start_utc"]), parse_utc(spec["stop_utc"]))
                    if window != event_window(
                        parse_utc(events[eid]["usgs_time"]), offset
                    ) or overlapping_events(*window, reserved):
                        raise ValueError(
                            "source window differs from frozen origin or overlaps reserved event"
                        )
                    if purpose == "quiet_control" and (
                        not catalog_origins
                        or window[0] < min(catalog_origins.values())
                        or window[1] > max(catalog_origins.values())
                        or overlapping_events(*window, catalog_origins)
                    ):
                        raise ValueError(
                            "control window lacks catalog coverage or overlaps a known earthquake"
                        )
                    entry["purpose"] = purpose
                entry.update(
                    window_start_utc=window[0].isoformat(), window_stop_utc=window[1].isoformat()
                )
                if header_only:
                    entry["purpose"] = "header_evidence"
                    entry.pop("window_start_utc")
                    entry.pop("window_stop_utc")
                path = root / contract.local_path
                if contract.expected_cdx_sha1:
                    verify_cdx_evidence(contract, root)
                    entry.update(
                        expected_cdx_sha1=contract.expected_cdx_sha1,
                        cdx_evidence_path=contract.cdx_evidence_path,
                        cdx_evidence_sha256=contract.cdx_evidence_sha256,
                    )
                sidecar = path.with_name(path.name + ".sha256")
                if not all(p.resolve().is_relative_to(root) for p in (path, sidecar)):
                    raise ValueError("source path escapes root")
                if receipt["status"] not in {"downloaded", "cached"}:
                    if path.exists():
                        raise ValueError("failed receipt has unexpected cached target")
                    entry["processing_status"] = "unavailable"
                    continue
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if (
                    digest != receipt["sha256"]
                    or digest != sidecar.read_text().strip()
                    or len(raw) != receipt["bytes"]
                ):
                    raise ValueError("source checksum or size mismatch")
                if not raw.lstrip().startswith(contract.expected_prefix.encode("utf-8")):
                    raise ValueError("source prefix mismatch")
                if contract.expected_cdx_sha1 and (
                    receipt.get("verified_cdx_sha1") != contract.expected_cdx_sha1
                    or base64.b32encode(hashlib.sha1(raw, usedforsecurity=False).digest()).decode()
                    != contract.expected_cdx_sha1
                ):
                    raise ValueError("pinned CDX body digest or verified receipt mismatch")
                entry.update(source_sha256=digest, source_bytes=len(raw))
                if header_only:
                    lines = raw.splitlines()
                    entry.update(
                        source_line_count=len(lines),
                        source_scope="historical_header_identity_only",
                    )
                    try:
                        header = parse_ntwc_header(
                            b"\n".join(lines[:4]).decode("utf-8"), contract.local_path.name
                        )
                    except (ValueError, UnicodeDecodeError) as exc:
                        entry.update(
                            processing_status="retained_unparsed_header_evidence",
                            parse_reason=str(exc),
                        )
                    else:
                        entry.update(
                            processing_status="verified_header_evidence", source_metadata=header
                        )
                    continue
                if diagnostic:
                    payload = json.loads(raw)
                    if "error" not in payload or "data" in payload:
                        raise ValueError("availability diagnostic is not an error response")
                    entry.update(processing_status="unavailable_diagnostic", provider_error=payload)
                    continue
                try:
                    rows, meta = _coops(contract, raw, window) if is_coops else _ntwc(contract, raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    if not (is_ntwc and retain_unparsed):
                        raise
                    entry.update(
                        processing_status="retained_unparsed_source",
                        source_line_count=len(raw.splitlines()),
                        parse_reason=str(exc),
                        timing_and_units="unresolved; raw bytes retained without inferred values",
                    )
                    if isinstance(exc, UnsupportedWaveformFormat):
                        entry.update(
                            unsupported_format_family=exc.family,
                            source_processing_level=exc.processing_level,
                        )
                    continue
                if meta.get("processing_status") == "unavailable_provider_response":
                    entry.update(meta)
                    continue
                if is_ntwc and sid in declared:
                    header_day = parse_utc(
                        str(meta["source_metadata"]["header_date"]) + "T00:00:00Z"
                    )
                    if not window[0] <= header_day < window[1]:
                        raise ValueError("NTWC header date outside declared source window")
                times = Counter(r["timestamp_utc"] for r in rows if r["timestamp_utc"] != "unknown")
                for number, row in enumerate(rows, 1):
                    row.update(
                        event_id=eid,
                        source_id=sid,
                        purpose=entry["purpose"],
                        source_row_number=number,
                        source_row_id=f"{eid}:{sid}:{number}",
                        station_key=meta["station_key"],
                        provider_station_id=meta["provider_station_id"],
                        sensor=meta["sensor"],
                        physical_site_id="unknown",
                        deployment_id="unknown",
                        units=meta["units"],
                        vertical_datum=meta["vertical_datum"],
                        duplicate_timestamp=times[row["timestamp_utc"]] > 1,
                    )
                    row["observation_id"] = (
                        f"{eid}:{meta['station_key']}:{meta['sensor']}:{row['timestamp_utc']}"
                    )
                ordered = sorted(datetime.fromisoformat(t) for t in times)
                deltas = Counter(
                    (b - a).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)
                )
                relative = Path(eid) / f"{sid}.csv.gz"
                _write(temporary / relative, rows)
                expected = meta.pop("expected_grid_timestamps")
                entry.update(
                    meta,
                    processing_status="normalized_source_samples",
                    source_rows=len(rows),
                    output_path=relative.as_posix(),
                    output_sha256=_sha(temporary / relative),
                    value_states=dict(Counter(r["value_state"] for r in rows)),
                    timestamp_states=dict(Counter(r["timestamp_state"] for r in rows)),
                    qc_states=dict(Counter(r["qc_state"] for r in rows)),
                    first_timestamp_utc=min(times, default="unknown"),
                    last_timestamp_utc=max(times, default="unknown"),
                    duplicate_timestamp_rows=sum(n for n in times.values() if n > 1),
                    duplicate_timestamp_excess=sum(n - 1 for n in times.values()),
                    observed_delta_seconds={str(k): v for k, v in sorted(deltas.items())},
                    gaps_over_declared_cadence=sum(
                        n for gap, n in deltas.items() if gap > meta["declared_cadence_seconds"]
                    )
                    if isinstance(meta["declared_cadence_seconds"], (int, float))
                    else "unknown",
                    missing_grid_timestamps=expected - len(times)
                    if isinstance(expected, int)
                    else "unknown",
                )
                if entry["purpose"] == "event_window" and isinstance(
                    meta["declared_cadence_seconds"], (int, float)
                ):
                    key = (
                        eid,
                        meta["station_key"],
                        meta["sensor"],
                        meta["declared_cadence_seconds"],
                        meta["units"],
                        meta["vertical_datum"],
                        meta["provider_station_id"],
                        meta["display_station_key"],
                    )
                    groups[key].append((entry, rows))
        entries.sort(key=lambda x: x["source_id"])
        summary["source_rows"] = sum(s["source_rows"] for s in entries)
        summary["series_coverage"] = _coverage(groups, events)
        (temporary / "manifest.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--receipts", type=Path, action="append", required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-map", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--known-catalog", type=Path)
    parser.add_argument("--retain-unparsed", action="store_true")
    parser.add_argument(
        "--header-evidence-config",
        type=Path,
        action="append",
        default=[],
        help="Paired config whose NTWC sources provide header evidence only, never samples.",
    )
    args = parser.parse_args(argv)
    result = build(
        args.config,
        args.receipts,
        args.events,
        args.root,
        args.output,
        source_map=args.source_map,
        selection=args.selection,
        known_catalog=args.known_catalog,
        retain_unparsed=args.retain_unparsed,
        header_evidence_configs=args.header_evidence_config,
    )
    print(json.dumps({"sources": len(result["sources"]), "source_rows": result["source_rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
