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
from pipeline.reported_time import EVIDENCE_RULES, parse_reported_time, time_rule_id

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

RECOVERY_SCHEMAS: dict[str, tuple[str, ...]] = {
    "reported_time_value": (
        "event_id", "report_id", "field_role", "source_id", "source_sha256",
        "raw_value", "state", "hour", "minute", "day_of_year", "timestamp_utc",
        "parsed_timestamp_utc", "rule_id", "evidence_id", "qualifier", "footnote",
    ),
    "target_eligibility": (
        "event_id", "report_id", "target_id", "target_version", "eligible",
        "reason_codes", "physical_site_id", "origin_basis", "model_eligible",
    ),
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


def _time_evidence(
    path: Path | None, pages: dict[str, dict[str, Any]],
    tables: dict[tuple[str, int], dict[str, Any]], development: set[str],
) -> dict[tuple[str, int], dict[str, Any]]:
    result: dict[tuple[str, int], dict[str, Any]] = {}
    required = {
        "event_id", "source_id", "source_sha256", "source_path", "table_index",
        "header_family", "rule_ids", "evidence_id", "review_status", "reviewer", "scope",
    }
    for row in _records(path) if path else []:
        if not required.issubset(row) or any(not str(row[k]).strip() for k in required):
            raise CorpusError("time evidence requires scoped source and review fields")
        eid = row["event_id"]
        key = (eid, int(row["table_index"]))
        if eid not in development or key not in tables or key in result:
            raise CorpusError("time evidence has reserved/unknown/duplicate source scope")
        page, table = pages[eid], tables[key]
        if (
            row["source_id"] != page["source_id"]
            or row["source_sha256"] != page["sha256"]
            or row["header_family"] != table["header_family"]
            or row["review_status"] != "independently_reviewed"
        ):
            raise CorpusError("time evidence source identity, header or review mismatch")
        source = Path(row["source_path"])
        root = Path.cwd().resolve()
        if source.is_absolute() or not (root / source).resolve().is_relative_to(root):
            raise CorpusError("time evidence source path must remain inside project root")
        if hashlib.sha256((root / source).read_bytes()).hexdigest() != page["sha256"]:
            raise CorpusError("time evidence raw source checksum mismatch")
        rules = json.loads(row["rule_ids"])
        if not isinstance(rules, list) or any(
            not isinstance(rule, str) or rule not in EVIDENCE_RULES
            for rule in cast(list[Any], rules)
        ):
            raise CorpusError("unknown time evidence rule")
        result[key] = {**row, "rule_ids": rules}
    return result



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
    time_evidence: Path | None = None,
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
    reviewed_times = _time_evidence(time_evidence, pages, tables, development)
    schemas = {**CORPUS_SCHEMAS, **RECOVERY_SCHEMAS} if time_evidence else CORPUS_SCHEMAS
    records: dict[str, dict[str, list[dict[str, Any]]]] = {
        eid: {name: [] for name in schemas} for eid in sorted(development)
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
        evidence = reviewed_times.get((eid, row["table_index"]), {}) if time_evidence else None
        estimated = parse_reported_time(estimated_raw, family, context, evidence=evidence)
        observed = parse_reported_time(observed_raw, family, context, evidence=evidence)
        effective_rule = time_rule_id(family) if time_evidence is None else "+".join(
            sorted({str(estimated["rule_id"]), str(observed["rule_id"])})
        )
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
                "time_rule_id": effective_rule,
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
        if time_evidence:
            for field, raw, value in (
                ("estimated", estimated_raw, estimated), ("observed", observed_raw, observed),
            ):
                target["reported_time_value"].append({
                    "event_id": eid, "report_id": report_id, "field_role": field,
                    "source_id": row["source_id"], "source_sha256": pages[eid]["sha256"],
                    "raw_value": raw,
                    **{k: value.get(k, "unknown") for k in (
                        "state", "hour", "minute", "day_of_year", "timestamp_utc",
                        "parsed_timestamp_utc", "rule_id", "evidence_id", "qualifier", "footnote",
                    )},
                })
            for target_id in ("T-OBS", "T-CAL"):
                why: list[str] = []
                if structural != "accepted_source_row" or table["status"] != "recognized":
                    why.append("structural_or_header_unresolved")
                if observed["state"] != "exact_reported_timestamp":
                    why.append("observed:" + observed["state"])
                if not fit_identity:
                    why.append("geographic_identity_unreviewed")
                if events[eid].get("attribution_status") != "single_source_metadata":
                    why.append("event_attribution_unresolved")
                if target_id == "T-OBS":
                    if context is None:
                        why.append("reference_origin_unreviewed")
                    elif observed["state"] == "exact_reported_timestamp" and (
                        _utc(observed["timestamp_utc"]) - context["origin"]
                    ).total_seconds() <= 0:
                        why.append("observed:nonpositive_elapsed")
                elif estimated["state"] != "exact_reported_timestamp":
                    why.append("estimate:" + estimated["state"])
                target["target_eligibility"].append({
                    "event_id": eid, "report_id": report_id, "target_id": target_id,
                    "target_version": (
                        "reported_duration_from_reviewed_reference_v1" if target_id == "T-OBS"
                        else "reported_absolute_difference_v1"
                    ),
                    "eligible": not why, "reason_codes": _json(why),
                    "physical_site_id": identity["physical_site_id"],
                    "origin_basis": context["origin_basis"] if context else "unknown",
                    "model_eligible": False,
                })
        if exact and context is not None:
            target["pair"].append(
                {
                    "event_id": eid,
                    "report_id": report_id,
                    "site_record_id": site_ref,
                    "source_id": row["source_id"],
                    "source_sha256": pages[eid]["sha256"],
                    "time_rule_id": effective_rule,
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
    if time_evidence:
        inputs["time_evidence"] = time_evidence
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
    if time_evidence:
        summary.update(
            schema_version="reported-arrival-corpus-v2",
            exact_observed_values=sum(
                r["field_role"] == "observed" and r["state"] == "exact_reported_timestamp"
                for d in records.values() for r in d["reported_time_value"]
            ),
            target_eligible={
                target_id: sum(r["eligible"] and r["target_id"] == target_id
                               for d in records.values() for r in d["target_eligibility"])
                for target_id in ("T-OBS", "T-CAL")
            },
            time_evidence_records=len(reviewed_times),
        )
        summary["interpretation"] = [
            "Source-supported reported timestamps are not independently validated physical onsets.",
            "T-OBS uses a named reviewed origin reference, not the unknown historical "
            "model origin.",
            "T-CAL eligibility concerns absolute clock differences; log-duration calibration "
            "requires a separate origin/product contract.",
            "Minute precision does not establish a rounding or picking uncertainty model.",
            "Qualified values retain parsed components; primary UTC remains withheld.",
            "Bare clock dates are never inferred from forecasts, distance or waveform onset.",
            "Geographic identity does not establish deployment continuity or model eligibility.",
        ]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        hashes: dict[str, str] = {}
        for eid, data in records.items():
            (temporary / eid).mkdir()
            for name, columns in schemas.items():
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
