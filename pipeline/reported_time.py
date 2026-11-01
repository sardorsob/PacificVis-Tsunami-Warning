"""Pure source-clock interpretation with independently reviewed calendar evidence.

The default preserves corpus-v4 exactly; optional evidence enables named rules.
"""
from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pipeline.ntwc_archive import arrival_value_flags

EVIDENCE_RULES = frozenset({
    "inline_month_day_v1", "legacy_definition_v1", "source_doy_semantics_v1",
    "footnote_asterisk_v1", "footnote_trailing_dash_v1",
})

def time_rule_id(header_family: str) -> str:
    if re.fullmatch(r"(?:estimated|computed)_observed_(?:utc|gmt)_jday", header_family):
        return "reported_hhmm_explicit_doy_v1"
    if re.fullmatch(r"(?:estimated|computed)_observed_(?:utc|gmt)", header_family):
        return "reported_clock_date_unresolved_v1"
    if header_family.startswith("arrival_eta_"):
        return "legacy_arrival_semantics_unresolved_v1"
    return "unknown_header_rule"


def _parse_original(
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


def _inline_date(
    text: str, context: dict[str, Any] | None, evidence: Mapping[str, Any],
) -> dict[str, Any] | None:
    clock = r"(?:\d{4}|\d{1,2}:\d{2})"
    date = r"\d{1,2}[-/]\d{1,2}(?:[-/](?:\d{4}|\d{2}))?"
    match = re.fullmatch(rf"(?P<clock>{clock})\s+(?P<date>{date})", text)
    if match is None:
        match = re.fullmatch(rf"(?P<date>{date})\s+(?P<clock>{clock})", text)
    if match is None:
        return None
    value = match["clock"].replace(":", "").zfill(4)
    hour, minute = int(value[:-2]), int(value[-2:])
    parts = re.split(r"[-/]", match["date"])
    month, day = int(parts[0]), int(parts[1])
    result: dict[str, Any] = {
        "state": "calendar_context_missing", "hour": hour, "minute": minute,
        "day_of_year": "unknown", "month": month, "day": day,
        "timestamp_utc": "unknown", "rule_id": "inline_month_day_v1",
    }
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return {**result, "state": "invalid_clock"}
    if context is None:
        return result
    year = int(context["calendar_year"])
    origin = cast(datetime, context["origin"])
    boundary = (origin.month, month) in {(12, 1), (1, 12)}
    if len(parts) == 3:
        literal = int(parts[2])
        candidates = [year]
        if boundary:
            candidates.append(year + (1 if origin.month == 12 else -1))
        years = [
            y for y in candidates if y == literal or (len(parts[2]) == 2 and y % 100 == literal)
        ]
        if len(years) != 1:
            return {**result, "state": "calendar_year_conflict"}
        year = years[0]
    elif boundary:
        reviewed = evidence.get("rollover_year")
        if reviewed != year + (1 if origin.month == 12 else -1):
            return {**result, "state": "year_boundary_review_required"}
        year = int(cast(int, reviewed))
    try:
        stamp = datetime(year, month, day, hour, minute, tzinfo=UTC)
    except ValueError:
        return {**result, "state": "invalid_calendar_date"}
    return {
        **result, "state": "exact_reported_timestamp", "year": year,
        "day_of_year": stamp.timetuple().tm_yday,
        "timestamp_utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def parse_reported_time(
    raw: str, header_family: str, context: dict[str, Any] | None = None,
    *, evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Interpret source-supported dates; no distance or forecast determines a date."""
    if evidence is None:
        return _parse_original(raw, header_family, context)
    rules = set(cast(list[str], evidence.get("rule_ids", [])))
    if evidence and (
        evidence.get("review_status") != "independently_reviewed"
        or not evidence.get("evidence_id")
    ):
        raise ValueError("time evidence requires independent review and an evidence ID")
    if not rules.issubset(EVIDENCE_RULES):
        raise ValueError("unknown reported-time evidence rule")
    text = " ".join(raw.replace("\xa0", " ").split())
    result = {
        **_parse_original(raw, header_family, context),
        "rule_id": time_rule_id(header_family),
        "evidence_id": evidence.get("evidence_id", "unknown"),
        "parsed_timestamp_utc": "unknown", "qualifier": "", "footnote": "",
    }
    if not text:
        return result
    if text.casefold() == "no eta" or not arrival_value_flags({"observed_arrival": raw})[
        "observed_value"
    ]:
        return {**result, "state": "source_absent_explicit", "rule_id": "explicit_absent_v1"}
    family = header_family
    if header_family.startswith("arrival_eta_"):
        if "legacy_definition_v1" not in rules:
            return result
        family = "computed_observed_" + header_family.removeprefix("arrival_eta_")
    if time_rule_id(family) == "unknown_header_rule":
        return result
    qualifiers = re.findall(r"\bapprox(?:imately)?\.?|\(\?\)|[?~≈]", text, re.IGNORECASE)
    clean = re.sub(r"\bapprox(?:imately)?\.?|\(\?\)|[?~≈]", "", text, flags=re.IGNORECASE).strip()
    footnote = re.search(r"([*-])\s*$", clean)
    marker = footnote[1] if footnote else ""
    if footnote:
        clean = clean[:footnote.start()].strip()
    result.update(qualifier=" ".join(qualifiers), footnote=marker)
    inline = _inline_date(clean, context, evidence) if "inline_month_day_v1" in rules else None
    if inline is not None:
        result.update(inline)
    else:
        parsed_family = family
        if "source_doy_semantics_v1" in rules and not family.endswith("_jday"):
            parsed_family += "_jday"
        result.update(_parse_original(clean, parsed_family, context))
        result["rule_id"] = (
            "source_doy_semantics_v1" if parsed_family != family else time_rule_id(family)
        )
    result["parsed_timestamp_utc"] = result["timestamp_utc"]
    footnote_rule = "footnote_asterisk_v1" if marker == "*" else "footnote_trailing_dash_v1"
    if qualifiers or (marker and footnote_rule not in rules):
        result.update(
            state="qualified_value" if qualifiers else "footnoted_value",
            timestamp_utc="unknown",
            rule_id="qualifier_v1" if qualifiers else "footnote_unreviewed_v1",
        )
    if header_family.startswith("arrival_eta_") and result["state"] == "exact_reported_timestamp":
        result["rule_id"] = "legacy_definition_v1+" + str(result["rule_id"])
    return result

