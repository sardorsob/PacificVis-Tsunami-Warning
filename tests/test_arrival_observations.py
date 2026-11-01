"""Measurements retain source origins and distinguish geographic from latent identity."""

import json

from analysis.arrival.observations import design_support, entity_id, ncei_measurement, opportunity


def test_unknown_sites_do_not_count_as_a_shared_repeat() -> None:
    result = design_support([{"event_id": e, "physical_site_id": "unknown"} for e in ["a", "b"]])
    assert result["sites"] == 0
    assert result["sites_with_at_least_events"]["2"] == 0


def test_incompatible_definitions_and_unreviewed_sites_never_merge() -> None:
    assert entity_id("e", "site", "coastal", "first", "a") != entity_id(
        "e", "site", "coastal", "crest", "a"
    )
    assert entity_id("e", "unknown", "coastal", "first", "a") != entity_id(
        "e", "unknown", "coastal", "first", "b"
    )


def test_native_origin_duration_and_unknown_covariates_survive() -> None:
    row = {
        "source_record_id": "n:1",
        "development_event_id": "e",
        "measurement_family": "tide_gauge",
        "event_match_json": json.dumps(
            {"ncei_origin_utc": "2000-01-01T00:00:00Z", "origin_difference_seconds": "80.19"}
        ),
        "reported_duration_minutes": "31",
        "arrival_utc": "unknown",
        "travel_state": "complete_positive",
        "duration_candidate": "True",
        "raw_record_json": "{}",
    }
    result = ncei_measurement(row, "unknown", "lineage:1")
    assert result["duration_minutes"] == "31"
    assert result["origin_difference_seconds"] == "80.19"
    assert result["source_native_origin"] == "2000-01-01T00:00:00Z"
    assert result["first_motion"] == "unknown"
    assert result["peak_amplitude_native"] == "unknown"
    row["raw_record_json"] = '{"firstMotion":null,"runupHt":null}'
    assert ncei_measurement(row, "unknown", "l")["peak_amplitude_native"] == "unknown"
    assert opportunity("n:1", "e")["reporting_state"] == "source_record_exists"
    assert opportunity("n:1", "e")["historical_operating_state"] == "unknown"
