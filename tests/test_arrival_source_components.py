"""Synthetic native-field consistency and outcome-access boundary checks."""

# pyright: basic

import json
from pathlib import Path

import pytest

from analysis.arrival import model_source_components as audit
from analysis.arrival.evidence import sha256


def native(**changes):
    return {
        "year": 2014,
        "month": 4,
        "day": 13,
        "hour": 12,
        "minute": 36,
        "second": 19.2,
        "arrDay": 13,
        "arrHour": 13,
        "arrMin": 0,
        "travHours": 0,
        "travMins": 24,
        **changes,
    }


def test_native_seconds_and_zero_hours_are_preserved():
    result = audit.assess_components(native(), 60)
    assert result["assessment"] == "assessed"
    assert result["clock_modulo_residual_minutes"] == pytest.approx(-0.32)
    assert not result["large_component_disagreement"]


def test_known_inconsistent_pattern_is_not_repaired():
    result = audit.assess_components(
        native(arrDay=2, arrHour=18, arrMin=32, travHours=18, travMins=45), 60
    )
    assert result["clock_modulo_residual_minutes"] == pytest.approx(670.68)
    assert result["large_component_disagreement"]
    assert "arrival_utc" not in result


def test_midnight_and_multiple_days_have_same_clock_residual():
    a = native(
        hour=23, minute=30, second=0, arrDay=14, arrHour=0, arrMin=30, travHours=1, travMins=0
    )
    b = {**a, "arrDay": 16, "travHours": 49}
    assert audit.assess_components(a, 60)["clock_modulo_residual_minutes"] == 0
    assert audit.assess_components(b, 60)["clock_modulo_residual_minutes"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("travHours", None),
        ("second", None),
        ("arrMin", 60),
        ("arrDay", 0),
        ("year", True),
        ("travMins", float("nan")),
    ],
)
def test_incomplete_invalid_components_are_explicitly_unassessed(field, value):
    result = audit.assess_components(native(**{field: value}), 60)
    assert result["assessment"] == "unassessed"
    assert result["clock_modulo_residual_minutes"] is None
    assert result["large_component_disagreement"] is None


def source(root, identity, event, number=1, escaped=False):
    relative = f"data/raw/arrival-recovery/ncei-development-v1/{identity}.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": [{"id": 1}]}))
    metadata = json.dumps(
        {
            "development_event_id": event,
            "event_id": event,
            "ncei_event_id": number,
            "ncei_origin_utc": "2014-04-13T12:36:19.200000+00:00",
        }
    )
    if escaped:
        metadata = metadata.replace('"', '\\"')
    return {
        "source_id": identity,
        "publisher": "NOAA NCEI",
        "local_path": relative,
        "sha256": sha256(path),
        "url": f"https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/runups?tsunamiEventId={number}&typeMeasurementId=2&typeMeasurementId=3&itemsPerPage=200&page=1",
        "notes": json.dumps({"station_metadata": metadata}),
    }


@pytest.mark.parametrize("escaped", [False, True])
def test_safe_source_preflight_binds_event_request_hash_before_parse(tmp_path, escaped):
    metadata = source(tmp_path, "recovery-ncei-fixture", "e1", escaped=escaped)
    rows = [{"record_id": "recovery-ncei-fixture:1", "event_id": "e1"}]
    prepared = audit.prepare_sources(tmp_path, rows, [metadata], {"e1"})
    assert prepared["recovery-ncei-fixture"]["ncei_event_id"] == 1
    (tmp_path / metadata["local_path"]).write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        audit.prepare_sources(tmp_path, rows, [metadata], {"e1"})


def test_wrong_event_role_rejected_without_any_raw_parse(tmp_path, monkeypatch):
    known = source(tmp_path, "recovery-ncei-fixture", "e1")
    protected = source(tmp_path, "recovery-ncei-protected", "confirmation")
    rows = [
        {"record_id": "recovery-ncei-fixture:1", "event_id": "e1"},
        {"record_id": "recovery-ncei-protected:1", "event_id": "confirmation"},
    ]
    original = Path.read_text

    def guard(path, *args, **kwargs):
        assert "data/raw" not in str(path), "raw outcome parsed before global role guard"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)
    with pytest.raises(ValueError, match="exploration"):
        audit.prepare_sources(tmp_path, rows, [known, protected], {"e1"})


def test_request_mismatch_and_duplicate_source_fail(tmp_path):
    metadata = source(tmp_path, "recovery-ncei-fixture", "e1")
    rows = [{"record_id": "recovery-ncei-fixture:1", "event_id": "e1"}]
    with pytest.raises(ValueError, match="duplicate"):
        audit.prepare_sources(tmp_path, rows, [metadata, metadata], {"e1"})
    metadata["url"] = metadata["url"].replace("tsunamiEventId=1", "tsunamiEventId=2")
    with pytest.raises(ValueError, match="request"):
        audit.prepare_sources(tmp_path, rows, [metadata], {"e1"})


def audited_fixture(tmp_path):
    metadata = source(tmp_path, "recovery-ncei-fixture", "e1")
    station = json.loads(json.loads(metadata["notes"])["station_metadata"])
    station["ncei_origin_utc"] = "2014-04-13T12:36:19.200000+00:00"
    metadata["notes"] = json.dumps({"station_metadata": json.dumps(station)})
    item = {
        **native(),
        "id": 99,
        "tsunamiEventId": 1,
        "typeMeasurementId": 2,
        "locationName": "Station",
    }
    path = tmp_path / metadata["local_path"]
    path.write_text(json.dumps({"items": [item], "page": 1}))
    metadata["sha256"] = sha256(path)
    row = {
        "record_id": "recovery-ncei-fixture:1",
        "event_id": "e1",
        "source_label": "Station",
        "target_minutes": "24",
        "physical_site_id": "s1",
    }
    return metadata, row, item


def test_census_preserves_role_native_id_and_target(tmp_path):
    metadata, row, _ = audited_fixture(tmp_path)
    results, pins = audit.audit_records(tmp_path, [row], [False], [metadata], {"e1"}, 60)
    assert results[0]["native_item_id"] == 99
    assert not results[0]["included_primary"]
    assert results[0]["reported_minutes"] == 24
    assert results[0]["clock_modulo_residual_minutes"] == pytest.approx(-0.32)
    assert pins == {metadata["local_path"]: metadata["sha256"]}


@pytest.mark.parametrize("field,value", [("source_label", "Other"), ("target_minutes", "25")])
def test_wrong_source_position_or_target_is_fatal(tmp_path, field, value):
    metadata, row, _ = audited_fixture(tmp_path)
    row[field] = value
    with pytest.raises(ValueError, match="mismatch"):
        audit.audit_records(tmp_path, [row], [True], [metadata], {"e1"}, 60)


def test_source_native_origin_not_usgs_is_controlling(tmp_path):
    metadata, row, item = audited_fixture(tmp_path)
    item["second"] = 19.23  # USGS precision differs; it cannot replace native origin.
    path = tmp_path / metadata["local_path"]
    path.write_text(json.dumps({"items": [item], "page": 1}))
    metadata["sha256"] = sha256(path)
    with pytest.raises(ValueError, match="origin"):
        audit.audit_records(tmp_path, [row], [True], [metadata], {"e1"}, 60)


def test_half_day_boundary_has_declared_signed_convention():
    item = native(hour=0, minute=0, second=0, arrHour=12, arrMin=0, travHours=0, travMins=0)
    assert audit.assess_components(item, 60)["clock_modulo_residual_minutes"] == -720


@pytest.mark.parametrize("metadata_origin", [None, "unknown", "2014-04-13T12:36:19.2"])
def test_native_origin_metadata_must_be_valid_utc_before_raw_parse(tmp_path, metadata_origin):
    metadata, row, _ = audited_fixture(tmp_path)
    station = json.loads(json.loads(metadata["notes"])["station_metadata"])
    station["ncei_origin_utc"] = metadata_origin
    metadata["notes"] = json.dumps({"station_metadata": json.dumps(station)})
    with pytest.raises(ValueError, match="native origin metadata"):
        audit.prepare_sources(tmp_path, [row], [metadata], {"e1"})


def test_missing_arrival_cannot_bypass_complete_native_origin_guard(tmp_path):
    metadata, row, item = audited_fixture(tmp_path)
    item["second"] = 19.23
    del item["arrMin"]
    path = tmp_path / metadata["local_path"]
    path.write_text(json.dumps({"items": [item], "page": 1}))
    metadata["sha256"] = sha256(path)
    with pytest.raises(ValueError, match="origin"):
        audit.audit_records(tmp_path, [row], [True], [metadata], {"e1"}, 60)


@pytest.mark.parametrize("escaped", [False, True])
def test_explicit_pagination_evidence_controls_inherited_parent_page(tmp_path, escaped):
    metadata, row, _ = audited_fixture(tmp_path)
    parent = source(tmp_path, "recovery-ncei-parent", "e1", escaped=escaped)
    proof = tmp_path / "artifacts/generated/ntwc-batch/recovery-execution-v1/fixture-check.json"
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_text("{}")
    station = json.loads(json.loads(metadata["notes"])["station_metadata"])
    station["page"] = 1
    station["pagination_evidence"] = {
        "page_requested": 2,
        "total_pages": 3,
        "page1_source_id": parent["source_id"],
        "page1_sha256": parent["sha256"],
        "qa_receipt": str(proof.relative_to(tmp_path)),
        "qa_sha256": sha256(proof),
    }
    metadata["url"] = metadata["url"].replace("page=1", "page=2")
    metadata["notes"] = json.dumps({"station_metadata": json.dumps(station)})
    path = tmp_path / metadata["local_path"]
    response = json.loads(path.read_text())
    response["page"] = 2
    path.write_text(json.dumps(response))
    metadata["sha256"] = sha256(path)
    results, pins = audit.audit_records(tmp_path, [row], [True], [metadata, parent], {"e1"}, 60)
    assert results[0]["assessment"] == "assessed"
    assert pins[str(proof.relative_to(tmp_path))] == sha256(proof)
    proof.write_text("tampered")
    with pytest.raises(ValueError, match="pagination"):
        audit.prepare_sources(tmp_path, [row], [metadata, parent], {"e1"})

    proof.write_text("{}")
    station["pagination_evidence"]["total_pages"] = True
    metadata["notes"] = json.dumps({"station_metadata": json.dumps(station)})
    with pytest.raises(ValueError, match="pagination"):
        audit.prepare_sources(tmp_path, [row], [metadata, parent], {"e1"})
