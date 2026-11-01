"""Availability evidence must not become invented causes or duplicate coverage."""

import pytest

from analysis.arrival.source_process import account, first_blocker


def report(key: str, estimate: str, observed: str) -> dict[str, str]:
    return {
        "report_id": key, "event_id": "development-event", "source_label": key,
        "structural_status": "accepted_source_row", "estimate_state": estimate,
        "observed_state": observed,
    }


def test_field_overlap_and_context_do_not_inflate_explained_rows() -> None:
    rows = [report("a", "exact_reported_timestamp", "blank"),
            report("b", "source_absent_explicit", "blank"),
            report("c", "blank", "exact_reported_timestamp")]
    links = [{"report_id": key, "field": "observed", "relation": "direct_field_reason"}
             for key in ["a", "b", "b"]]
    links.append({"report_id": "c", "field": "estimate", "relation": "incident_context"})
    result = account(rows, links)
    assert result["absent_fields"] == {"estimate": 2, "observed": 2}
    assert result["source_absence_reports"] == 3
    assert result["direct_reason_fields"] == 2
    assert result["reports_with_direct_reason"] == 2
    assert result["all_absent_fields_have_reason"] == 1
    assert result["some_absent_fields_still_unexplained"] == 2
    assert result["absence_reports_without_any_direct_reason"] == 1


def test_cause_cannot_be_attached_to_present_or_rejected_field() -> None:
    for row in [report("a", "blank", "exact_reported_timestamp"),
                dict(report("a", "blank", "blank"), structural_status="blank_row")]:
        with pytest.raises(ValueError, match="absent accepted field"):
            account([row], [{"report_id": "a", "field": "observed",
                             "relation": "direct_field_reason"}])


def test_incident_positive_control_remains_a_resolved_pair() -> None:
    row = report("a", "exact_reported_timestamp", "exact_reported_timestamp")
    result = account([row], [{"report_id": "a", "field": "observed",
                              "relation": "positive_control"}])
    assert first_blocker(row) == "resolved_pair"
    assert result["reports_with_direct_reason"] == 0


def test_first_blocker_retains_overlapping_calendar_information() -> None:
    assert first_blocker(report("a", "date_ambiguous", "blank")) == "source_time_entry_absent"
    assert first_blocker(report("b", "date_ambiguous", "qualified_value")) == "qualified_clock"
    assert first_blocker(report("c", "date_ambiguous", "exact_reported_timestamp")) == (
        "calendar_or_day_context_unresolved"
    )


def test_dangling_links_and_duplicate_reports_fail_closed() -> None:
    a = report("a", "blank", "blank")
    with pytest.raises(ValueError, match="unknown report"):
        account([a], [{"report_id": "absent", "field": "observed",
                       "relation": "direct_field_reason"}])
    with pytest.raises(ValueError, match="duplicate report"):
        account([a, a], [])


@pytest.mark.parametrize("change", [
    {"identity_approved": "True"}, {"parent_replacement_allowed": "True"},
    {"pair_approved": "True"}, {"arrival_utc": "2015-09-17T13:00:00Z"},
    {"event_id": "other-event"}, {"source_id": "other-source"},
    {"parent_report_candidate": "other-report"},
])
def test_alternative_statement_cannot_acquire_approvals_or_lose_source_binding(
    change: dict[str, str],
) -> None:
    from analysis.arrival.source_process import validate_alternative

    item = {"event_id": "dev", "source_id": "national-notice", "claim_id": "approx",
            "parent_report_candidate": "dev:1:1", "arrival_utc": "unknown",
            "identity_approved": "False", "pair_approved": "False",
            "parent_replacement_allowed": "False"}
    claim = {"event_id": "dev", "source_id": "national-notice", "claim_id": "approx",
             "evidence_class": "documented_alternative_observation"}
    parent = {"event_id": "dev", "report_id": "dev:1:1"}
    validate_alternative(item, claim, parent)
    with pytest.raises(ValueError, match="alternative observation"):
        validate_alternative(item | change, claim, parent)
