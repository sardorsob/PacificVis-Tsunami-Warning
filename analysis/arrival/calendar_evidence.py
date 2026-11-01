"""Document calendar components without silently repairing primary clocks."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from analysis.arrival.evidence import (
    Row,
    development_reports,
    file_manifest,
    read_rows,
    require_development,
    sha256,
    verify_inputs,
    verify_product,
    write_json,
    write_rows,
)
from analysis.arrival.lineage import stable_id


def documentary_clock(text: str) -> str:
    """Only a complete explicit English date and UTC clock proves this statement date."""
    match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2}) UTC", text)
    if not match:
        return "unknown"
    return datetime.strptime(match[1], "%B %d, %Y %H:%M").isoformat() + "Z"


def first_future_clock(origin: datetime, hour: int, minute: int) -> datetime:
    """A sensitivity hypothesis, explicitly unable to establish a primary date."""
    candidate = origin.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate + timedelta(days=1) if candidate < origin else candidate


def build_calendar_evidence(inputs: Path, lineage: Path, output: Path) -> Path:
    document = verify_inputs(inputs)
    verify_product(lineage, required_files=("statements.csv.gz",), inputs_sha256=sha256(inputs))
    if output.exists():
        raise ValueError("output already exists")
    root = Path(document["root"])
    reports = development_reports(document)
    ncei = read_rows(root / document["ncei"] / "observations.csv.gz")
    require_development(ncei, document["events"], "development_event_id")
    calendars: list[Row] = []
    forecasts: list[Row] = []
    backtests: list[Row] = []
    for row in reports:
        rid, event = row["report_id"], row["event_id"]
        for prefix, field in [("observed", "observed_utc"), ("estimated", "estimated_utc")]:
            utc = row[field] or "unknown"
            calendars.append(
                {
                    "calendar_evidence_id": stable_id("calendar", rid, field),
                    "source_record_id": rid,
                    "statement_id": "primary_source_cell",
                    "event_id": event,
                    "time_field": field,
                    "component": "full_timestamp",
                    "native_text": row["observed_raw" if prefix == "observed" else "estimated_raw"],
                    "documentary_utc": utc,
                    "calendar_tier": "accepted_baseline_evidence"
                    if utc != "unknown"
                    else "unresolved",
                    "precision_seconds": row["reported_precision_seconds"],
                    "evidence_sha256": row["source_sha256"],
                    "evidence_locator": rid,
                    "rule_version": row["time_rule_id"],
                    "primary_exact_write_allowed": "False",
                    "scope": "arrival",
                }
            )
        forecasts.append(
            {
                "forecast_instance_id": stable_id("forecast", rid, "estimate_cell"),
                "source_record_id": rid,
                "event_id": event,
                "product_id": row["source_id"],
                "product_instance_scope": "retained_archive_table_estimate_cell",
                "issue_utc": "unknown",
                "version": "unknown",
                "original_prediction_origin": "unknown",
                "time_basis": row["header_family"],
                "estimated_utc": row["estimated_utc"] or "unknown",
                "estimate_state": row["estimate_state"],
                "native_estimate_text": row["estimated_raw"],
                "evidence_sha256": row["source_sha256"],
                "available_before_arrival": "unknown",
                "source_instance_resolved": "False",
                "replacement_allowed": "False",
            }
        )
        if row["observed_utc"] and row["observed_state"] == "exact_reported_timestamp":
            origin = datetime.fromisoformat(
                document["events"][event]["usgs_time"].replace("Z", "+00:00")
            )
            observed = datetime.fromisoformat(row["observed_utc"].replace("Z", "+00:00"))
            candidate = first_future_clock(origin, observed.hour, observed.minute)
            backtests.append(
                {
                    "source_record_id": rid,
                    "event_id": event,
                    "site_record_id": row["site_record_id"],
                    "rule_version": "first_future_clock_sensitivity_v1",
                    "candidate_utc": candidate.isoformat(),
                    "baseline_documentary_utc": observed.isoformat(),
                    "contradiction": str(candidate != observed),
                    "day_error": str((candidate.date() - observed.date()).days),
                    "primary_exact_write_allowed": "False",
                    "source_calendar_rule": row["time_rule_id"],
                    "reference_origin": origin.isoformat(),
                    "origin_basis": "reviewed_USGS_not_original_forecast",
                }
            )
    for row in ncei:
        rid = row["source_record_id"]
        # Origin year/month are deliberately not used to fill arrival year/month.
        for component, native in [
            ("year", "unknown"),
            ("month", "unknown"),
            ("day", row["native_arrDay"]),
            ("hour", row["native_arrHour"]),
            ("minute", row["native_arrMin"]),
            ("second", "unknown"),
            ("timezone", "unknown"),
        ]:
            value = native if native not in {"", "not_provided"} else "unknown"
            calendars.append(
                {
                    "calendar_evidence_id": stable_id("calendar", rid, component),
                    "source_record_id": rid,
                    "statement_id": "primary_source_cell",
                    "event_id": row["development_event_id"],
                    "time_field": "initial_arrival",
                    "component": component,
                    "native_text": value,
                    "documentary_utc": "unknown",
                    "calendar_tier": "documentary_component"
                    if value != "unknown"
                    else "unresolved",
                    "precision_seconds": "60" if component in {"hour", "minute"} else "unknown",
                    "evidence_sha256": row["source_sha256"],
                    "evidence_locator": row["source_row_number"],
                    "rule_version": "native_component_only_v1",
                    "primary_exact_write_allowed": "False",
                    "scope": "arrival",
                }
            )
    for row in read_rows(lineage / "statements.csv.gz"):
        if row["provenance_scope"] != "arrival_statement":
            continue
        utc = documentary_clock(row["evidence_text"])
        calendars.append(
            {
                "calendar_evidence_id": stable_id("calendar", row["statement_id"], "full"),
                "source_record_id": row["source_record_id"],
                "statement_id": row["statement_id"],
                "event_id": row["event_id"],
                "time_field": "cited_arrival_statement",
                "component": "full_timestamp",
                "native_text": row["evidence_text"],
                "documentary_utc": utc,
                "calendar_tier": "documentary_statement"
                if utc != "unknown"
                else "partial_calendar_year_timezone_unresolved",
                "precision_seconds": "60",
                "evidence_sha256": row["evidence_sha256"],
                "evidence_locator": row["evidence_locator"],
                "rule_version": "explicit_full_date_UTC_v1",
                "primary_exact_write_allowed": "False",
                "scope": "arrival",
                "conflict_group": row["source_record_id"],
                "relation_to_primary_catalog_pick": "unknown",
            }
        )
    for name, rows in [
        ("calendar_evidence", calendars),
        ("forecast_instances", forecasts),
        ("calendar_backtest", backtests),
    ]:
        write_rows(output / (name + ".csv.gz"), rows)
    write_json(
        output / "summary.json",
        {
            "primary_timestamps_changed": 0,
            "calendar_tiers": dict(Counter(r["calendar_tier"] for r in calendars)),
            "backtest_records": len(backtests),
            "backtest_events": len({r["event_id"] for r in backtests}),
            "backtest_site_records": len({r["site_record_id"] for r in backtests}),
            "first_future_contradictions": sum(r["contradiction"] == "True" for r in backtests),
            "backtest_limitations": [
                "baseline-reported dates, not independently validated physical onset",
                "minute rounding and travel longer than24h cannot be identified by clock alone",
                "catalog-assisted rule untested: no independent full-date NCEI truth corpus",
                "no missingness mechanism identified; no universal date rule established",
            ],
            "forecast_instances": len(forecasts),
            "forecast_issue_times_known": 0,
        },
    )
    write_json(
        output / "forecast_leads.json",
        {
            "status": "deferred_by_scope",
            "url": "https://www.tsunami.gov/previous.events/01-13-07/0113forecast.html",
            "lead_only": True,
            "cached_verified_product": False,
            "reason": (
                "Dated product lead; issue/version/origin compatibility unresolved. "
                "Sitka ETA must not replace archive cell."
            ),
        },
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": "arrival_calendar_evidence_v1",
            "inputs_sha256": sha256(inputs),
            "lineage_sha256": sha256(lineage / "manifest.json"),
            "files": file_manifest(output),
        },
    )
    return output / "manifest.json"
