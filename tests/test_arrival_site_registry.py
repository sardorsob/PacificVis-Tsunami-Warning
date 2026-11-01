"""Full-location review preserves country, subsite and coordinate conflicts."""

from __future__ import annotations

from typing import Any

import pytest

from analysis.arrival.site_registry import (
    bounded_clusters,
    label_key,
    parse_uhslc,
    validate_alias_review,
)


def test_bounded_name_rules_keep_region_and_subsite() -> None:
    assert label_key("San Francisco, California") == label_key("San_Fransico,_CA")
    assert label_key("Ofunato, JP") == label_key("Ofunato,_Japan")
    assert label_key("Luganville, Solomon Islands") != label_key("Lunganville, Vanuatu")
    assert label_key("Raoul Island, Boat Cove, NZ") != label_key("Raoul Island, Fishing Rock, NZ")
    assert label_key("Tofino, BC, Canada") != label_key("Tofino, CA")


def test_spatial_sensitivity_never_bridges_neighbors() -> None:
    points = [
        {"id": str(i), "name_key": "same", "latitude": "0", "longitude": str(lon)}
        for i, lon in enumerate([0, 0.008, 0.016])
    ]
    groups = bounded_clusters(points, 1)
    assert len(set(groups.values())) == 2
    assert not (groups["0"] == groups["1"] == groups["2"])
    assert bounded_clusters(list(reversed(points)), 1) == groups
    with pytest.raises(ValueError):
        bounded_clusters(points, float("nan"))


def test_antimeridian_and_family_do_not_create_false_merge() -> None:
    points = [
        {"id": "a", "name_key": "coastal:Example", "latitude": "0", "longitude": "179.999"},
        {"id": "b", "name_key": "coastal:Example", "latitude": "0", "longitude": "-179.999"},
        {"id": "c", "name_key": "DART:Example", "latitude": "0", "longitude": "179.999"},
    ]
    groups = bounded_clusters(points, 1)
    assert groups["a"] == groups["b"]
    assert groups["c"] != groups["a"]


def test_alias_review_cannot_override_wrong_country_or_no_corroboration() -> None:
    alt: dict[str, Any] = {
        "event_id": "dev",
        "report_label": "Ofunato, JP",
        "headers": [{"header_name": "Ofunato,_Japan"}],
        "registry_id_checks": [],
        "label_alias_review": {"method": "full_location_key_v1", "ncei": []},
    }
    with pytest.raises(ValueError, match="corroboration"):
        validate_alias_review(alt)
    alt["registry_id_checks"] = [{"provider": "CO-OPS", "station_id": "1"}]
    assert validate_alias_review(alt) == "Ofunato,_Japan"
    alt["report_label"] = "Ofunato, Chile"
    with pytest.raises(ValueError, match="full location"):
        validate_alias_review(alt)


def test_uhslc_native_rows_and_coverage_dates_are_not_deployments() -> None:
    text = (
        '<table><tr id="000002d"><td>002</td><td>113</td><td>Tarawa</td>'
        "<td>Kiribati</td><td>1.3633</td><td>172.9300</td>"
        "<td>1992-12-04</td><td>2026-09-30</td></tr></table>"
    )
    rows = parse_uhslc(text)
    assert rows[0]["native_row_id"] == "000002d"
    assert rows[0]["latitude"] == "1.3633"
    assert rows[0]["record_start"] == "1992-12-04"
    assert rows[0]["deployment_continuity"] == "unknown"
