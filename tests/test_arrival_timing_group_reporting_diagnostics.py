"""Sparse support and selection diagnostics preserve their scientific denominators."""

from analysis.arrival.timing_group_reporting_and_support_diagnostics import (
    availability_table,
    group_profile,
    paired_differences,
)


def test_availability_conserves_structural_and_accepted_denominators() -> None:
    rows = [
        {"era": "a", "structural_status": "accepted_source_row", "exact_observed": 1},
        {"era": "a", "structural_status": "accepted_source_row", "exact_observed": 0},
        {"era": "a", "structural_status": "blank_row", "exact_observed": 0},
    ]
    row = availability_table(rows, "era")[0]
    assert row["retained_rows"] == 3 and row["accepted_rows"] == 2
    assert row["exact_observed"] == 1 and row["availability"] == 0.5


def test_geographic_link_is_comparison_without_cartesian_expansion() -> None:
    a = [{"event_id": "e", "physical_site_id": "s", "target_minutes": 10.0}]
    b = [
        {"event_id": "e", "physical_site_id": "s", "target_minutes": 12.0},
        {"event_id": "e", "physical_site_id": "s", "target_minutes": 14.0},
    ]
    result = paired_differences(a, b)
    assert len(result) == 1 and result[0]["difference_minutes"] == -3
    assert result[0]["lineage_state"] == "unresolved"
    assert result[0]["independence_established"] is False


def test_disconnected_group_effects_remain_component_relative() -> None:
    rows = [
        {"event_id": e, "physical_site_id": s, "r0": y}
        for e, s, y in [("a", "x", 1.0), ("b", "x", 2.0), ("c", "z", 3.0)]
    ]
    summary, effects = group_profile(rows, "physical_site_id", repeats=3)
    assert summary["components"] == 2 and summary["raw_rows"] == 3
    assert len(effects) == 5
    assert all(r["component_relative"] for r in effects)
    assert summary["largest_component_rows"] == 2
