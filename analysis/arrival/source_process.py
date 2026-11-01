"""Field-level accounting for reviewed source-process evidence."""

from collections import Counter
from typing import Any

from analysis.arrival.evidence import Row

ABSENT = frozenset({"blank", "source_absent_explicit"})
CALENDAR = frozenset({"date_ambiguous", "calendar_context_missing", "day_semantics_unverified"})
RELATIONS = frozenset({"direct_field_reason", "incident_context", "definition_conflict",
                       "positive_control", "not_applicable_to_missing_field"})


def first_blocker(row: Row) -> str:
    """Assign one reporting blocker, preserving field overlaps elsewhere."""
    states = {row["estimate_state"], row["observed_state"]}
    if row["structural_status"] != "accepted_source_row":
        return "structural_or_blank_row"
    if states == {"exact_reported_timestamp"}:
        return "resolved_pair"
    if states & ABSENT:
        return "source_time_entry_absent"
    for state, reason in [("qualified_value", "qualified_clock"),
                          ("footnoted_value", "footnoted_clock"),
                          ("legacy_semantics_unverified", "column_meaning_unverified")]:
        if state in states:
            return reason
    if states & CALENDAR:
        return "calendar_or_day_context_unresolved"
    raise ValueError(f"unclassified report: {row['report_id']}")


def account(reports: list[Row], links: list[Row]) -> dict[str, Any]:
    """Count unique absent fields, never treating contextual links as causes."""
    by_id = {row["report_id"]: row for row in reports}
    if len(by_id) != len(reports):
        raise ValueError("duplicate report ID")
    absent = {(r["report_id"], field) for r in reports
              if r["structural_status"] == "accepted_source_row"
              for field in ("estimate", "observed") if r[f"{field}_state"] in ABSENT}
    explained: set[tuple[str, str]] = set()
    for link in links:
        if link["report_id"] not in by_id:
            raise ValueError("unknown report in evidence link")
        if link["field"] not in {"estimate", "observed", "waveform"}:
            raise ValueError("unknown evidence field")
        if link["relation"] not in RELATIONS:
            raise ValueError("unknown evidence relation")
        if link["relation"] == "direct_field_reason":
            key = (link["report_id"], link["field"])
            if key not in absent:
                raise ValueError("direct reason requires an absent accepted field")
            explained.add(key)
    absent_ids = {key for key, _ in absent}
    explained_ids = {key for key, _ in explained}
    still_unexplained = {key for key, _ in absent - explained}
    accepted = [r for r in reports if r["structural_status"] == "accepted_source_row"]
    return {
        "reports": len(reports), "accepted_field_mappings": len(accepted),
        "first_blockers": dict(sorted(Counter(first_blocker(r) for r in reports).items())),
        "absent_fields": {f: sum(field == f for _, field in absent)
                          for f in ("estimate", "observed")},
        "both_fields_absent": sum(all((key, f) in absent for f in ("estimate", "observed"))
                                  for key in absent_ids),
        "source_absence_reports": len(absent_ids),
        "any_calendar_problem_reports": sum(
            bool({r["estimate_state"], r["observed_state"]} & CALENDAR) for r in accepted
        ),
        "direct_reason_fields": len(explained),
        "reports_with_direct_reason": len(explained_ids),
        "all_absent_fields_have_reason": len(absent_ids - still_unexplained),
        "some_absent_fields_still_unexplained": len(still_unexplained),
        "absence_reports_without_any_direct_reason": len(absent_ids - explained_ids),
        "absent_fields_without_direct_reason": len(absent - explained),
    }


def validate_alternative(item: Row, claim: Row, parent: Row) -> None:
    """Reject inferred timestamps, approval changes and broken source/event links."""
    if (item["arrival_utc"] != "unknown" or any(item[key] != "False" for key in (
            "identity_approved", "pair_approved", "parent_replacement_allowed")) or
            item["event_id"] != claim["event_id"] or
            item["event_id"] != parent["event_id"] or
            item["source_id"] != claim["source_id"] or
            item["claim_id"] != claim["claim_id"] or
            item["parent_report_candidate"] != parent["report_id"] or
            claim["evidence_class"] != "documented_alternative_observation"):
        raise ValueError("unapproved or unbound alternative observation")
