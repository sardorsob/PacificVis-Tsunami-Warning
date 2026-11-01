"""Recover explicit dates while preserving qualifiers, missingness and source authority."""

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.reported_time import parse_reported_time


def context(year: int = 2007, month: int = 1, day: int = 13) -> dict[str, Any]:
    return {"calendar_year": year, "origin": datetime(year, month, day, tzinfo=UTC)}


def review(*rules: str, **extra: Any) -> dict[str, Any]:
    return {"rule_ids": list(rules), "review_status": "independently_reviewed",
            "evidence_id": "source-a:table-0", **extra}


@pytest.mark.parametrize("raw", ["0007 1/14", "0007 1-14", "1/14 0007", "0007 1-14-07"])
def test_inline_dates_require_review_and_retain_evidence(raw: str) -> None:
    parsed = parse_reported_time(raw, "computed_observed_utc", context(),
                                 evidence=review("inline_month_day_v1"))
    assert parsed["timestamp_utc"] == "2007-01-14T00:07:00Z"
    assert parsed["rule_id"] == "inline_month_day_v1"
    assert parsed["evidence_id"] == "source-a:table-0"
    assert parse_reported_time(raw, "computed_observed_utc", context())["timestamp_utc"] == (
        "unknown"
    )


def test_legacy_column_definitions_require_their_own_review() -> None:
    args = ("6/23 2121", "arrival_eta_utc", context(2001, 6, 23))
    assert parse_reported_time(*args, evidence=review("inline_month_day_v1"))["state"] == (
        "legacy_semantics_unverified"
    )
    parsed = parse_reported_time(
        *args, evidence=review("inline_month_day_v1", "legacy_definition_v1"),
    )
    assert parsed["timestamp_utc"] == "2001-06-23T21:21:00Z"
    assert "legacy_definition_v1" in parsed["rule_id"]


@pytest.mark.parametrize("raw", ["No ETA", "no eta", "??? 5/4", "? 11/17"])
def test_source_absence_with_date_is_never_a_numeric_arrival(raw: str) -> None:
    parsed = parse_reported_time(raw, "computed_observed_utc", context(), evidence={})
    assert parsed["state"] == "source_absent_explicit"
    assert parsed["timestamp_utc"] == "unknown"


@pytest.mark.parametrize("prefix", ["≈", "~", "approx "])
def test_qualifiers_retain_components_without_releasing_exact_time(prefix: str) -> None:
    parsed = parse_reported_time(prefix + "0007 1/14", "computed_observed_utc", context(),
                                 evidence=review("inline_month_day_v1"))
    assert parsed["state"] == "qualified_value" and parsed["timestamp_utc"] == "unknown"
    assert parsed["parsed_timestamp_utc"] == "2007-01-14T00:07:00Z"
    assert parsed["qualifier"] and parsed["hour"] == 0 and parsed["minute"] == 7


def test_footnotes_require_the_specific_annotation_review() -> None:
    args = ("0007 (014)*", "estimated_observed_utc_jday", context())
    blocked = parse_reported_time(*args, evidence={})
    assert blocked["state"] == "footnoted_value" and blocked["timestamp_utc"] == "unknown"
    assert blocked["parsed_timestamp_utc"] == "2007-01-14T00:07:00Z"
    allowed = parse_reported_time(*args, evidence=review("footnote_asterisk_v1"))
    assert allowed["timestamp_utc"] == "2007-01-14T00:07:00Z" and allowed["footnote"] == "*"


def test_distance_and_forecast_cannot_date_a_bare_clock() -> None:
    parsed = parse_reported_time("0007", "computed_observed_utc", context(),
                                 evidence=review("inline_month_day_v1", distance_km=5000,
                                                 expected_arrival="0009"))
    assert parsed["state"] == "date_ambiguous" and parsed["timestamp_utc"] == "unknown"


def test_clock_only_header_needs_explicit_day_semantics_review() -> None:
    args = ("0007 (014)", "computed_observed_utc", context())
    assert parse_reported_time(*args, evidence={})["state"] == "day_semantics_unverified"
    assert parse_reported_time(*args, evidence=review("source_doy_semantics_v1"))[
        "timestamp_utc"] == "2007-01-14T00:07:00Z"


@pytest.mark.parametrize(("raw", "state"), [
    ("2460 1/14", "invalid_clock"), ("0007 2/29", "invalid_calendar_date"),
    ("0007 1/14/08", "calendar_year_conflict"), ("0007 13/14", "invalid_calendar_date"),
])
def test_invalid_clocks_dates_and_year_conflicts_are_withheld(raw: str, state: str) -> None:
    parsed = parse_reported_time(raw, "computed_observed_utc", context(),
                                 evidence=review("inline_month_day_v1"))
    assert parsed["state"] == state and parsed["timestamp_utc"] == "unknown"


def test_new_year_needs_explicit_year_or_reviewed_rollover_context() -> None:
    ctx = context(2012, 12, 31)
    args = ("0007 1/1", "computed_observed_utc", ctx)
    assert parse_reported_time(*args, evidence=review("inline_month_day_v1"))[
        "state"] == "year_boundary_review_required"
    explicit = parse_reported_time("0007 1/1/13", "computed_observed_utc", ctx,
                                   evidence=review("inline_month_day_v1"))
    assert explicit["timestamp_utc"] == "2013-01-01T00:07:00Z"
    assert parse_reported_time(*args, evidence=review("inline_month_day_v1", rollover_year=2013))[
        "timestamp_utc"] == explicit["timestamp_utc"]


def test_unreviewed_or_unknown_evidence_rules_are_rejected() -> None:
    with pytest.raises(ValueError, match="review"):
        parse_reported_time("0007 1/14", "computed_observed_utc", context(),
                            evidence={"rule_ids": ["inline_month_day_v1"],
                                      "review_status": "pending"})
    with pytest.raises(ValueError, match="rule"):
        parse_reported_time("0007 1/14", "computed_observed_utc", context(),
                            evidence=review("physical_window_date_v1"))
