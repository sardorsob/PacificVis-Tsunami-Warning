"""Metadata screen excludes outcomes even when present upstream."""

from scripts.prepare_arrival_expansion import project_metadata


def test_only_whitelisted_fields_survive_and_outcomes_do_not_change_selection() -> None:
    native = {"id": 1, "year": 2021, "latitude": 1, "eqMagnitude": 7.2}
    first = project_metadata(native)
    assert first == project_metadata(
        {**native, "numRunups": 99, "maxWaterHeight": 200, "deaths": 400, "arrival": "12:30"}
    )
    assert "numRunups" not in first
    assert "deaths" not in first
    assert first["month"] == "unknown"
