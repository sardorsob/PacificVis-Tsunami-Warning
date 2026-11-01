"""Build a development-only corpus of reported arrivals, never physical onset labels.

The optional time-context CSV is a separate reviewed contract, not a modification
of frozen event selection. Its columns are event_id, calendar_year,
calendar_year_provenance, origin_utc, origin_basis and origin_provenance. Without
it, exact clock/day components survive but absolute timestamps stay unreleased.
The optional crosswalk has event_id, report_id, identity_tier, physical_site_id,
deployment_id and evidence. Neither a source label nor an exact clock establishes
a physical site, a validated arrival, or Stage-D eligibility.
"""

from __future__ import annotations

import calendar
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import tomllib
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from analysis.arrival.stations import StationError, validate_reviewed_site_evidence
from pipeline.ntwc_archive import arrival_value_flags

CORPUS_SCHEMAS: dict[str, tuple[str, ...]] = {
    "event": (
        "event_id",
        "name",
        "region",
        "role",
        "usgs_origin_raw",
        "magnitude_raw",
        "magnitude_type",
        "archive_source_id",
        "archive_url",
        "archive_sha256",
        "calendar_year",
        "calendar_year_provenance",
        "elapsed_origin_utc",
        "elapsed_origin_basis",
        "elapsed_origin_provenance",
        "stage_d_status",
    ),
    "site": (
        "event_id",
        "site_record_id",
        "report_id",
        "source_label",
        "physical_site_id",
        "deployment_id",
        "identity_tier",
        "identity_scope",
        "identity_basis",
        "event_site_identity_verified",
        "deployment_continuity_verified",
        "review_status",
        "identity_evidence",
        "fit_tier_identity",
    ),
    "name_crosswalk": (
        "event_id",
        "report_id",
        "source_label",
        "site_record_id",
        "physical_site_id",
        "deployment_id",
        "identity_tier",
        "identity_scope",
        "identity_basis",
        "event_site_identity_verified",
        "deployment_continuity_verified",
        "review_status",
        "evidence",
    ),
    "arrival_report": (
        "event_id",
        "report_id",
        "table_index",
        "row_index",
        "source_id",
        "source_sha256",
        "structural_status",
        "header_family",
        "time_rule_id",
        "source_label",
        "site_record_id",
        "estimated_raw",
        "observed_raw",
        "legacy_arrival_raw",
        "legacy_eta_raw",
        "estimate_state",
        "observed_state",
        "estimate_hour",
        "estimate_minute",
        "estimate_day_of_year",
        "observed_hour",
        "observed_minute",
        "observed_day_of_year",
        "estimated_utc",
        "observed_utc",
        "reported_precision_seconds",
        "disposition",
        "reason_codes",
        "raw_row_json",
    ),
    "pair": (
        "event_id",
        "report_id",
        "site_record_id",
        "source_id",
        "source_sha256",
        "time_rule_id",
        "estimated_utc",
        "observed_utc",
        "origin_utc",
        "origin_basis",
        "origin_provenance",
        "estimated_elapsed_seconds",
        "observed_elapsed_seconds",
        "physical_site_id",
        "deployment_id",
        "identity_tier",
        "identity_scope",
        "identity_basis",
        "event_site_identity_verified",
        "deployment_continuity_verified",
        "review_status",
        "fit_tier_identity",
        "reported_precision_seconds",
        "model_eligible",
        "physical_onset_validated",
    ),
    "rejected_record": (
        "event_id",
        "report_id",
        "structural_status",
        "reason_codes",
        "raw_row_json",
    ),
}
TIME_CONTEXT_COLUMNS = {
    "event_id",
    "calendar_year",
    "calendar_year_provenance",
    "origin_utc",
    "origin_basis",
    "origin_provenance",
}
CROSSWALK_COLUMNS = {
    "event_id",
    "report_id",
    "identity_tier",
    "physical_site_id",
    "deployment_id",
    "evidence",
}
IDENTITY_TIERS = {
    "header_exact",
    "registry_exact",
    "archive_code",
    "name_only",
    "ambiguous",
    "unmatched",
}


class CorpusError(ValueError):
    """Inputs cannot be reconciled under the corpus's source and role contracts."""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as stream:
            records = cast(list[dict[str, Any]], list(csv.DictReader(stream)))
        for row in records:
            for key in ("fields", "cells", "cell_states"):
                if key in row:
                    row[key] = json.loads(row[key])
            for key in ("table_index", "row_index"):
                if key in row:
                    row[key] = int(row[key])
        return records
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(
        not isinstance(row, dict) for row in cast(list[Any], records)
    ):
        raise CorpusError(f"expected a JSON record list: {path}")
    return cast(list[dict[str, Any]], records)


def _utc(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value):
        raise CorpusError("reviewed origin must be a full datetime explicitly declaring UTC")
    try:
        origin = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CorpusError("invalid reviewed origin") from error
    if origin.tzinfo is None or origin.utcoffset() != timedelta(0):
        raise CorpusError("reviewed origin must be timezone-aware UTC")
    return origin.astimezone(UTC)


def _time_contexts(path: Path | None, development: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _records(path) if path else []:
        if not TIME_CONTEXT_COLUMNS.issubset(row) or any(
            not str(row[key]).strip() or str(row[key]).strip().lower() == "unknown"
            for key in TIME_CONTEXT_COLUMNS
        ):
            raise CorpusError("time context requires reviewed year/origin and their provenance")
        eid = row["event_id"]
        if eid not in development or eid in result:
            raise CorpusError("time context has reserved, absent or duplicate event ID")
        year = int(row["calendar_year"])
        if not 1 <= year <= 9999:
            raise CorpusError("invalid source calendar year")
        origin = _utc(row["origin_utc"])
        if year != origin.year:
            raise CorpusError("source calendar year must match origin year; rollover is unreviewed")
        result[eid] = {**row, "calendar_year": year, "origin": origin}
    return result


def time_rule_id(header_family: str) -> str:
    if re.fullmatch(r"(?:estimated|computed)_observed_(?:utc|gmt)_jday", header_family):
        return "reported_hhmm_explicit_doy_v1"
    if re.fullmatch(r"(?:estimated|computed)_observed_(?:utc|gmt)", header_family):
        return "reported_clock_date_unresolved_v1"
    if header_family.startswith("arrival_eta_"):
        return "legacy_arrival_semantics_unresolved_v1"
    return "unknown_header_rule"


def parse_reported_time(
    raw: str,
    header_family: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve exact components; never infer a missing date or erase qualifiers."""
    result: dict[str, Any] = {
        "state": "unknown_format",
        "hour": "unknown",
        "minute": "unknown",
        "day_of_year": "unknown",
        "timestamp_utc": "unknown",
    }
    if not raw.strip():
        return {**result, "state": "blank"}
    if not arrival_value_flags({"observed_arrival": raw})["observed_value"]:
        return {**result, "state": "source_missing_token"}
    text = " ".join(raw.replace("\xa0", " ").split())
    rule = time_rule_id(header_family)
    if rule == "legacy_arrival_semantics_unresolved_v1":
        return {**result, "state": "legacy_semantics_unverified"}
    if rule == "unknown_header_rule":
        return {**result, "state": "unknown_time_rule"}
    if "?" in text or "~" in text or re.search(r"\bapprox", text, re.IGNORECASE):
        return {**result, "state": "qualified_value"}
    match = re.fullmatch(
        r"(?:(\d{2})(\d{2})|(\d{1,2}):(\d{2}))"
        r"(?:\s*\((?:JD\s*)?(\d{1,3})\))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return result
    hour, minute = int(match[1] or match[3]), int(match[2] or match[4])
    result.update(hour=hour, minute=minute)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return {**result, "state": "invalid_clock"}
    if match[5] is None:
        return {**result, "state": "date_ambiguous"}
    day = int(match[5])
    result["day_of_year"] = day
    if not 1 <= day <= 366:
        return {**result, "state": "invalid_day_of_year"}
    if rule != "reported_hhmm_explicit_doy_v1":
        return {**result, "state": "day_semantics_unverified"}
    if context is None:
        return {**result, "state": "calendar_context_missing"}
    year = int(context["calendar_year"])
    if day == 366 and not calendar.isleap(year):
        return {**result, "state": "invalid_day_of_year"}
    stamp = datetime(year, 1, 1, hour, minute, tzinfo=UTC) + timedelta(days=day - 1)
    origin = cast(datetime, context["origin"])
    if (origin.month, stamp.month) in {(12, 1), (1, 12)}:
        return {**result, "state": "year_boundary_review_required"}
    return {
        **result,
        "state": "exact_reported_timestamp",
        "timestamp_utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _crosswalk(
    path: Path | None,
    development: set[str],
    report_ids: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _records(path) if path else []:
        if not CROSSWALK_COLUMNS.issubset(row):
            raise CorpusError(
                "crosswalk requires report identity, site/deployment, tier and evidence"
            )
        report_id = row["report_id"]
        if (
            row["event_id"] not in development
            or report_id not in report_ids
            or not report_id.startswith(row["event_id"] + ":")
            or report_id in result
        ):
            raise CorpusError("crosswalk has reserved, absent or duplicate report identity")
        if row["identity_tier"] not in IDENTITY_TIERS:
            raise CorpusError("unknown crosswalk identity tier")
        if row.get("review_status") == "independently_reviewed":
            try:
                validate_reviewed_site_evidence(row)
            except StationError as exc:
                raise CorpusError(
                    "reviewed site fields differ from digest-bound evidence: " + str(exc)
                ) from exc
        result[report_id] = row
    return result


def _gzip_csv(path: Path, columns: tuple[str, ...], records: list[dict[str, Any]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                for record in records:
                    writer.writerow({key: record.get(key, "unknown") for key in columns})


def build_corpus(
    config: Path,
    census_dir: Path,
    output: Path,
    *,
    rows_path: Path | None = None,
    time_context: Path | None = None,
    crosswalk: Path | None = None,
) -> dict[str, Any]:
    """Build immutable per-event tables with complete source-row accounting."""
    if output.exists():
        raise FileExistsError(f"refusing to replace corpus: {output}")
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    configured = cast(dict[str, dict[str, Any]], document.get("events", {}))
    events = {event["event_id"]: event for event in configured.values()}
    if (
        not events
        or len(events) != len(configured)
        or any(not re.fullmatch(r"[A-Za-z0-9_-]+", eid) for eid in events)
    ):
        raise CorpusError("event IDs must be unique, nonempty and safe path components")
    if any(
        event.get("role") not in {"development", "sealed_evaluation"} for event in events.values()
    ):
        raise CorpusError("unsupported event role")
    development = {eid for eid, event in events.items() if event["role"] == "development"}
    census_path = census_dir / "census.json"
    census = _records(census_path)
    if len(census) != len(events) or {row["event_id"] for row in census} != set(events):
        raise CorpusError("census/config event sets differ")
    pages = {page["event_id"]: page for page in census}
    actual_rows_path = rows_path or census_dir / "rows.json"
    rows = _records(actual_rows_path)
    reports: dict[str, dict[str, Any]] = {}
    tables: dict[tuple[str, int], dict[str, Any]] = {}
    for page in census:
        eid = page["event_id"]
        if (
            page["role"] != events[eid]["role"]
            or page["source_id"] != events[eid]["archive_source_id"]
        ):
            raise CorpusError("census source identity or role mismatch")
        if eid in development:
            if not re.fullmatch(r"[0-9a-f]{64}", page["sha256"]):
                raise CorpusError("missing source checksum")
            for table in page["arrival_tables"]:
                key = (eid, table["table_index"])
                if key in tables:
                    raise CorpusError("duplicate source table")
                tables[key] = table
    row_counts: Counter[tuple[str, int]] = Counter()
    for row in rows:
        eid = row["event_id"]
        if eid not in development or row["role"] != "development":
            raise CorpusError("reserved or unknown event rows are forbidden")
        if row["source_id"] != events[eid]["archive_source_id"]:
            raise CorpusError("row source identity mismatch")
        table_key = (eid, row["table_index"])
        if table_key not in tables:
            raise CorpusError("row has no source table")
        table = tables[table_key]
        if (
            not isinstance(row["row_index"], int)
            or not table["header_row_index"] < row["row_index"] < table["source_rows"]
        ):
            raise CorpusError("row index is outside its source table")
        report_id = f"{eid}:{row['table_index']}:{row['row_index']}"
        if report_id in reports:
            raise CorpusError("duplicate report ID")
        reports[report_id] = row
        row_counts[table_key] += 1
    if any(row_counts[key] != table["rows_after_header"] for key, table in tables.items()):
        raise CorpusError("source row accounting mismatch")
    contexts = _time_contexts(time_context, development)
    matches = _crosswalk(crosswalk, development, set(reports))
    records: dict[str, dict[str, list[dict[str, Any]]]] = {
        eid: {name: [] for name in CORPUS_SCHEMAS} for eid in sorted(development)
    }
    for eid in sorted(development):
        event, page, context = events[eid], pages[eid], contexts.get(eid, {})
        records[eid]["event"].append(
            {
                "event_id": eid,
                "name": event.get("name", "unknown"),
                "region": event.get("region", "unknown"),
                "role": "development",
                "usgs_origin_raw": event.get("usgs_time", "unknown"),
                "magnitude_raw": event.get("usgs_mag", "unknown"),
                "magnitude_type": event.get("usgs_magType", "unknown"),
                "archive_source_id": page["source_id"],
                "archive_url": page["archive_url"],
                "archive_sha256": page["sha256"],
                "calendar_year": context.get("calendar_year", "unknown"),
                "calendar_year_provenance": context.get("calendar_year_provenance", "unknown"),
                "elapsed_origin_utc": context.get("origin_utc", "unknown"),
                "elapsed_origin_basis": context.get("origin_basis", "unknown"),
                "elapsed_origin_provenance": context.get("origin_provenance", "unknown"),
                "stage_d_status": "not_assessed",
            }
        )
    reasons: Counter[str] = Counter()
    for report_id, row in sorted(
        reports.items(),
        key=lambda item: (item[1]["event_id"], item[1]["table_index"], item[1]["row_index"]),
    ):
        eid = row["event_id"]
        target = records[eid]
        context = contexts.get(eid)
        table = tables[eid, row["table_index"]]
        family = table["header_family"]
        fields = cast(dict[str, str], row["fields"])
        structural = row["status"]
        label = fields.get("location", "")
        match = matches.get(report_id, {})
        identity = {
            key: match.get(key, "unknown")
            for key in (
                "physical_site_id",
                "deployment_id",
                "identity_tier",
                "identity_scope",
                "identity_basis",
            )
        }
        fit_identity = (
            identity["identity_tier"] in {"header_exact", "registry_exact"}
            and match.get("review_status") == "independently_reviewed"
            and str(match.get("event_site_identity_verified", "false")).lower() == "true"
        )
        identity.update(
            event_site_identity_verified=fit_identity,
            # This reviewed adapter validates event-site identity only.
            deployment_continuity_verified=False,
            review_status=match.get("review_status", "unreviewed"),
        )
        site_ref = report_id + ":site" if label.strip() else "unknown"
        if site_ref != "unknown":
            target["site"].append(
                {
                    "event_id": eid,
                    "site_record_id": site_ref,
                    "report_id": report_id,
                    "source_label": label,
                    **identity,
                    "identity_evidence": match.get("evidence", "unknown"),
                    "fit_tier_identity": fit_identity,
                }
            )
            target["name_crosswalk"].append(
                {
                    "event_id": eid,
                    "report_id": report_id,
                    "source_label": label,
                    "site_record_id": site_ref,
                    **identity,
                    "evidence": match.get("evidence", "unknown"),
                }
            )
        estimated_raw = fields.get("estimated_arrival", fields.get("eta_as_labeled", ""))
        observed_raw = fields.get("observed_arrival", fields.get("arrival_as_labeled", ""))
        estimated = parse_reported_time(estimated_raw, family, context)
        observed = parse_reported_time(observed_raw, family, context)
        rejected: list[str] = []
        if structural != "accepted_source_row":
            rejected.append("structural:" + structural)
        if table["status"] != "recognized":
            rejected.append("unknown_header_family")
        for name, value in (("estimate", estimated), ("observed", observed)):
            if value["state"] != "exact_reported_timestamp":
                rejected.append(name + ":" + value["state"])
        elapsed: dict[str, float] = {}
        if not rejected and context is not None:
            for name, value in (("estimated", estimated), ("observed", observed)):
                elapsed[name] = (_utc(value["timestamp_utc"]) - context["origin"]).total_seconds()
                if elapsed[name] <= 0:
                    rejected.append(name + ":nonpositive_elapsed")
        raw_row = _json(row)
        reason_codes = _json(rejected)
        exact = not rejected
        target["arrival_report"].append(
            {
                "event_id": eid,
                "report_id": report_id,
                "table_index": row["table_index"],
                "row_index": row["row_index"],
                "source_id": row["source_id"],
                "source_sha256": pages[eid]["sha256"],
                "structural_status": structural,
                "header_family": family,
                "time_rule_id": time_rule_id(family),
                "source_label": label,
                "site_record_id": site_ref,
                "estimated_raw": fields.get("estimated_arrival", ""),
                "observed_raw": fields.get("observed_arrival", ""),
                "legacy_arrival_raw": fields.get("arrival_as_labeled", ""),
                "legacy_eta_raw": fields.get("eta_as_labeled", ""),
                "estimate_state": estimated["state"],
                "observed_state": observed["state"],
                **{
                    f"{name}_{component}": value[component]
                    for name, value in (("estimate", estimated), ("observed", observed))
                    for component in ("hour", "minute", "day_of_year")
                },
                "estimated_utc": estimated["timestamp_utc"],
                "observed_utc": observed["timestamp_utc"],
                "reported_precision_seconds": 60 if exact else "unknown",
                "disposition": "exact_reported_pair" if exact else "rejected_or_uncertain",
                "reason_codes": reason_codes,
                "raw_row_json": raw_row,
            }
        )
        if exact and context is not None:
            target["pair"].append(
                {
                    "event_id": eid,
                    "report_id": report_id,
                    "site_record_id": site_ref,
                    "source_id": row["source_id"],
                    "source_sha256": pages[eid]["sha256"],
                    "time_rule_id": time_rule_id(family),
                    "estimated_utc": estimated["timestamp_utc"],
                    "observed_utc": observed["timestamp_utc"],
                    "origin_utc": context["origin_utc"],
                    "origin_basis": context["origin_basis"],
                    "origin_provenance": context["origin_provenance"],
                    "estimated_elapsed_seconds": elapsed["estimated"],
                    "observed_elapsed_seconds": elapsed["observed"],
                    **identity,
                    "fit_tier_identity": fit_identity,
                    "reported_precision_seconds": 60,
                    "model_eligible": False,
                    "physical_onset_validated": False,
                }
            )
        else:
            target["rejected_record"].append(
                {
                    "event_id": eid,
                    "report_id": report_id,
                    "structural_status": structural,
                    "reason_codes": reason_codes,
                    "raw_row_json": raw_row,
                }
            )
            reasons.update(rejected)
    accounting: dict[str, dict[str, Any]] = {
        eid: {
            "source_rows": len(data["arrival_report"]),
            "exact_pairs": len(data["pair"]),
            "rejected_or_uncertain": len(data["rejected_record"]),
            "stage_d_status": "not_assessed",
        }
        for eid, data in records.items()
    }
    for counts in accounting.values():
        if counts["source_rows"] != counts["exact_pairs"] + counts["rejected_or_uncertain"]:
            raise CorpusError("output accounting mismatch")
    inputs = {"config": config, "census": census_path, "rows": actual_rows_path}
    if time_context:
        inputs["time_context"] = time_context
    if crosswalk:
        inputs["crosswalk"] = crosswalk
    summary: dict[str, Any] = {
        "schema_version": "reported-arrival-corpus-v1",
        "lane": "paper",
        "development_events": len(development),
        "reserved_events_excluded": len(events) - len(development),
        "source_rows": len(rows),
        "exact_pairs": sum(len(d["pair"]) for d in records.values()),
        "rejected_or_uncertain": sum(len(d["rejected_record"]) for d in records.values()),
        "events": accounting,
        "reason_counts": dict(sorted(reasons.items())),
        "input_sha256": {
            key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in inputs.items()
        },
        "interpretation": [
            "Exact pairs refer to unqualified published clocks, not physical onsets "
            "or precise arrival instants.",
            "Minute display precision does not establish a rounding convention "
            "or observation likelihood.",
            "No date rollover is inferred; source calendar year and origin require "
            "a separate reviewed context.",
            "Legacy Arrival/ETA, qualified values and structural failures remain "
            "outside numeric pairs.",
            "Site identities and Stage-D/model eligibility are never inferred "
            "from source labels or pair counts.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        hashes: dict[str, str] = {}
        for eid, data in records.items():
            (temporary / eid).mkdir()
            for name, columns in CORPUS_SCHEMAS.items():
                path = temporary / eid / f"{name}.csv.gz"
                _gzip_csv(path, columns, data[name])
                hashes[f"{eid}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
        summary["output_sha256"] = hashes
        (temporary / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise FileExistsError(f"refusing to replace corpus: {output}")
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary
