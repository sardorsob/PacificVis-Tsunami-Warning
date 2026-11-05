"""Small graph oracles for pre-model design diagnostics."""

import pytest

from scripts.build_arrival_model_design import design_checks, scale_scenarios


def rows(edges: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"record_id": str(i), "event_id": e, "physical_site_id": s,
             "distance_km": str((i+1)*100), "magnitude": "8", "depth_km": "20",
             "era": "old", "region": "Pacific", "mechanism": "unknown",
             "header_family": "native"} for i, (e, s) in enumerate(edges)]


def test_tree_has_no_cycle_but_repeat_is_not_a_new_contrast() -> None:
    summary, _, _ = design_checks(rows([("a", "s"), ("b", "s"), ("b", "t"), ("b", "t")]))
    assert summary["unique_edge_cycle_surplus"] == 0
    assert summary["row_surplus_over_rank"] == 1
    assert summary["repeated_edge_rows"] == 1


def test_square_and_disconnected_edge_have_one_cycle() -> None:
    summary, folds, aliases = design_checks(
        rows([("a", "s"), ("a", "t"), ("b", "s"), ("b", "t"), ("c", "u")]))
    assert summary["components"] == 2
    assert summary["unique_edge_cycle_surplus"] == 1
    assert summary["additive_indicator_rank"] == 4
    assert summary["row_weighted_seen_site_fraction"] == pytest.approx(4/5)
    assert summary["event_weighted_seen_site_fraction"] == pytest.approx(2/3)
    assert next(f for f in folds if f["event_id"] == "c")["seen_site_rows"] == "0"
    assert all(a["aliased_with_unrestricted_event_intercepts"] == "True" for a in aliases)


def test_within_between_distance_decomposition_and_permutation() -> None:
    data = rows([("a", "s"), ("a", "t"), ("b", "s"), ("b", "t")])
    data[0]["distance_km"] = data[1]["distance_km"] = "100"
    data[2]["distance_km"] = data[3]["distance_km"] = "1000"
    summary, _, _ = design_checks(data)
    assert summary["within_event_log_distance_fraction"] == 0
    assert summary == design_checks(list(reversed(data)))[0]
    data[1]["header_family"] = "other"
    _, _, aliases = design_checks(data)
    assert aliases[-1]["aliased_with_unrestricted_event_intercepts"] == "False"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_reject_invalid_distance(value: str) -> None:
    data = rows([("a", "s")])
    data[0]["distance_km"] = value
    with pytest.raises(ValueError, match="positive distance"):
        design_checks(data)


def test_unknown_identity_and_duplicate_record_fail() -> None:
    with pytest.raises(ValueError, match="unknown event/site"):
        design_checks(rows([("a", "unknown")]))
    data = rows([("a", "s")])
    with pytest.raises(ValueError, match="unique source-record"):
        design_checks(data+data)


def test_lognormal_scenario_is_multiplicatively_symmetric() -> None:
    for row in scale_scenarios():
        assert float(row["central_90_lower_ratio"])*float(row["central_90_upper_ratio"]) == \
            pytest.approx(1)
        assert float(row["conditional_mean_over_median"]) > 1
